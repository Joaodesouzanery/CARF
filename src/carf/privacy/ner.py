"""Camada 2: nomes de pessoas físicas (NER em português) com allowlist de agentes públicos."""

import re
import unicodedata

from .rules import Span

PARTICULAS = {"da", "de", "do", "das", "dos", "e"}
HONORIFICOS = {"sr", "sra", "dr", "dra", "conselheiro", "conselheira", "relator", "relatora"}
CHUNK = 50_000

# Títulos e marcadores de página nas bordas de uma entidade: ficam no texto, fora da máscara.
BORDA = HONORIFICOS | {
    "desembargador", "desembargadora", "juiz", "juiza", "doutor", "doutora", "professor",
    "professora", "senhor", "senhora", "procurador", "procuradora", "ministro", "ministra",
    "presidente", "rel", "fl", "fls", "r", "c", "autor", "autora", "advogado", "advogada",
}
# Vocabulário jurídico-tributário: se aparece dentro de uma entidade, ela não é nome de pessoa.
JURIDICO = {
    "inciso", "incisos", "alinea", "artigo", "art", "arts", "paragrafo", "lei", "decreto",
    "portaria", "instrucao", "normativa", "codigo", "constituicao", "despacho", "decisorio",
    "saneamento", "decurso", "integral", "onus", "prova", "provas", "turma", "camara", "secao",
    "julgadora", "julgadoras", "recurso", "recursos", "provimento", "negar", "dar", "conhecer",
    "conheco", "voto", "relatoria", "acordao", "acordaos", "resolucao", "sumula", "sumulas",
    "previdenciarias", "previdenciario", "previdenciaria", "periodo", "exercicio", "contribuinte",
    "contribuintes", "contribuicao", "contribuicoes", "imposto", "tributo", "receita", "federal",
    "nacional", "fazenda", "ministerio", "conselho", "administrativo", "fiscais", "fiscal",
    "procuradoria", "republica", "tribunal", "justica", "superior", "supremo", "estado",
    "municipio", "uniao", "banco", "sociedade", "empresa", "ltda", "impugnante", "reu", "condeno",
    "csrf", "carf", "rfb", "irpj", "csll", "cofins", "pis", "pasep", "nfld", "debcad", "gfip",
    "gfips", "dicat", "ricarf", "cpc", "ctn", "cf", "auto", "infracao", "lancamento", "debito",
    "credito", "processo", "processual", "tributaria", "tributario", "sentenca", "ementa",
    "decisao", "diligencia", "preliminar", "merito", "recorrente", "recorrida", "recorrido",
    "autuacao", "notificacao", "intimacao", "pedido", "capitulo", "titulo", "secretaria",
}
# Quem vem precedido de um destes títulos atua em função pública: não se mascara.
OFICIAIS = {
    "ministro", "ministra", "min", "conselheiro", "conselheira", "desembargador",
    "desembargadora", "juiz", "juiza", "relator", "relatora",
}
# Sufixos de nome que não devem ser propagados como se fossem sobrenome.
SUFIXOS = {"filho", "neto", "junior", "sobrinho", "segundo", "primeiro"}

_TOKEN = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*")


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def normalizar_nome(s: str) -> list[str]:
    toks = re.findall(r"[a-z]+", _sem_acento(s))
    return [t for t in toks if t not in PARTICULAS and t not in HONORIFICOS]


def palavras_minusculas(text: str) -> set[str]:
    """Palavras que aparecem em minúscula no documento: vocabulário comum, não nome próprio."""
    return set(re.findall(r"(?<![\w])[a-zà-ÿ]{3,}(?![\w])", text))


def refinar(text: str, sp: Span, comuns: set[str] | None = None) -> Span | None:
    """Apara títulos/marcadores das bordas e descarta o que não parece nome de pessoa.

    Devolve rótulo "OFICIAL" quando o nome vem após título judicial (ministro, conselheiro...).
    """
    toks = [(sp.start + m.start(), sp.start + m.end(), _sem_acento(m.group()), m.group())
            for m in _TOKEN.finditer(text[sp.start : sp.end])]
    oficial = False
    while toks and (toks[0][2] in BORDA or toks[0][2] in PARTICULAS):
        oficial |= toks[0][2] in OFICIAIS
        toks.pop(0)
    while toks and (toks[-1][2] in BORDA or toks[-1][2] in PARTICULAS):
        toks.pop()
    if len(toks) < 2 or any(t[2] in JURIDICO for t in toks):
        return None
    if comuns is not None:
        nomes = [t[3].lower() for t in toks if t[2] not in PARTICULAS]
        if all(n in comuns for n in nomes):
            return None
    return Span(toks[0][0], toks[-1][1], "OFICIAL" if oficial else "NOME")


