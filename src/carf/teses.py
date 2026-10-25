"""Matéria (assunto) e teses de uma ementa, com a tese tratada como acolhida ou rejeitada.

A ementa do CARF começa com "Assunto: X Período de apuração: ..." e segue com frases-título em caixa
alta ("NULIDADE. INOCORRÊNCIA.") e o texto. O classificador é heurístico (regras sobre a ementa e a
decisão), abstém-se quando os sinais se contradizem e deve ser conferido por quem usa.
"""

import re
import unicodedata

_CAB = re.compile(
    r"^\s*assunto:\s*(.*?)\s+(?:per[íi]odo de apura[çc][ãa]o|ano-calend[áa]rio|exerc[íi]cio|"
    r"data do fato gerador|data)\b",
    re.IGNORECASE | re.DOTALL,
)
_DATAS = re.compile(
    r"^.*?(?:per[íi]odo de apura[çc][ãa]o|ano-calend[áa]rio|exerc[íi]cio|data do fato gerador)\s*:\s*"
    r"(?:\d[\d/,\s]*(?:a\s*\d[\d/,\s]*)?)*",
    re.IGNORECASE | re.DOTALL,
)
_TITULOS = re.compile(r"((?:[A-ZÀ-Ú0-9][A-ZÀ-Ú0-9/\-\.,;:\sº°ª()]{3,}?\.\s*){1,6})(?=[A-ZÀ-Ú]?[a-zà-ú])")


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).lower().strip()


def extrair_assunto(ementa: str | None) -> str | None:
    m = _CAB.match(ementa or "")
    if not m:
        return None
    a = re.sub(r"\s+", " ", m.group(1)).strip(" :-")
    return a or None


def extrair_teses(ementa: str | None) -> str | None:
    """Frases-título em caixa alta que seguem o cabeçalho (ex.: 'NULIDADE. INOCORRÊNCIA.')."""
    corpo = _DATAS.sub("", ementa or "", count=1) if re.match(r"\s*assunto", ementa or "", re.IGNORECASE) else (ementa or "")
    corpo = re.sub(r"\s+", " ", corpo).strip()
    m = _TITULOS.match(corpo)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


# A DECISÃO diz o que aconteceu com a preliminar; a ementa só serve de reserva. Texto sem acento/minúsculo.
_ARG = r"(?:preliminar(?:es)?|nulidade|arguicao|arguicoes)"
TEMAS = {
    "nulidade": {
        "mencao": re.compile(r"nulidade|\bnul[oa]s?\b|cerceamento|anul"),
        "dec_acolhe": re.compile(
            rf"(?:acolh\w+|acat\w+)[^.;]{{0,60}}{_ARG}|(?:decret\w+|declar\w+|reconhec\w+)[^.;]{{0,40}}nulidade|"
            r"declar\w+ (?:a )?nul[oa]|nulidade (?:do|da) \w+ (?:acolhid|reconhecid)"),
        "dec_anula": re.compile(r"\banular\b|\banul(?:ou|ando|ado|ada|acao)\b|para anular|tornar nul[oa]"),
        "dec_rejeita": re.compile(
            rf"(?:rejeit\w+|afast\w+|nao acolh\w+|negar provimento a|improced\w+)[^.;]{{0,60}}{_ARG}"),
        "em_acolhe": re.compile(
            r"(?<!nao )(?<!nao se )\be nul[oa]\b|declara-se nul|decretacao de nulidade|vicio insanavel|"
            r"nulidade[^.]{0,30}(?:acolhid|reconhecid|configurad)|nulidade\.? ocorrencia(?!.{0,5}\bnao)|"
            r"(?:cerceamento|preterição)[^.]{0,30}(?:configurad|caracterizad)"),
        "em_rejeita": re.compile(
            r"inocorr|nao evidenciad|nao (?:ha|houve|padece|enseja|procedem?)[^.]{0,40}(?:nulidade|cerceamento|nulo)|"
            r"improcedencia|nao configurad|nao se verific|afasta-se a nulidade|inexistencia de (?:nulidade|cerceamento)|"
            r"nulidade\.? (?:inexistencia|impossibilidade|nao ocorrencia)|ausencia de nulidade|nao e nulo|nao cabe o acolhimento"),
    },
    "prescricao": {
        "mencao": re.compile(r"prescri[cç]ao"),
        "dec_acolhe": re.compile(r"(?:reconhec\w+|acolh\w+)[^.;]{0,40}prescri"),
        "dec_rejeita": re.compile(r"(?:rejeit\w+|afast\w+|negar provimento a)[^.;]{0,60}prescri"),
        "em_acolhe": re.compile(r"prescricao (?:reconhecid|configurad|ocorrid)"),
        "em_rejeita": re.compile(r"inaplic|nao se aplica|inocorr|nao ocorrid|sumula carf n\w* ?11|inexiste prescricao|afastad"),
    },
}


