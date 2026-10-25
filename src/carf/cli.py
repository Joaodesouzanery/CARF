import argparse
import json
import sys
from pathlib import Path

from . import anonimizador, config, gerenciais, parallel
from .auditoria import auditar
from .monitor import verificar_indice, vigiar_paginas
from .privacy import Anonymizer
from .qa import consulta
from .solr import SolrClient
from .store import Store
from .sync import State, sincronizar


def _anonimizador(args) -> Anonymizer:
    try:
        return anonimizador.criar(args.sem_ner, args.manter_cnpj)
    except RuntimeError as exc:
        sys.exit(str(exc))


def _estado() -> State:
    return State(config.DATA_DIR / "state.json")


def cmd_status(args):
    print(json.dumps(parallel.status(config.DATA_DIR), ensure_ascii=False, indent=2))


def cmd_texto(args):
    from .texto import baixar_texto

    linha = baixar_texto(SolrClient(), Store(config.DATA_DIR), _anonimizador(args), args.id)
    if linha is None:
        sys.exit(f"id {args.id} não encontrado no índice")
    print(f"{consulta.citacao(linha)}\n\n{linha['conteudo'][:args.preview]}")


def cmd_sync(args):
    if args.workers > 1:
        r = parallel.sincronizar_paralelo(
            config.DATA_DIR, args.ano_min, args.workers, leve=args.leve, sem_ner=args.sem_ner,
            manter_cnpj=args.manter_cnpj, limite=args.limite)
        print(json.dumps(r, ensure_ascii=False))
        return
    r = sincronizar(SolrClient(), Store(config.DATA_DIR), _estado(), _anonimizador(args),
                    ano_min=args.ano_min, limite=args.limite, incremental=args.incremental,
                    leve=args.leve)
    print(json.dumps(r, ensure_ascii=False))


def cmd_check(args):
    r = verificar_indice(SolrClient(), _estado())
    if args.paginas:
        r["paginas"] = vigiar_paginas(_estado(), config.DATA_DIR, baixar=not args.sem_download)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(10 if r["ha_atualizacao"] else 0)


def cmd_embed(args):
    from .embeddings import Indice, criar_embedder, indexar

    n = indexar(Store(config.DATA_DIR).connect(), Indice(config.DATA_DIR, args.modelo),
                criar_embedder(args.modelo), limite=args.limite)
    print(f"{n} acórdãos vetorizados com {args.modelo}")


def cmd_search(args):
    con = Store(config.DATA_DIR).connect()
    if args.modo == "lexico":
        resultados = consulta.buscar(con, args.termos, _filtros(args), args.limite, qualquer=args.qualquer)
    else:
        from .embeddings import Indice, criar_embedder
        from .qa import semantico

        resultados = semantico.buscar(
            con, args.termos, _filtros(args), args.limite, args.modo,
            Indice(config.DATA_DIR, args.modelo).carregar(), criar_embedder(args.modelo))
    for r in resultados:
        print(f"- {r['citacao']}\n  {(r['ementa'] or '')[:300]}\n")


def cmd_stats(args):
    con = Store(config.DATA_DIR).connect()
    fn = consulta.taxa_resultado if args.resultado else consulta.contagem
    print(fn(con, args.por, _filtros(args)).to_string(index=False))


