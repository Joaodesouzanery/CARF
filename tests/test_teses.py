from datetime import datetime

import pytest

from carf.qa import consulta
from carf.store import SCHEMA, Store
from carf.teses import (
    classificar_tese,
    construir_facets,
    enriquecer,
    extrair_assunto,
    extrair_teses,
)

EM_CF = "Assunto: Classificação de Mercadorias Ano-calendário: 2015 NULIDADE. OCORRÊNCIA. Vício insanável por cerceamento."
EM_REJ = "Assunto: Imposto sobre a Renda Exercício: 2010 NULIDADE. INOCORRÊNCIA. Não há cerceamento de defesa."


def test_assunto_e_teses():
    assert extrair_assunto(EM_CF) == "Classificação de Mercadorias"
    assert extrair_assunto("Sem cabeçalho") is None
    assert extrair_teses(EM_CF).startswith("NULIDADE. OCORRÊNCIA")


@pytest.mark.parametrize("ementa,decisao,esperado", [
    (EM_REJ, "por unanimidade, rejeitar a preliminar de nulidade e, no mérito, negar provimento", "REJEITADA"),
    (EM_CF, "por unanimidade, declarar a nulidade do despacho decisório", "ACOLHIDA"),
    (EM_CF, "dar provimento ao recurso para anular a decisão recorrida", "ACOLHIDA"),
    (EM_REJ, "não acolher a preliminar de nulidade e negar provimento", "REJEITADA"),
    # voto vencido não vale
    (EM_REJ, "rejeitar a preliminar de nulidade. Fulano (Relator), que votou por acatar a preliminar de nulidade.", "REJEITADA"),
    # outra preliminar acolhida não é nulidade acolhida
    (EM_REJ, "acolher a preliminar de ilegitimidade passiva, cancelando o lançamento", "INDEFINIDA"),
    # rejeita uma e acolhe outra: acolhida
    (EM_REJ, "rejeitar a nulidade do acórdão e acolher a preliminar de nulidade da autuação", "ACOLHIDA"),
    ("Assunto: IRPJ Exercício: 2010 DEPÓSITOS BANCÁRIOS. OMISSÃO.", "negar provimento ao recurso", None),
])
def test_classificar_nulidade(ementa, decisao, esperado):
    assert classificar_tese("nulidade", ementa, decisao) == esperado


def test_enriquecer_traz_campos():
    f = enriquecer(EM_CF, "declarar a nulidade do despacho")
    assert f["assunto"] == "Classificação de Mercadorias" and f["tese_nulidade"] == "ACOLHIDA"
    assert f["tese_prescricao"] is None


def _linha(i, ementa, decisao):
    base = {c.name: None for c in SCHEMA}
    base.update(id=str(i), ementa=ementa, decisao=decisao, ano=2024, tem_texto=False, pii_mascarado=0,
              processado_em=datetime(2026, 1, 1), dt_index=datetime(2026, 1, 1))
    return base


def test_filtros_por_materia_e_tese(tmp_path):
    st = Store(tmp_path)
    st.write([
        _linha(1, EM_CF, "declarar a nulidade do despacho decisório"),
        _linha(2, EM_CF.replace("OCORRÊNCIA", "INOCORRÊNCIA"), "rejeitar a preliminar de nulidade"),
        _linha(3, EM_REJ.replace("Imposto sobre a Renda", "Classificação Fiscal"), "declarar a nulidade do lançamento"),
    ])
    con = st.connect()
    assert con.execute("select tese_nulidade from acordaos where id='1'").fetchone() == (None,)  # ainda sem facets
    assert construir_facets(st, log=lambda *_: None) == 3
    con = st.connect()
    r = consulta.buscar(con, "nulidade", {"assunto": "classificacao de mercadorias", "tese_nulidade": "ACOLHIDA"})
    assert [x["id"] for x in r] == ["1"]
    with pytest.raises(ValueError):
        consulta.buscar(con, "x", {"tese_inexistente": "1"})


@pytest.mark.parametrize("decisao,esperado", [
    ("rejeitar as arguições de nulidade; por maioria acolher a arguição de decadência", "REJEITADA"),
    ("dar provimento ao recurso, sem anulação do anterior, com análise do mérito", "INDEFINIDA"),
    ("acolher os embargos admitidos, sem efeitos infringentes, com retificação da nulidade", "INDEFINIDA"),
])
def test_falsos_acolhidos_corrigidos(decisao, esperado):
    assert classificar_tese("nulidade", "NULIDADE. TESE GENÉRICA.", decisao) == esperado


def test_assunto_sem_prefixo():
    em = "IMPOSTO SOBRE A RENDA DE PESSOA FÍSICA (IRPF) Ano-calendário: 2005 DEDUÇÃO. DESPESAS MÉDICAS. COMPROVAÇÃO. Recibos bastam."
    assert extrair_assunto(em) == "IMPOSTO SOBRE A RENDA DE PESSOA FÍSICA (IRPF)"
    assert extrair_teses(em).startswith("DEDUÇÃO. DESPESAS MÉDICAS")
    assert extrair_assunto("DEDUÇÃO. DESPESAS MÉDICAS. Comprovação por recibos.") is None


def test_sumulas_citadas():
    from carf.teses import extrair_sumulas

    assert extrair_sumulas("Súmula CARF nº 11 - Não se aplica a prescrição.", "conforme Súmulas CARF nºs 2, 28 e 85") == "2,11,28,85"
    assert extrair_sumulas("Súmula Vinculante nº 150 do STF", None) is None
    assert extrair_sumulas("Súmula CARF nº 11 (Vinculante, Portaria MF nº 277, de 07/06/2018)") == "11"
