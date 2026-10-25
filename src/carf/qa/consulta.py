"""Busca e estatísticas sobre a base anonimizada. Toda saída traz dados para citação."""

import re
import unicodedata

import pandas as pd

from .. import config

FILTROS = {"ano": "ano = ?", "turma": "turma = ?", "camara": "camara = ?", "secao": "secao = ?",
           "relator": "relator = ?", "numero_processo": "numero_processo = ?"}
DIMENSOES = {"ano", "turma", "camara", "secao", "relator"}

PARCIAL = re.compile(r"provimento\s+(?:parcial|em\s+parte)|parcial\s+provimento")
RESULTADOS = [
    ("NEGADO", re.compile(r"neg(?:ar|ado|ou|aram)(?:-lhe)?\s+provimento")),
    ("PROVIDO", re.compile(r"(?:dar|dado|deram|dou)(?:-lhe)?\s+provimento")),
    ("NAO_CONHECIDO", re.compile(r"n[aã]o\s+(?:conhec|tomar\s+conhecimento)")),
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def classificar_resultado(decisao: str | None) -> str:
    """Heurística sobre o texto da decisão. Indicativa; confira por amostragem."""
    t = _norm(decisao)
    achados = {"PROVIDO_PARCIAL"} if PARCIAL.search(t) else set()
    t = PARCIAL.sub(" ", t)  # "dar provimento parcial" não conta também como "dar provimento"
    achados |= {nome for nome, rx in RESULTADOS if rx.search(t)}
    if len(achados) == 1:
        return achados.pop()
    return "MISTO" if achados else "OUTRO"


def citacao(r: dict) -> str:
    data = r["dt_sessao"].strftime("%d/%m/%Y") if r.get("dt_sessao") else "s/d"
    return (f"Acórdão {r.get('numero_decisao') or 's/n'}, Processo {r.get('numero_processo') or 's/n'}, "
            f"{r.get('turma') or 's/turma'}, sessão {data}, Rel. {r.get('relator') or 's/relator'} "
            f"[id {r['id']}, arquivo {r.get('nome_arquivo_pdf') or 's/arquivo'}]")


def _where(filtros: dict | None) -> tuple[str, list]:
    cond, params = [], []
    for k, v in (filtros or {}).items():
        if k not in FILTROS:
            raise ValueError(f"filtro inválido: {k}")
        cond.append(FILTROS[k])
        params.append(v)
    return (" AND ".join(cond) or "true"), params


def buscar(con, termos: str, filtros=None, limite=10) -> list[dict]:
    """Todos os termos precisam aparecer (sem acento/caixa); ementa pesa mais que o corpo."""
    palavras = [p for p in re.findall(r"\w+", _norm(termos)) if len(p) > 2]
    if not palavras:
        raise ValueError("informe ao menos um termo com 3+ letras")
    where, params = _where(filtros)
    texto = "strip_accents(lower(coalesce(ementa,'') || ' ' || coalesce(conteudo,'')))"
    ementa = "strip_accents(lower(coalesce(ementa,'')))"
    conds = " AND ".join(f"{texto} LIKE ?" for _ in palavras)
    score = " + ".join(
        f"(length({ementa}) - length(replace({ementa}, ?, ''))) * 5 / {len(p)}"
        f" + (length({texto}) - length(replace({texto}, ?, ''))) / {len(p)}"
        for p in palavras
    )
    sql = f"""SELECT id, numero_decisao, numero_processo, turma, camara, secao, relator, dt_sessao,
                     ano, ementa, nome_arquivo_pdf, ({score}) AS score
              FROM acordaos WHERE {where} AND {conds}
              ORDER BY score DESC, dt_sessao DESC NULLS LAST LIMIT ?"""
    # ordem dos parâmetros no SQL: score, filtros, LIKE, limite
    args = [x for p in palavras for x in (p, p)] + params + [f"%{p}%" for p in palavras] + [limite]
    rows = con.execute(sql, args).fetchall()
    nomes = ["id", "numero_decisao", "numero_processo", "turma", "camara", "secao", "relator",
             "dt_sessao", "ano", "ementa", "nome_arquivo_pdf", "score"]
    out = []
    for row in rows:
        r = dict(zip(nomes, row))
        r["citacao"] = citacao(r)
        out.append(r)
    return out


def obter(con, id_: str) -> dict | None:
    cur = con.execute("SELECT * FROM acordaos WHERE id = ?", [str(id_)])
    row = cur.fetchone()
    if not row:
        return None
    r = dict(zip([c[0] for c in cur.description], row))
    r["citacao"] = citacao(r)
    return r


def contagem(con, por: str, filtros=None) -> pd.DataFrame:
    if por not in DIMENSOES:
        raise ValueError(f"dimensão inválida: {por}")
    where, params = _where(filtros)
    df = con.execute(
        f"SELECT {por} AS {por}, count(*) AS acordaos FROM acordaos WHERE {where} "
        f"GROUP BY 1 ORDER BY 2 DESC", params).df()
    return _protege_relator(df, por, "acordaos")


def taxa_resultado(con, por: str, filtros=None, termo: str | None = None) -> pd.DataFrame:
    """Distribuição de resultados por dimensão. Heurística; ver classificar_resultado."""
    if por not in DIMENSOES:
        raise ValueError(f"dimensão inválida: {por}")
    where, params = _where(filtros)
    df = con.execute(
        f"SELECT {por} AS {por}, decisao, ementa FROM acordaos WHERE {where} AND {por} IS NOT NULL",
        params).df()
    if termo:
        t = _norm(termo)
        df = df[df["ementa"].map(lambda e: t in _norm(e))]
    df["resultado"] = df["decisao"].map(classificar_resultado)
    tab = pd.crosstab(df[por], df["resultado"])
    tab["total"] = tab.sum(axis=1)
    tab = tab.reset_index().sort_values("total", ascending=False)
    return _protege_relator(tab, por, "total")


def _protege_relator(df: pd.DataFrame, por: str, col: str) -> pd.DataFrame:
    """Política LGPD: não expõe estatística por relator com amostra pequena."""
    if por == "relator":
        df = df[df[col] >= config.MIN_SAMPLE_PER_RELATOR]
    return df
