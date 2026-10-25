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


from datetime import datetime

from carf.store import Store
from carf.sync import montar_linha

from .fakes import doc

AGORA = datetime(2026, 10, 25)


@pytest.fixture
def con(tmp_path, anon):
    docs = [
        doc(1, ementa_s="IRPJ. Glosa de despesas operacionais. Prova insuficiente.", turma_s="T1"),
        doc(2, ementa_s="CSLL. Base de cálculo negativa. Compensação de prejuízos.", turma_s="T1",
            decisao_txt=["Acordam em dar provimento parcial ao recurso."]),
        doc(3, ementa_s="IRPJ. Omissão de receitas; depósitos bancários.", turma_s="T2",
            decisao_txt=["Acordam, por maioria, dar provimento ao recurso voluntário."]),
        doc(4, ementa_s="Preliminar. Nulidade. Não conhecimento.", turma_s="T2",
            decisao_txt=["Acordam em não conhecer do recurso."]),
    ]
    st = Store(tmp_path)
    st.write([montar_linha(d, anon, AGORA) for d in docs])
    return st.connect()


