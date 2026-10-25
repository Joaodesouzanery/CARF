import pytest

from carf.privacy import Anonymizer
from carf.privacy.ner import Allowlist


class NomesFalso:
    """NER de teste: reconhece nomes de uma lista fixa."""

    def __init__(self, nomes):
        self.nomes = nomes

    def detectar(self, text):
        from carf.privacy.rules import Span

        out = []
        for n in self.nomes:
            i = text.find(n)
            while i != -1:
                out.append(Span(i, i + len(n), "NOME"))
                i = text.find(n, i + 1)
        return out


@pytest.fixture
def anon():
    return Anonymizer(nomes=NomesFalso(["João Carlos da Silva", "Paulo Jakson da Silva Lucas",
                                        "Maria Souza"]), allowlist=Allowlist())
