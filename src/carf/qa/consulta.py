"""Busca e estatísticas sobre a base anonimizada. Toda saída traz dados para citação."""

import re
import unicodedata

import pandas as pd

from .. import config

FILTROS = {"ano": "ano = ?", "turma": "turma = ?", "camara": "camara = ?", "secao": "secao = ?",
           "relator": "relator = ?", "numero_processo": "numero_processo = ?",
           "assunto": "assunto_norm LIKE ?",  # contém, sem acento/caixa
           "tese_nulidade": "tese_nulidade = ?", "tese_prescricao": "tese_prescricao = ?",
           "tributo": "tributo = ?", "desfecho_oficial": "desfecho_oficial = ?", "votacao": "votacao = ?", "tipo_recurso": "tipo_recurso = ?"}
DIMENSOES = {"ano", "turma", "camara", "secao", "relator"}

# Mesma taxonomia do dado aberto oficial (gerenciais.desfecho). O mérito prevalece sobre o
# conhecimento: "conhece parcialmente... e, na parte conhecida, nega provimento" é NEGADO.
PARCIAL = re.compile(
    r"provimento\s+(?:parcial|em\s+parte)|parcial\s+provimento|acolh\w*\s+parcialmente|"
    r"acolh\w*\s+em\s+parte|parcialmente\s+(?:os\s+)?embargos"
)
MERITO = [
    ("NEGADO", re.compile(r"neg(?:ar|ado|ou|aram|ando|am)(?:-lhes?)?\s+provimento")),
    ("PROVIDO", re.compile(r"(?:dar|dado|deram|dou|dando|dao)(?:-lhes?|-se)?\s+provimento")),
    ("ACOLHIDO", re.compile(r"acolh(?:er|ido|idos|eu|eram|endo|e)\s+(?:os\s+)?embargos")),
    ("REJEITADO", re.compile(r"rejeit(?:ar|ou|ado|ados|aram|ando)\s+(?:os\s+)?embargos")),
]
NAO_CONHECIDO = re.compile(r"n[aã]o\s+(?:conhec|tomar\s+conhecimento)")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


_CITADO = re.compile(r"[“\"][^”\"]*[”\"]")  # decisão anterior citada entre aspas
# Voto vencido não é o resultado: remove "vencidos ... que votaram por ..." até o ponto; quando a
# cláusula não tem "que", remove só até a primeira pontuação (não apaga o "no mérito, ...").
_VENCIDO_QUE = re.compile(r"vencid[oa]s?\b[^.]*?\bque\b[^.]*\.?")
_VENCIDO = re.compile(r"vencid[oa]s?\b[^,;.]*")
_OFICIO = re.compile(r"recurso\s+de\s+of[ií]cio")
_VOLUNTARIO = re.compile(r"recurso\s+volunt[aá]rio")
_EMBARGOS = {"ACOLHIDO", "REJEITADO"}


def classificar_resultado(decisao: str | None) -> str:
    """Heurística sobre o texto da decisão; o dado oficial (gerenciais) é preferível quando existe.

    Precedência: embargos > provimento parcial > demais resultados de mérito > não conhecido.
    """
    t = _norm(_CITADO.sub(" ", decisao or ""))
    t = _VENCIDO.sub(" ", _VENCIDO_QUE.sub(" ", t))
    parcial = bool(PARCIAL.search(t))
    t = PARCIAL.sub(" ", t)  # "dar provimento parcial" não conta também como "dar provimento"
    achados = {nome for nome, rx in MERITO if rx.search(t)}
    if achados & _EMBARGOS:
        achados &= _EMBARGOS
        if parcial:
            achados = {"PROVIDO_PARCIAL"}
    elif parcial:
        # dois recursos distintos na mesma decisão (ofício e voluntário) podem ter desfechos diferentes
        dois = _OFICIO.search(t) and _VOLUNTARIO.search(t)
        achados = achados | {"PROVIDO_PARCIAL"} if dois else {"PROVIDO_PARCIAL"}
    if len(achados) > 1:
        return "MISTO"
    if achados:
        return achados.pop()
    return "NAO_CONHECIDO" if NAO_CONHECIDO.search(t) else "OUTRO"


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
        params.append(f"%{_norm(v)}%" if k == "assunto" else v)
    return (" AND ".join(cond) or "true"), params


STOPWORDS = {
    "para", "como", "com", "por", "dos", "das", "nos", "nas", "uma", "que", "sem", "sobre",
    "entre", "pelo", "pela", "aos", "ser", "foi", "são", "mais", "quando", "qual", "quais",
    "isso", "esse", "essa", "este", "esta", "não", "nao", "seu", "sua", "ainda", "pode",
}


def buscar(con, termos: str, filtros=None, limite=10, qualquer=False) -> list[dict]:
    """Léxica. Por padrão todos os termos precisam aparecer; com `qualquer=True` basta um, e o
    ranking premia quem casa mais termos. Sem acento/caixa; a ementa pesa mais que o corpo."""
    palavras = [p for p in re.findall(r"\w+", _norm(termos)) if len(p) > 2 and p not in STOPWORDS]
    if not palavras:
        raise ValueError("informe ao menos um termo com 3+ letras")
    where, params = _where(filtros)
    texto = "strip_accents(lower(coalesce(ementa,'') || ' ' || coalesce(conteudo,'')))"
    ementa = "strip_accents(lower(coalesce(ementa,'')))"
    conds = ("(" + " OR ".join(f"{texto} LIKE ?" for _ in palavras) + ")") if qualquer else \
        " AND ".join(f"{texto} LIKE ?" for _ in palavras)
    score = " + ".join(
        f"(length({ementa}) - length(replace({ementa}, ?, ''))) * 5 / {len(p)}"
        f" + (length({texto}) - length(replace({texto}, ?, ''))) / {len(p)}"
        f" + CASE WHEN {texto} LIKE ? THEN 20 ELSE 0 END"
        for p in palavras
    )
    sql = f"""SELECT id, numero_decisao, numero_processo, turma, camara, secao, relator, dt_sessao,
                     ano, ementa, nome_arquivo_pdf, ({score}) AS score
              FROM acordaos WHERE {where} AND {conds}
              ORDER BY score DESC, dt_sessao DESC NULLS LAST LIMIT ?"""
    # ordem dos parâmetros no SQL: score, filtros, LIKE, limite
    args = ([x for p in palavras for x in (p, p, f"%{p}%")] + params
            + [f"%{p}%" for p in palavras] + [limite])
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
