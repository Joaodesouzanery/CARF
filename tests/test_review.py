import csv
import json
from datetime import datetime

import pytest

from carf import review
from carf.auditoria import auditar_profundo, candidatos_vazamento
from carf.store import Store
from carf.sync import montar_linha

from .conftest import NomesFalso
from .fakes import doc


def test_wilson():
    lo, hi = review.wilson(0, 100)
    assert lo == 0 and 0.03 < hi < 0.04
    lo, hi = review.wilson(5, 100)
    assert 0.02 < lo < 0.03 and 0.10 < hi < 0.12
    assert review.wilson(0, 0) == (0.0, 0.0)


def test_candidatos_vazamento_texto_anonimizado_e_vazado():
    limpo = "O contribuinte [NOME] pagou [CPF] no processo 10880.909334/2020-61 e 13896904173200879."
    assert candidatos_vazamento(limpo) == []
    sujo = "O Sr. Carlos Lima informou CPF 52998 224 e conta 123456789012 no processo 10880.909334/2020-61."
    achados = " | ".join(candidatos_vazamento(sujo))
    assert "tratamento+nome: Sr. Carlos" in achados and "cpf:" in achados and "123456789012" in achados
    assert "10880" not in achados  # número de processo não é vazamento
    ner = NomesFalso(["Maria Souza"])
    assert "nome: Maria Souza" in candidatos_vazamento("Quem pagou foi Maria Souza ontem.", ner)
    assert candidatos_vazamento("Quem pagou foi [NOME] ontem.", ner) == []


@pytest.fixture
def con(tmp_path, anon):
    docs = [doc(1, ementa_s="Ementa limpa [NOME] decidiu."),
            doc(2, ementa_s="Aqui vazou Maria Souza sem máscara."),
            doc(3, ementa_s="Outra ementa com [CPF].")]
    st = Store(tmp_path)
    rows = [montar_linha(d, anon, datetime(2026, 1, 1)) for d in docs]
    rows[1]["ementa"] = "Aqui vazou Maria Souza sem máscara."  # simula falha da anonimização
    st.write(rows)
    return st.connect()


def test_auditoria_profunda_acha_o_vazamento_plantado(con):
    r = auditar_profundo(con, n=10, seed=1, ner=NomesFalso(["Maria Souza"]))
    assert r["amostra"] == 3 and r["docs_com_candidatos"] == 1
    assert r["por_tipo"] == {"nome": 1} and "Maria Souza" in r["exemplos"]["nome"][0]


def test_amostra_gera_md_e_csv_reprodutivel(con, tmp_path):
    a = review.amostrar(con, 2, seed=7, saida=tmp_path / "rev", ner=NomesFalso(["Maria Souza"]))
    b = review.amostrar(con, 2, seed=7, saida=tmp_path / "rev2", ner=None)
    def ids(r):
        with open(r["csv"], encoding="utf-8") as f:
            return [x["id"] for x in csv.DictReader(f)]

    assert ids(a) == ids(b) and a["documentos"] == 2
    with open(a["md"], encoding="utf-8") as f:
        md = f.read()
    assert "Contexto das máscaras" in md and "Trecho sem máscara" in md
    with open(a["csv"], encoding="utf-8") as f:
        cab = f.readline().strip().split(",")
    assert cab == review.COLUNAS


def test_pontuar(tmp_path):
    p = tmp_path / "m.csv"
    linhas = [
        {"id": "1", "citacao": "a", "palavras": "1000", "total_mascaras": "10",
         "qtd_nomes_remanescentes": "0", "qtd_identificadores_remanescentes": "0",
         "qtd_mascaras_indevidas": "1", "observacoes": ""},
        {"id": "2", "citacao": "b", "palavras": "3000", "total_mascaras": "30",
         "qtd_nomes_remanescentes": "2", "qtd_identificadores_remanescentes": "1",
         "qtd_mascaras_indevidas": "3", "observacoes": ""},
        {"id": "3", "citacao": "c", "palavras": "500", "total_mascaras": "5",
         "qtd_nomes_remanescentes": "", "qtd_identificadores_remanescentes": "",
         "qtd_mascaras_indevidas": "", "observacoes": ""},
    ]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=review.COLUNAS)
        w.writeheader()
        w.writerows(linhas)
    r = review.pontuar(p)
    assert (r["revisados"], r["pendentes"], r["docs_com_vazamento"]) == (2, 1, 1)
    assert r["taxa_docs_com_vazamento"] == 0.5 and r["vazamentos_por_mil_palavras"] == pytest.approx(0.75)
    assert r["nomes_remanescentes"] == 2 and r["taxa_mascara_indevida"] == pytest.approx(4 / 40)
    json.dumps(r)  # serializável para o registro
