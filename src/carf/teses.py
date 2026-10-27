"""Matéria (assunto) e teses de uma ementa, com a tese tratada como acolhida ou rejeitada.

A ementa do CARF começa com "Assunto: X Período de apuração: ..." e segue com frases-título em caixa
alta ("NULIDADE. INOCORRÊNCIA.") e o texto. O classificador é heurístico (regras sobre a ementa e a
decisão), abstém-se quando os sinais se contradizem e deve ser conferido por quem usa.
"""

import re
import unicodedata

_CAB = re.compile(
    r"^\s*(?:assunto:\s*)?(.*?)\s+(?:per[íi]odo de apura[çc][ãa]o|ano-calend[áa]rio|exerc[íi]cio|"
    r"data do fato gerador)\b",
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


def _tem_cab(ementa: str | None) -> bool:
    m = _CAB.match(ementa or "")
    return bool(m) and len(m.group(1)) <= 160


def extrair_assunto(ementa: str | None) -> str | None:
    m = _CAB.match(ementa or "")
    if not m:
        return None
    a = re.sub(r"\s+", " ", m.group(1)).strip(" :-")
    return a if a and len(a) <= 160 else None  # cabeçalho sem data de referência pega a ementa inteira


def _corpo(ementa: str | None) -> str:
    c = _DATAS.sub("", ementa or "", count=1) if _tem_cab(ementa) else (ementa or "")
    return re.sub(r"\s+", " ", c).strip()


def extrair_teses(ementa: str | None) -> str | None:
    """Frases-título em caixa alta que seguem o cabeçalho (ex.: 'NULIDADE. INOCORRÊNCIA.')."""
    corpo = _DATAS.sub("", ementa or "", count=1) if _tem_cab(ementa) else (ementa or "")
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
            r"(?<!nao )(?<!nao se )(?<!somente )\be nul[oa]\b|declara-se nul|decretacao de nulidade|vicio insanavel|"
            r"nulidade[^.]{0,30}(?:acolhid|reconhecid|configurad)|nulidade\.? ocorrencia(?!.{0,5}\bnao)|"
            r"(?:cerceamento|preterição)[^.]{0,30}(?:configurad|caracterizad)"),
        "em_rejeita": re.compile(
            r"inocorr|nao evidenciad|nao (?:ha|houve|padece|enseja|procedem?)[^.]{0,40}(?:nulidade|cerceamento|nulo)|"
            r"improcedencia|nao configurad|nao se verific|afasta-se a nulidade|inexistencia de (?:nulidade|cerceamento)|"
            r"nulidade\.? (?:inexistencia|impossibilidade|nao ocorrencia)|ausencia de nulidade|nao e nulo|nao cabe o acolhimento|nao verificad|nulidade\.? rejeitad"),
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
_OUTRA_PRELIM = re.compile(r"(?:preliminar(?:es)?|arguica\w+) (?:de|da|do) (?:admissibilidade|decadencia|prescricao|ilegitimidade|conhecimento|tempestividade|concomitancia)")


def classificar_tese(tema: str, ementa: str | None, decisao: str | None = None) -> str | None:
    """None: a ementa não trata do tema. ACOLHIDA / REJEITADA / INDEFINIDA caso contrário.

    ACOLHIDA vale quando ao menos uma arguição foi acolhida (ex.: "rejeitar a nulidade do acórdão e
    acolher a nulidade da autuação"). Sem sinal claro, INDEFINIDA: o painel mostra o trecho para conferir.
    """
    t = TEMAS[tema]
    e, d = _norm(ementa), _norm(decisao)
    d = _VENCIDO.sub(" ", d)
    d = re.sub(r"\bnao (?:se )?(?:acolh|acat)\w+", "afastar", d)
    d = re.sub(r"\bsem (?:a )?(?:anulacao|declaracao de nulidade|decretacao)\b", "sem efeito", d)
    d = re.sub(r"acolh\w+ (?:os )?(?:dois )?embargos\w*", "embargos", d)
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
    # sem sinal na decisão, só vale a ementa se o tema está no título dela (as frases em caixa alta e o
    # começo do texto); menção solta no meio de outra matéria não faz do acórdão um caso desse tema
    titulo = _norm(_corpo(ementa))[:260]
    if not t["mencao"].search(titulo):
        return None if not t["mencao"].search(d) else "INDEFINIDA"
    ea, er = bool(t["em_acolhe"].search(e[:900])), bool(t["em_rejeita"].search(e[:900]))
    if ea and not er:
        # contribuinte perdeu (nega provimento ao voluntário) e o texto só enuncia a regra: não dá para afirmar
        if re.search(r"neg\w+ provimento ao recurso( voluntario)?\b", d) and "oficio" not in d:
            return "INDEFINIDA"
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


def _oficial(store) -> dict:
    """numero_decisao -> dados do dado aberto oficial (tributo, resultado, votação, tipo de recurso)."""
    from pathlib import Path

    from .qa import gerenciais as qg

    raiz = Path(store.root)
    if not (raiz / "gerenciais" / "julgamentos").exists():
        return {}
    g = qg.conectar(raiz)
    rows = g.execute("""SELECT numero_decisao, numero_processo, tributo, desfecho, votacao, tipo_recurso FROM julgamentos
                        WHERE numero_decisao IS NOT NULL AND tipo_resultado = 'Acórdão'""").fetchall()
    por: dict[str, dict] = {}
    for dec, proc, trib, des, vot, tipo in rows:
        d = por.setdefault(dec, {})
        d[re.sub(r"\D", "", proc or "")] = (trib, des, vot, tipo)
        d.setdefault("", (trib, des, vot, tipo))  # reserva: primeira linha da decisão
    return por


def construir_facets(store, log=print) -> int:
    """Calcula assunto/teses e junta o dado oficial (por número da decisão); grava `facets.parquet`.

    Arquivo à parte (e não colunas nas partições): dá para recalcular quando a regra melhora sem
    reescrever a base, e o DuckDB junta pelo id na view `acordaos`.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    con = store.connect()
    linhas = con.execute("SELECT id, ementa, decisao, numero_decisao, numero_processo FROM acordaos_base").fetchall()
    oficial = _oficial(store)
    chaves = ("id", "assunto", "assunto_norm", "teses", "tese_nulidade", "tese_prescricao",
              "tributo", "desfecho_oficial", "votacao", "tipo_recurso")
    cols = {k: [] for k in chaves}
    casou = 0
    for id_, ementa, decisao, dec, proc in linhas:
        f = enriquecer(ementa, decisao)
        o = oficial.get(dec or "", {})
        reg = o.get(re.sub(r"\D", "", proc or "")) or o.get("") or (None, None, None, None)
        casou += bool(o)
        cols["id"].append(id_)
        cols["assunto"].append(f["assunto"])
        cols["assunto_norm"].append(_norm(f["assunto"]) if f["assunto"] else None)
        cols["teses"].append(f["teses"])
        cols["tese_nulidade"].append(f["tese_nulidade"])
        cols["tese_prescricao"].append(f["tese_prescricao"])
        for k, v in zip(("tributo", "desfecho_oficial", "votacao", "tipo_recurso"), reg, strict=True):
            cols[k].append(v)
    tmp = store.facets_path.with_suffix(".tmp")
    pq.write_table(pa.table(cols), tmp, compression="zstd")
    tmp.replace(store.facets_path)
    log(f"{len(linhas)} acórdãos enriquecidos; {casou} com dado oficial")
    return len(linhas)