def propagar(
    text: str, mascarados: list[Span], bloqueados: list[Span], comuns: set[str] | None = None
) -> list[Span]:
    """Mascara sobrenomes/prenomes soltos de quem já foi mascarado por inteiro no documento.

    Uma pessoa costuma aparecer por extenso uma vez e depois só por "Silva" ou "Maria". Posições
    dentro de nomes permitidos (agentes públicos) ficam de fora.
    """
    palavras = set()
    for sp in mascarados:
        for m in _TOKEN.finditer(text[sp.start : sp.end]):
            w, n = m.group(), _sem_acento(m.group())
            if (len(w) >= 4 and n not in PARTICULAS | BORDA | JURIDICO | SUFIXOS and w[0].isupper()
                    and w.lower() not in (comuns or ())):
                palavras.add(w)
    if not palavras:
        return []
    alternativas = "|".join(map(re.escape, sorted(palavras)))
    rx = re.compile(rf"(?<![\w])(?:{alternativas})(?![\w])")
    return [
        Span(m.start(), m.end(), "NOME")
        for m in rx.finditer(text)
        if not any(m.start() < b.end and b.start < m.end() for b in bloqueados)
    ]


class Allowlist:
    """Nomes de agentes públicos (relatores) que não devem ser mascarados."""

    def __init__(self, nomes=()):
        self._indice: dict[str, list[frozenset[str]]] = {}
        self.adicionar(nomes)

    def adicionar(self, nomes):
        for nome in nomes:
            toks = frozenset(normalizar_nome(nome))
            if len(toks) < 2:
                continue
            for t in toks:
                self._indice.setdefault(t, []).append(toks)

    def permite(self, texto: str) -> bool:
        toks = set(normalizar_nome(texto))
        if len(toks) < 2:
            return False
        candidatos = self._indice.get(next(iter(toks)), [])
        return any(toks <= nome for nome in candidatos)


def _chunks(text: str):
    pos = 0
    while pos < len(text):
        fim = min(pos + CHUNK, len(text))
        if fim < len(text):
            corte = text.rfind("\n", pos, fim)
            if corte > pos:
                fim = corte + 1
        yield pos, text[pos:fim]
        pos = fim


class SpacyNomes:
    """NER + nomes após termos de contexto, ambos filtrados por `refinar`."""

    def __init__(self, modelo="pt_core_news_lg"):
        import spacy

        self.nlp = spacy.load(
            modelo, disable=["parser", "lemmatizer", "attribute_ruler", "morphologizer"]
        )

    def detectar(self, text: str) -> list[Span]:
        spans = []
        partes = list(_chunks(text))
        docs = self.nlp.pipe((p for _, p in partes), batch_size=8)
        for (offset, _), doc in zip(partes, docs):
            for ent in doc.ents:
                if ent.label_ == "PER":
                    spans.append(Span(offset + ent.start_char, offset + ent.end_char, "NOME"))
        spans += NomesPorContexto().detectar(text)
        comuns = palavras_minusculas(text)
        refinados = (refinar(text, sp, comuns) for sp in spans)
        return sorted({sp for sp in refinados if sp}, key=lambda x: x.start)


class NomesPorContexto:
    """Reserva degradada, sem modelo: só nomes que seguem um termo de contexto.

    Recall muito inferior ao NER; exige confirmação explícita para uso.
    """

    _RX = re.compile(
        r"(?i:contribuinte|recorrente|requerente|interessad[oa]|s[óo]cio|"
        r"respons[áa]vel solid[áa]rio|Sr\.|Sra\.|senhor|senhora)\s*:?\s*"
        r"((?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]+(?:\s+(?:d[aeo]s?|e))?\s+){1,4}"
        r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]+)"
    )

    def detectar(self, text: str) -> list[Span]:
        return [Span(*m.span(1), "NOME") for m in self._RX.finditer(text)]