def cmd_review(args):
    from . import review

    if args.acao == "amostra":
        con = Store(config.DATA_DIR).connect()
        ner = None if args.sem_ner else _anonimizador(args).nomes
        print(json.dumps(review.amostrar(con, args.n, args.seed, config.DATA_DIR / "review", ner),
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(review.pontuar(args.arquivo), ensure_ascii=False, indent=2))


def cmd_audit(args):
    if args.profundo:
        from .auditoria import auditar_profundo

        ner = None if args.sem_ner else _anonimizador(args).nomes
        r = auditar_profundo(Store(config.DATA_DIR).connect(), args.n, args.seed, ner)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(1 if r["docs_com_candidatos"] else 0)
    r = auditar(Store(config.DATA_DIR).connect())
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(1 if r["residuos"] else 0)


def cmd_ask(args):
    from .embeddings import Indice, criar_embedder
    from .qa import gerenciais as qg
    from .qa.ask import perguntar

    ger = qg.conectar() if (config.DATA_DIR / "gerenciais").exists() else None
    indice = Indice(config.DATA_DIR, args.modelo)
    sem = (indice.carregar(), criar_embedder(args.modelo)) if indice.ids_existentes() else None
    print(perguntar(Store(config.DATA_DIR).connect(), args.pergunta, ger=ger, sem=sem))


def cmd_compact(args):
    print(f"{Store(config.DATA_DIR).compact()} arquivos substituídos")


def cmd_gerenciais(args):
    from .qa import gerenciais as qg

    anon = None
    if args.acao in ("atualizar", "reingerir") and args.com_ementa and not args.sem_anonimizar:
        anon = _anonimizador(args)
    if args.acao == "reingerir":
        print(json.dumps(gerenciais.reingerir(config.DATA_DIR, anon, com_texto=args.com_ementa),
                         ensure_ascii=False, indent=2))
        return
    if args.acao == "atualizar":
        print(json.dumps(gerenciais.atualizar(config.DATA_DIR, anon, workers=args.workers, sem_ner=args.sem_ner,
                                              manter_cnpj=args.manter_cnpj, com_texto=args.com_ementa),
                         ensure_ascii=False, indent=2))
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
    s.add_argument("--leve", action="store_true",
                   help="metadados + ementa + decisão (sem o voto integral): rápido")
    s.add_argument("--workers", type=int, default=1, help="processos em paralelo (fatias ano x seção)")
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
    q.add_argument("--modo", choices=["lexico", "semantico", "hibrido"], default="lexico")
    q.add_argument("--modelo", default="spacy", help="e5-small, minilm, e5-large ou spacy")
    q.add_argument("--qualquer", action="store_true", help="léxico: basta um dos termos")
    filtros(q)
    q.set_defaults(fn=cmd_search)

    t = sub.add_parser("stats", help="contagens e resultados por dimensão")
    t.add_argument("por", choices=sorted(consulta.DIMENSOES))
    t.add_argument("--resultado", action="store_true")
    filtros(t)
    t.set_defaults(fn=cmd_stats)

    g = sub.add_parser("gerenciais", help="dados abertos oficiais: Julgamentos e Estoque")
    g.add_argument("acao", choices=["atualizar", "reingerir", "desfechos", "estoque"])
    g.add_argument("por", nargs="?", default="tributo")
    g.add_argument("--workers", type=int, default=1, help="processos para anonimizar anos em paralelo")
    g.add_argument("--sem-ner", action="store_true")
    g.add_argument("--manter-cnpj", action="store_true")
    g.add_argument("--com-ementa", action="store_true",
                   help="guarda também ementa/decisão do CSV (anonimizadas); por padrão não guarda")
    g.add_argument("--sem-anonimizar", action="store_true", help="não passa a ementa pelo anonimizador")
    g.set_defaults(fn=cmd_gerenciais)

    e = sub.add_parser("embed", help="vetoriza ementas para a busca semântica")
    e.add_argument("--modelo", default="spacy", help="e5-small, minilm, e5-large ou spacy")
    e.add_argument("--limite", type=int)
    e.set_defaults(fn=cmd_embed)
    sub.add_parser("status", help="progresso da carga paralela").set_defaults(fn=cmd_status)
    x = sub.add_parser("texto", help="baixa e anonimiza o voto integral de um acórdão (por id)")
    x.add_argument("id")
    x.add_argument("--preview", type=int, default=1500)
    x.add_argument("--sem-ner", action="store_true")
    x.add_argument("--manter-cnpj", action="store_true")
    x.set_defaults(fn=cmd_texto)

    au = sub.add_parser("audit", help="varre a base atrás de identificadores")
    au.add_argument("--profundo", action="store_true", help="detectores independentes, em amostra")
    au.add_argument("--n", type=int, default=200)
    au.add_argument("--seed", type=int, default=1)
    au.add_argument("--sem-ner", action="store_true")
    au.add_argument("--manter-cnpj", action="store_true")
    au.set_defaults(fn=cmd_audit)
    rv = sub.add_parser("review", help="revisão humana da anonimização")
    rv.add_argument("acao", choices=["amostra", "pontuar"])
    rv.add_argument("arquivo", nargs="?", type=Path, help="CSV marcado (para pontuar)")
    rv.add_argument("--n", type=int, default=100)
    rv.add_argument("--seed", type=int, default=1)
    rv.add_argument("--sem-ner", action="store_true")
    rv.add_argument("--manter-cnpj", action="store_true")
    rv.set_defaults(fn=cmd_review)
    sub.add_parser("compact", help="remove versões antigas").set_defaults(fn=cmd_compact)
    a = sub.add_parser("ask", help="pergunta em linguagem natural (requer ANTHROPIC_API_KEY)")
    a.add_argument("pergunta")
    a.add_argument("--modelo", default="spacy", help="modelo de embeddings da busca semântica")
    a.set_defaults(fn=cmd_ask)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
