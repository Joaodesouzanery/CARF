"""Limpeza de texto e validação de campos do índice."""

import re
from datetime import date, datetime

_TIKA = re.compile(r"^\s*Metadados\s*=>.*?\|\s*Conte[úu]do\s*=>\s*", re.DOTALL)
ANO_MIN = 1970


def limpar_texto(text: str | None) -> str:
    if not text:
        return ""
    text = _TIKA.sub("", text, count=1)
    text = text.replace("\xad", "").replace("\x0c", "\n")
    text = re.sub(r"[ \t\r\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", s)
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups()))
    except ValueError:
        return None


def data_sessao_valida(s: str | None, hoje: date | None = None) -> date | None:
    dt = parse_datetime(s)
    if dt is None:
        return None
    limite = (hoje or date.today()).year + 1
    return dt.date() if ANO_MIN <= dt.year <= limite else None


def ano_valido(s: str | None, hoje: date | None = None) -> int | None:
    if not s or not s.isdigit():
        return None
    y = int(s)
    return y if ANO_MIN <= y <= (hoje or date.today()).year + 1 else None
