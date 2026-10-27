"""Gera os dados do painel HTML: um JSON por ano (colunar, com dicionários), tendências do dado
oficial, estoque, a amostra de revisão LGPD e pesquisas prontas (opcional, usa o índice e5).

Uso: python scripts/painel/exportar.py DATA_DIR SAIDA_DIR [--revisao revisao/amostra-....md] [--prontas]
"""

import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from carf.qa import consulta
from carf.qa import gerenciais as qg
from carf.store import Store

LINK = "https://acordaos.economia.gov.br/acordaos2/pdfs/processados/"
COLS = ["id", "decisao", "processo", "turma", "data", "assunto", "nul", "pre", "res", "ementa", "pdf", "trib", "vot", "tipo", "of", "rel", "sum"]
TESE = {None: 0, "ACOLHIDA": 1, "REJEITADA": 2, "INDEFINIDA": 3}


_SIGLA = re.compile(r"^\(?[A-ZÀ-Ú/]{2,6}\)?$")


def _conserta(a: str) -> str:
    """Desfaz máscaras indevidas do NER no cabeçalho (poucas dezenas de ementas)."""
    a = re.sub(r"(pessoa f[íi]sica\s*[-(]\s*)\[NOME\]", r"\1IRPF", a, flags=re.IGNORECASE)
    a = re.sub(r"(retido na fonte\s*[-(]\s*)\[NOME\]", r"\1IRRF", a, flags=re.IGNORECASE)
    return a.replace("[NOME]", "Pessoa")


def _chave_assunto(a: str) -> str:
    sem = unicodedata.normalize("NFKD", _conserta(a))
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in sem if not unicodedata.combining(c)).lower()).strip()


def assunto_limpo(a: str) -> str:
    """Caixa de frase para o que vem em CAIXA ALTA (mantém siglas entre parênteses ou no fim)."""
    a = " ".join(_conserta(a).split())
    if not a.isupper():
        return a
    ps = a.split()
    ps = [p if _SIGLA.match(p) and ("(" in p or i == len(ps) - 1) else p.lower() for i, p in enumerate(ps)]
    t = " ".join(ps)
    return t[:1].upper() + t[1:]


def canonicos(assuntos) -> dict[str, str]:
    """'(IRPF)', '- IRPF' e a versão em caixa alta contam como a mesma matéria; vale a forma mais comum."""
    cont: dict[str, Counter] = {}
    for a in assuntos:
        if a:
            cont.setdefault(_chave_assunto(a), Counter())[assunto_limpo(a)] += 1
    return {k: max(c.items(), key=lambda kv: (kv[1], not kv[0].isupper()))[0] for k, c in cont.items()}


def resumo_ementa(e: str | None, n=230) -> str:
    """Tira o cabeçalho 'Assunto: ... Ano-calendário: ...' (já vai em coluna própria) e corta."""
    e = " ".join((e or "").split())
    e = re.sub(r"^assunto:\s*.*?(?:per[íi]odo de apura[çc][ãa]o|ano-calend[áa]rio|exerc[íi]cio|data do fato gerador)"
               r"\s*:\s*[\d/,\s]*(?:a\s*[\d/]+)?\s*", "", e, flags=re.IGNORECASE)
    return e[:n] + ("…" if len(e) > n else "")


def canon_nomes(valores) -> dict[str, str]:
    """Mesmo relator com caixa/acento diferentes ('ANA CECILIA', 'Ana Cecília') vira um nome só (forma mais comum, em caixa de nome)."""
    cont: dict[str, Counter] = {}
    for v in valores:
        if v:
            cont.setdefault(_chave_assunto(v), Counter())[" ".join(v.split())] += 1
    out = {}
    for k, c in cont.items():
        mistas = [(n, f) for f, n in c.items() if not f.isupper()]
        forma = max(mistas)[1] if mistas else re.sub(r" (De|Da|Do|Das|Dos|E)\b", lambda m: m.group(0).lower(), max((n, f) for f, n in c.items())[1].title())
        out[k] = forma
    return out


def resumo_decisao(d: str | None, n=230) -> str:
    """Sem ementa (em geral resoluções de conversão em diligência): mostra o que a decisão determinou."""
    d = " ".join((d or "").split())
    d = re.sub(r"^vistos, relatados e discutidos os presentes autos\.?\s*", "", d, flags=re.IGNORECASE)
    d = re.split(r"\(?documento assinado|assinado digitalmente", d, flags=re.IGNORECASE)[0].strip()
    return "(sem ementa) " + (d[:n] + ("…" if len(d) > n else ""))


