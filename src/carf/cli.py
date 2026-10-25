import argparse
import json
import sys

from . import config, gerenciais
from .auditoria import auditar
from .monitor import verificar_indice, vigiar_paginas
from .privacy import Anonymizer
from .privacy.ner import NomesPorContexto, SpacyNomes
from .qa import consulta
from .solr import SolrClient
from .store import Store
from .sync import State, sincronizar


def _anonimizador(args) -> Anonymizer:
    try:
        nomes = SpacyNomes()
    except Exception as exc:  # noqa: BLE001
        if not args.sem_ner:
            sys.exit(f"NER indisponível ({exc}). Instale `.[ner]` ou use --sem-ner para a "
                     "reserva por contexto (recall muito menor; não use em produção).")
        nomes = NomesPorContexto()
    return Anonymizer(nomes=nomes, mascarar_cnpj=not args.manter_cnpj)


def _estado() -> State:
    return State(config.DATA_DIR / "state.json")


def cmd_sync(args):
    r = sincronizar(SolrClient(), Store(config.DATA_DIR), _estado(), _anonimizador(args),
                    ano_min=args.ano_min, limite=args.limite, incremental=args.incremental)
    print(json.dumps(r, ensure_ascii=False))


def cmd_check(args):
    r = verificar_indice(SolrClient(), _estado())
    if args.paginas:
        r["paginas"] = vigiar_paginas(_estado(), config.DATA_DIR, baixar=not args.sem_download)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(10 if r["ha_atualizacao"] else 0)


def cmd_search(args):
    con = Store(config.DATA_DIR).connect()
    for r in consulta.buscar(con, args.termos, _filtros(args), args.limite):
        print(f"- {r['citacao']}\n  {(r['ementa'] or '')[:300]}\n")


def cmd_stats(args):
    con = Store(config.DATA_DIR).connect()
    fn = consulta.taxa_resultado if args.resultado else consulta.contagem
    print(fn(con, args.por, _filtros(args)).to_string(index=False))


def cmd_audit(args):
    r = auditar(Store(config.DATA_DIR).connect())
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(1 if r["residuos"] else 0)


def cmd_ask(args):
    from .qa.ask import perguntar

    print(perguntar(Store(config.DATA_DIR).connect(), args.pergunta))


def cmd_compact(args):
    print(f"{Store(config.DATA_DIR).compact()} arquivos substituídos")


def cmd_gerenciais(args):
    from .qa import gerenciais as qg

    if args.acao == "atualizar":
        anon = None if args.sem_anonimizar else _anonimizador(args)
        print(json.dumps(gerenciais.atualizar(config.DATA_DIR, anon), ensure_ascii=False, indent=2))
        return
    con = qg.conectar()
    if args.acao == "desfechos":
        print(qg.desfecho_por(con, args.por).to_string(index=False))
    else:
        df = qg.estoque_por(con, args.por)
        print(f"Estoque em {df.attrs['referencia']}\n{df.to_string(index=False)}")


def _filtros(args) -> dict:
    return {k: getattr(args, k) for k in ("ano", "turma", "camara", "secao", "relator")
            if getattr(args, k, None) is not None}


def main(argv=None):
    p = argparse.ArgumentParser(prog="carf")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("sync", help="baixa e anonimiza acórdãos")
    s.add_argument("--ano-min", type=int, help="recorte: sessões a partir deste ano")
    s.add_argument("--limite", type=int, help="para após N documentos (teste)")
    s.add_argument("--incremental", action="store_true", help="só o que mudou desde a última carga")
    s.add_argument("--sem-ner", action="store_true")
    s.add_argument("--manter-cnpj", action="store_true", help="não mascara CNPJ")
    s.set_defaults(fn=cmd_sync)

    c = sub.add_parser("check", help="há atualização? (código de saída 10 = sim)")
    c.add_argument("--paginas", action="store_true", help="também vigia PDFs gerenciais do CARF")
    c.add_argument("--sem-download", action="store_true")
    c.set_defaults(fn=cmd_check)

    def filtros(sp):
        sp.add_argument("--ano", type=int)
        for f in ("turma", "camara", "secao", "relator"):
            sp.add_argument(f"--{f}")

    q = sub.add_parser("search", help="busca por termos")
    q.add_argument("termos")
    q.add_argument("--limite", type=int, default=10)
    filtros(q)
    q.set_defaults(fn=cmd_search)

    t = sub.add_parser("stats", help="contagens e resultados por dimensão")
    t.add_argument("por", choices=sorted(consulta.DIMENSOES))
    t.add_argument("--resultado", action="store_true")
    filtros(t)
    t.set_defaults(fn=cmd_stats)

    g = sub.add_parser("gerenciais", help="dados abertos oficiais: Julgamentos e Estoque")
    g.add_argument("acao", choices=["atualizar", "desfechos", "estoque"])
    g.add_argument("por", nargs="?", default="tributo")
    g.add_argument("--sem-ner", action="store_true")
    g.add_argument("--manter-cnpj", action="store_true")
    g.add_argument("--sem-anonimizar", action="store_true", help="não passa a ementa pelo anonimizador")
    g.set_defaults(fn=cmd_gerenciais)

    sub.add_parser("audit", help="varre a base atrás de identificadores").set_defaults(fn=cmd_audit)
    sub.add_parser("compact", help="remove versões antigas").set_defaults(fn=cmd_compact)
    a = sub.add_parser("ask", help="pergunta em linguagem natural (requer ANTHROPIC_API_KEY)")
    a.add_argument("pergunta")
    a.set_defaults(fn=cmd_ask)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
