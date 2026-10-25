"""Camada 1: detecção determinística de identificadores pessoais.

Números de processo e de decisão são protegidos (públicos e necessários para citação):
qualquer detecção que os toque é descartada.
"""

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str


def _digits(s: str) -> list[int]:
    return [int(c) for c in s if c.isdigit()]


def cpf_valido(s: str) -> bool:
    d = _digits(s)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        dv = (sum(v * (n + 1 - i) for i, v in enumerate(d[:n])) * 10) % 11 % 10
        if dv != d[n]:
            return False
    return True


_PESOS_CNPJ = (
    [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
    [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
)


def cnpj_valido(s: str) -> bool:
    d = _digits(s)
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for n, pesos in zip((12, 13), _PESOS_CNPJ):
        resto = sum(v * p for v, p in zip(d[:n], pesos)) % 11
        if (0 if resto < 2 else 11 - resto) != d[n]:
            return False
    return True


def _so(fn):
    return lambda _texto, m: fn(m.group(0))


_BANCOS = re.compile(
    r"(?i)\b(?:banco|ag[êe]ncia|bradesco|ita[uú]|santander|caixa\s+econ[ôo]mica|hsbc|sicredi|"
    r"sicoob|nubank|safra|banrisul|c/c)\b"
)


def _contexto_bancario(texto, m):
    return bool(_BANCOS.search(texto[max(0, m.start() - 80) : m.end() + 40]))


_SEP = r"\s*(?:n[º°o.]*\s*)?[:\-]?\s*"

PROTEGIDOS = [
    # processo: 10880.909334/2020-61, 10880-909.334/2020-61, 10880-909334/2020-61
    re.compile(r"(?<!\d)\d{4,5}[.\-]?\d{3}[.\-]?\d{3}/\d{4}-\d{2}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}(?!\d)"),  # processo sem pontuação
    re.compile(r"(?<!\d)\d{4}-\d{3}\.\d{3}(?!\d)"),  # número de decisão (ex.: 1301-000.868)
]

# (rótulo, regex, grupo, validador opcional)
REGRAS = [
    ("CPF", re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"), 0, None),
    ("CPF", re.compile(r"(?<![\d.\-/])\d{11}(?![\d.\-/])"), 0, _so(cpf_valido)),
    ("CNPJ", re.compile(r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)"), 0, None),
    ("CNPJ", re.compile(r"(?<![\d.\-/])\d{14}(?![\d.\-/])"), 0, _so(cnpj_valido)),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), 0, None),
    ("TELEFONE", re.compile(r"\(\d{2}\)\s?9?\d{4}[-\s]?\d{4}(?!\d)"), 0, None),
    ("TELEFONE", re.compile(r"(?<!\d)\d{2}\s9?\d{4}-\d{4}(?!\d)"), 0, None),
    ("TELEFONE", re.compile(r"\+55\s?\d{2}\s?9?\d{4}[-\s]?\d{4}(?!\d)"), 0, None),
    (
        "TELEFONE",
        re.compile(
            r"(?i)\b(?:tel(?:efone)?|fone|cel(?:ular)?|whats(?:app)?)\b\.?\s*:?\s*"
            r"([\d\s().+-]{8,20}\d)"
        ),
        1,
        None,
    ),
    ("CEP", re.compile(r"(?<![\d/-])(?<!\d\.)\d{5}-\d{3}(?![\d/-]|\.\d|\s*/)"), 0, None),
    ("RG", re.compile(r"(?i)\b(?:RG|identidade)\b" + _SEP + r"(\d[\d.\-xX]{4,14})"), 1, None),
    (
        "TITULO_ELEITOR",
        re.compile(r"(?i)t[íi]tulo\s+(?:de\s+)?eleitor(?:al)?" + _SEP + r"(\d[\d. ]{8,16}\d)"),
        1,
        None,
    ),
    ("CNH", re.compile(r"(?i)\bCNH\b" + _SEP + r"(\d{9,11})"), 1, None),
    (
        "PIS",
        re.compile(r"(?i)\b(?:PIS|PASEP|NIT)(?:/PASEP)?\b" + _SEP + r"(\d[\d.\-]{9,14}\d)"),
        1,
        None,
    ),
    (
        "CONTA_BANCARIA",
        re.compile(
            r"(?i)\b(?:ag[êe]ncia|c/c|conta[\s-]+(?:corrente|poupan[çc]a|banc[áa]ria))\b"
            + _SEP
            + r"(\d[\d.\-]{2,14}\d)"
        ),
        1,
        None,
    ),
    # "conta" solta é, na maioria, conta contábil: só conta se houver contexto de banco por perto.
    (
        "CONTA_BANCARIA",
        re.compile(r"(?i)\bconta\b" + _SEP + r"(\d[\d.\-]{2,14}\d)"),
        1,
        _contexto_bancario,
    ),
    ("PLACA", re.compile(r"(?i)\bplacas?\b" + _SEP + r"([A-Z]{3}-?\d[A-Z0-9]\d{2})\b"), 1, None),
]

TOKENS = {
    "CPF": "[CPF]",
    "CNPJ": "[CNPJ]",
    "EMAIL": "[EMAIL]",
    "TELEFONE": "[TELEFONE]",
    "CEP": "[CEP]",
    "RG": "[RG]",
    "TITULO_ELEITOR": "[TITULO_ELEITOR]",
    "CNH": "[CNH]",
    "PIS": "[PIS]",
    "CONTA_BANCARIA": "[CONTA_BANCARIA]",
    "PLACA": "[PLACA]",
    "NOME": "[NOME]",
}


def detectar(text: str, mascarar_cnpj: bool = True) -> list[Span]:
    protegidos = [m.span() for rx in PROTEGIDOS for m in rx.finditer(text)]
    spans = []
    for label, rx, grupo, validador in REGRAS:
        if label == "CNPJ" and not mascarar_cnpj:
            continue
        for m in rx.finditer(text):
            if validador and not validador(text, m):
                continue
            s, e = m.span(grupo)
            if any(s < pe and ps < e for ps, pe in protegidos):
                continue
            spans.append(Span(s, e, label))
    return unir(spans)


def unir(spans: list[Span]) -> list[Span]:
    """Une spans sobrepostos; o mais longo define o rótulo."""
    out: list[Span] = []
    for sp in sorted(spans, key=lambda x: (x.start, -(x.end - x.start))):
        if out and sp.start < out[-1].end:
            last = out[-1]
            label = last.label if (last.end - last.start) >= (sp.end - sp.start) else sp.label
            out[-1] = Span(last.start, max(last.end, sp.end), label)
        else:
            out.append(sp)
    return out


def aplicar(text: str, spans: list[Span]) -> tuple[str, Counter]:
    stats: Counter = Counter()
    for sp in sorted(spans, key=lambda x: x.start, reverse=True):
        text = text[: sp.start] + TOKENS[sp.label] + text[sp.end :]
        stats[sp.label] += 1
    return text, stats