def exportar_anos(con, saida: Path, anos_min: int, anos_max: int = 9999, filtro_sql: str = "", params=()) -> dict:
    d = saida / "dados"
    d.mkdir(parents=True, exist_ok=True)
    turmas, assuntos, tributos, votos, tipos, relatores = {}, {}, {}, {}, {}, {}
    por_ano = {}
    resumo = {"ano": {}, "assuntos": Counter(), "res": Counter(), "turmas": Counter(), "nul": Counter(), "pre": Counter()}
    q = con.execute("""SELECT id, numero_decisao, numero_processo, turma, dt_sessao, ano, assunto, tese_nulidade,
                       tese_prescricao, decisao, ementa, nome_arquivo_pdf, tributo, desfecho_oficial, votacao, tipo_recurso, relator, sumulas FROM acordaos
                       WHERE ano BETWEEN ? AND ?""" + filtro_sql + " ORDER BY dt_sessao DESC, id", [anos_min, anos_max, *params])
    linhas = q.fetchall()
    canon = canonicos(l[6] for l in linhas)
    canon_rel = canon_nomes(l[16] for l in linhas)
    for (id_, dec, proc, turma, dt, ano, assunto, nul, pre, decisao, ementa, pdf, trib, des_of, vot, tipo, relator, sumulas) in linhas:
        ti = turmas.setdefault(turma or "", len(turmas))
        ai = assuntos.setdefault(canon.get(_chave_assunto(assunto), "") if assunto else "", len(assuntos))
        res = des_of or consulta.classificar_resultado(decisao)  # oficial quando existe
        tributos.setdefault(trib or "", len(tributos)); votos.setdefault(vot or "", len(votos)); tipos.setdefault(tipo or "", len(tipos))
        r_ano = resumo["ano"].setdefault(str(ano), {"n": 0, "res": Counter(), "nul": Counter()})
        r_ano["n"] += 1
        r_ano["res"][res] += 1
        r_ano["nul"][nul or "NENHUMA"] += 1
        resumo["res"][res] += 1
        resumo["nul"][nul or "NENHUMA"] += 1
        resumo["pre"][pre or "NENHUMA"] += 1
        resumo["turmas"][turma or ""] += 1
        if assunto:
            resumo["assuntos"][canon.get(_chave_assunto(assunto), "")] += 1
        por_ano.setdefault(ano, []).append([
            id_, dec, proc, ti, dt.isoformat() if dt else None, ai, TESE[nul], TESE[pre],
            res, resumo_ementa(ementa) if (ementa or "").strip() else resumo_decisao(decisao), pdf,
            tributos[trib or ""], votos[vot or ""], tipos[tipo or ""], int(bool(des_of)),
            relatores.setdefault(canon_rel.get(_chave_assunto(relator), "") if relator else "", len(relatores)), sumulas or ""])
    for ano, rows in por_ano.items():
        (d / f"ano-{ano}.json").write_text(json.dumps({"cols": COLS, "rows": rows}, ensure_ascii=False, separators=(",", ":")))
    meta = {"anos": sorted(por_ano), "n": {str(a): len(r) for a, r in por_ano.items()},
            "turmas": list(turmas), "assuntos": list(assuntos), "tributos": list(tributos), "votacoes": list(votos),
            "tipos": list(tipos), "relatores": list(relatores), "link": LINK,
            "teses": ["", "acolhida", "rejeitada", "indefinida"], "gerado": date.today().strftime("%d/%m/%Y"),
            "resumo": {"ano": {a: {"n": v["n"], "res": dict(v["res"]), "nul": dict(v["nul"])} for a, v in resumo["ano"].items()},
                       "assuntos": resumo["assuntos"].most_common(14), "res": dict(resumo["res"]),
                       "turmas": [t for t in resumo["turmas"].most_common(12) if t[0]], "nul": dict(resumo["nul"]),
                       "pre": dict(resumo["pre"])}}
    (saida / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
    return meta


def exportar_estoque_processos(raiz: Path, saida: Path):
    """Situação de cada processo no estoque do mês mais recente, codificada por dicionário (consulta por número)."""
    g = qg.conectar(raiz)
    if not g.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'estoque'").fetchone()[0]:
        return 0  # sem dado oficial de estoque (ex.: base de teste)
    ano, mes = g.execute("SELECT ano_referencia, mes_referencia FROM estoque ORDER BY 1 DESC, 2 DESC LIMIT 1").fetchone()
    rows = g.execute("""SELECT DISTINCT ON (numero_processo) numero_processo, fase_processual, data_entrada_carf, tributo, instancia,
                        tipo_contribuinte FROM estoque WHERE ano_referencia=? AND mes_referencia=?""", [ano, mes]).fetchall()
    dic = {k: {} for k in ("f", "t", "i", "c")}
    cod = lambda k, v: dic[k].setdefault(v if isinstance(v, str) else "", len(dic[k]))
    d = {re.sub(r"\D", "", n or ""): [cod("f", f), e.isoformat() if e else None, cod("t", t), cod("i", i), cod("c", c)]
         for n, f, e, t, i, c in rows}
    out = {"ref": f"{mes:02d}/{ano}", **{k: list(v) for k, v in dic.items()}, "d": d}
    (saida / "estoque_proc.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return len(d)


def exportar_oficial(raiz: Path, saida: Path):
    g = qg.conectar(raiz)
    df = g.execute("""SELECT ano, tributo, desfecho, count(*) n FROM julgamentos WHERE tipo_resultado='Acórdão'
                      AND desfecho IS NOT NULL AND ano >= 2012 GROUP BY 1,2,3""").df()
    tend = [[int(a), t if isinstance(t, str) else "", d, int(n)] for a, t, d, n in df.itertuples(index=False)]
    ano, mes = g.execute("SELECT ano_referencia, mes_referencia FROM estoque ORDER BY 1 DESC, 2 DESC LIMIT 1").fetchone()
    e = g.execute("""SELECT fase_processual, tributo, count(DISTINCT numero_processo) n FROM estoque
                     WHERE ano_referencia=? AND mes_referencia=? GROUP BY 1,2""", [ano, mes]).df()
    est = {"ref": f"{mes:02d}/{ano}",
           "linhas": [[f if isinstance(f, str) else "", t if isinstance(t, str) else "", int(n)] for f, t, n in e.itertuples(index=False)]}
    (saida / "oficial.json").write_text(json.dumps({"tendencia": tend, "estoque": est}, ensure_ascii=False, separators=(",", ":")))


def exportar_revisao(md: Path, saida: Path, csv_marcado: Path | None = None):
    import csv

    marcas = {}
    if csv_marcado:
        for r in csv.DictReader(Path(csv_marcado).open(encoding="utf-8", newline="")):
            marcas[r["id"]] = {"nome": int(r["qtd_nomes_remanescentes"] or 0), "ident": int(r["qtd_identificadores_remanescentes"] or 0),
                               "indevida": int(r["qtd_mascaras_indevidas"] or 0), "obs": r["observacoes"]}
    itens = []
    for bloco in re.split(r"\n## ", md.read_text())[1:]:
        cab, _, corpo = bloco.partition("\n")
        id_, _, cit = cab.partition(": ")
        ctx = re.findall(r"^- (.*)$", corpo.split("**Trecho")[0], flags=re.MULTILINE)
        trecho = "\n".join(re.findall(r"^> (.*)$", corpo, flags=re.MULTILINE))
        pal = re.search(r"palavras: (\d+) \| máscaras: (\d+)", corpo)
        itens.append({"id": id_, "cit": re.sub(r"\s*\[id .*$", "", cit), "palavras": int(pal.group(1)) if pal else 0,
                      "mascaras": int(pal.group(2)) if pal else 0, "ctx": [c for c in ctx if "nenhuma" not in c], "trecho": trecho,
                      "ia": marcas.get(id_)})
    (saida / "revisao.json").write_text(json.dumps(itens, ensure_ascii=False, separators=(",", ":")))
    return len(itens)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("saida")
    ap.add_argument("--ano-min", type=int, default=2018)
    ap.add_argument("--revisao")
    ap.add_argument("--revisao-csv", help="CSV já marcado (revisão por IA ou humana) para pré-preencher a aba")
    a = ap.parse_args()
    raiz, saida = Path(a.data_dir), Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    meta = exportar_anos(Store(raiz).connect(), saida, a.ano_min)
    exportar_oficial(raiz, saida)
    exportar_estoque_processos(raiz, saida)
    if a.revisao:
        exportar_revisao(Path(a.revisao), saida, a.revisao_csv)
    print(f"ok: {sum(meta['n'].values())} acórdãos em {len(meta['anos'])} anos")


if __name__ == "__main__":
    main()
