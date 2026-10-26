"""Camada 2: nomes de pessoas físicas (NER em português) com allowlist de agentes públicos."""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .rules import Span

PARTICULAS = {"da", "de", "do", "das", "dos", "e"}
HONORIFICOS = {"sr", "sra", "dr", "dra", "conselheiro", "conselheira", "relator", "relatora"}
CHUNK = 50_000

# Títulos e marcadores de página nas bordas de uma entidade: ficam no texto, fora da máscara.
BORDA = HONORIFICOS | {
    "desembargador", "desembargadora", "juiz", "juiza", "doutor", "doutora", "professor",
    "professora", "senhor", "senhora", "procurador", "procuradora", "ministro", "ministra",
    "presidente", "rel", "fl", "fls", "r", "c", "autor", "autora", "advogado", "advogada",
    "redator", "redatora", "suplente", "designado", "designada",
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
# Palavras gramaticais curtas que não contam ao decidir se uma entidade é só vocabulário comum.
GRAMATICAIS = {"na", "no", "nas", "nos", "que", "em", "por", "para", "com", "sem", "ao", "aos", "um",
               "uma", "se", "ou", "como", "pela", "pelo", "sob", "sobre", "ante", "apos"}
# Função pública depois do nome ("Fulano - Presidente Redator"): também não se mascara.
FUNCAO_POS = {"presidente", "relator", "relatora", "redator", "redatora", "suplente", "designado",
              "designada", "conselheiro", "conselheira"}
# Quem vem precedido de um destes títulos atua em função pública: não se mascara.
OFICIAIS = {
    "ministro", "ministra", "min", "conselheiro", "conselheira", "desembargador",
    "desembargadora", "juiz", "juiza", "relator", "relatora",
}
# Sufixos de nome que não devem ser propagados como se fossem sobrenome.
SUFIXOS = {"filho", "neto", "junior", "sobrinho", "segundo", "primeiro"}

_TOKEN = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*")


@lru_cache(maxsize=1)
def vocabulario_comum() -> frozenset[str]:
    """Palavras que aparecem em minúscula em muitos acórdãos (gerado por scripts/gerar_vocabulario.py)."""
    arq = Path(__file__).with_name("vocab_comum.txt")
    return frozenset(arq.read_text(encoding="utf-8").split()) if arq.exists() else frozenset()


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def normalizar_nome(s: str) -> list[str]:
    toks = re.findall(r"[a-z]+", _sem_acento(s))
    return [t for t in toks if t not in PARTICULAS and t not in HONORIFICOS]


def palavras_minusculas(text: str) -> set[str]:
    """Palavras que aparecem em minúscula no documento: vocabulário comum, não nome próprio."""
    return set(re.findall(r"(?<![\w])[a-zà-ÿ]{3,}(?![\w])", text))


_FUNCAO_APOS = re.compile(r"[\s,]*\(\s*(?:substitut|suplente|convocad|relator|president|redator)", re.IGNORECASE)


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
        oficial |= toks[-1][2] in FUNCAO_POS
        toks.pop()
    if len(toks) < 2 or any(t[2] in JURIDICO for t in toks):
        return None
    nomes = [t[3].lower() for t in toks if t[2] not in PARTICULAS and t[2] not in GRAMATICAIS]
    conhecidas = vocabulario_comum() | (comuns or frozenset())
    if all(n in conhecidas for n in nomes):  # só palavras comuns (ou só gramaticais)
        return None
    # função pública logo depois do nome, fora da entidade: "Fulano (substituto[a] integral)"
    oficial |= bool(_FUNCAO_APOS.match(text[toks[-1][1] : toks[-1][1] + 40]))
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
                    and w.lower() not in (comuns or ()) and w.lower() not in vocabulario_comum()):
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
    """Nomes que seguem um termo de contexto ("Sr.", "sócios", "responsável solidário"...).

    Pega o que o NER perde, sobretudo nomes em CAIXA ALTA e listas ligadas por "e" ou vírgula
    ("Srs. FULANO DE TAL e BELTRANO DE TAL"). Sozinha tem recall muito inferior ao NER.
    """

    _CAP = r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç'\-]+"
    _NOME = rf"{_CAP}(?:\s+(?:d[aeo]s?\s+)?{_CAP}){{1,5}}"
    _CUES = (
        r"contribuintes?|recorrentes?|requerentes?|interessad[oa]s?|s[óo]cios?|s[óo]cias?|"
        r"respons[áa]ve(?:l|is)\s+solid[áa]ri[oa]s?|autuad[oa]s?|advogad[oa]s?|"
        r"Srs?\.?|Sras?\.?|senhor(?:es|a|as)?|patronos?|representantes?\s+legais?|"
        r"administrador(?:es|a|as)?|diretor(?:es|a|as)?|herdeiros?|espólio\s+de"
    )
    _RX = re.compile(rf"(?i:{_CUES})\s*:?\s*({_NOME}(?:\s*(?:,|\be\b)\s*{_NOME})*)")
    _UM = re.compile(_NOME)

    def detectar(self, text: str) -> list[Span]:
        spans = []
        for m in self._RX.finditer(text):
            base = m.start(1)
            spans += [Span(base + n.start(), base + n.end(), "NOME")
                      for n in self._UM.finditer(m.group(1))]
        return spans