# Voto vencido não é o resultado ("vencido o relator, que acolhia..."); sai antes de ler a decisão.
_VENCIDO = re.compile(r"venc[ei]d\w*.*?(?:\.\s|$)|designad\w+ para redigir.*?(?:\.\s|$)|"
    r"que (?:votou|votaram|dava|davam|acolhia|acatava|negava)\b.*?(?:\.\s|$)", re.DOTALL)
# "acolher a preliminar de admissibilidade/decadência..." não é preliminar de nulidade.
_OUTRA_PRELIM = re.compile(r"preliminar(?:es)? (?:de|da|do) (?:admissibilidade|decadencia|prescricao|ilegitimidade|conhecimento|tempestividade|concomitancia)")


def classificar_tese(tema: str, ementa: str | None, decisao: str | None = None) -> str | None:
    """None: a ementa não trata do tema. ACOLHIDA / REJEITADA / INDEFINIDA caso contrário.

    ACOLHIDA vale quando ao menos uma arguição foi acolhida (ex.: "rejeitar a nulidade do acórdão e
    acolher a nulidade da autuação"). Sem sinal claro, INDEFINIDA: o painel mostra o trecho para conferir.
    """
    t = TEMAS[tema]
    e, d = _norm(ementa), _norm(decisao)
    d = _VENCIDO.sub(" ", d)
    d = re.sub(r"\bnao (?:se )?(?:acolh|acat)\w+", "afastar", d)
    if tema == "nulidade":
        d = _OUTRA_PRELIM.sub("prelimoutra", d)
    if not t["mencao"].search(e) and not t["mencao"].search(d):
        return None
    if tema == "nulidade" and not re.search(r"nulidade|\bnul[oa]s?\b|cerceamento|anul|preliminar", e + " " + d):
        return None
    da, dr = bool(t["dec_acolhe"].search(d)), bool(t["dec_rejeita"].search(d))
    anula = bool(t["dec_anula"].search(d)) if "dec_anula" in t else False
    if da:
        return "ACOLHIDA"
    if dr:
        return "REJEITADA"
    if anula:
        return "ACOLHIDA"
    if "prelimoutra" in d:
        return "INDEFINIDA"
    if not t["mencao"].search(e[:900]):
        return "INDEFINIDA"
    ea, er = bool(t["em_acolhe"].search(e[:900])), bool(t["em_rejeita"].search(e[:900]))
    if ea and not er:
        return "ACOLHIDA"
    if er and not ea:
        return "REJEITADA"
    return "INDEFINIDA"


def enriquecer(ementa: str | None, decisao: str | None) -> dict:
    return {
        "assunto": extrair_assunto(ementa),
        "teses": extrair_teses(ementa),
        "tese_nulidade": classificar_tese("nulidade", ementa, decisao),
        "tese_prescricao": classificar_tese("prescricao", ementa, decisao),
    }


def construir_facets(store, log=print) -> int:
    """Calcula assunto/teses de todos os acórdãos e grava `facets.parquet` ao lado dos dados.

    Arquivo à parte (e não colunas nas partições): dá para recalcular quando a regra melhora sem
    reescrever a base, e o DuckDB junta pelo id na view `acordaos`.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    con = store.connect()
    linhas = con.execute("SELECT id, ementa, decisao FROM acordaos_base").fetchall()
    cols = {k: [] for k in ("id", "assunto", "assunto_norm", "teses", "tese_nulidade", "tese_prescricao")}
    for id_, ementa, decisao in linhas:
        f = enriquecer(ementa, decisao)
        cols["id"].append(id_)
        cols["assunto"].append(f["assunto"])
        cols["assunto_norm"].append(_norm(f["assunto"]) if f["assunto"] else None)
        cols["teses"].append(f["teses"])
        cols["tese_nulidade"].append(f["tese_nulidade"])
        cols["tese_prescricao"].append(f["tese_prescricao"])
    tmp = store.facets_path.with_suffix(".tmp")
    pq.write_table(pa.table(cols), tmp, compression="zstd")
    tmp.replace(store.facets_path)
    log(f"{len(linhas)} acórdãos enriquecidos")
    return len(linhas)
