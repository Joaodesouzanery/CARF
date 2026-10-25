import json
from datetime import datetime

import pytest

from carf import config
from carf.monitor import verificar_indice
from carf.qa import ask, consulta
from carf.store import Store
from carf.sync import State, montar_linha

from .fakes import SessaoFalsa, doc

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


@pytest.mark.parametrize("texto,esperado", [
    ("negar provimento ao recurso voluntário", "NEGADO"),
    ("dar provimento parcial ao recurso", "PROVIDO_PARCIAL"),
    ("dar provimento ao recurso", "PROVIDO"),
    ("não conhecer do recurso", "NAO_CONHECIDO"),
    ("negar provimento ao recurso de ofício e dar provimento ao voluntário", "MISTO"),
    ("converter o julgamento em diligência", "OUTRO"),
    ("conhecer parcialmente do recurso, não conhecendo os argumentos de constitucionalidade. "
     "Na parte conhecida, em negar provimento ao Recurso Voluntário.", "NEGADO"),
    ("por maioria, em conhecer do recurso e, por unanimidade, em dar parcial provimento", "PROVIDO_PARCIAL"),
    ("conhecer do Recurso Voluntário, dando-lhe provimento", "PROVIDO"),
    ("conhecer e acolher parcialmente os Embargos de Declaração", "PROVIDO_PARCIAL"),
    ("acolher os embargos de declaração, sem efeitos infringentes", "ACOLHIDO"),
    ("rejeitar os embargos de declaração", "REJEITADO"),
    ("rejeitar a preliminar e, no mérito, negar provimento ao recurso", "NEGADO"),
    ("rejeitar a preliminar, vencida, neste ponto, a conselheira Maria, e, no mérito, negar provimento", "NEGADO"),
    ("negar provimento, vencidos os Conselheiros A e B que votaram por dar provimento ao recurso", "NEGADO"),
    ("acolher os embargos para alterar o dispositivo de: “não conhecer” para: “dar-lhe provimento”", "ACOLHIDO"),
    ("dar parcial provimento ao recurso para reverter glosas, mantendo outras; negar provimento quanto ao frete",
     "PROVIDO_PARCIAL"),
    ("negar provimento ao recurso de ofício e dar parcial provimento ao recurso voluntário", "MISTO"),
    (None, "OUTRO"),
])
def test_classificar_resultado(texto, esperado):
    assert consulta.classificar_resultado(texto) == esperado


def test_busca_exige_todos_os_termos_e_ignora_acento(con):
    r = consulta.buscar(con, "glosa despesas operacionais")
    assert [x["id"] for x in r] == ["1"]
    assert "Acórdão 1301-000001" in r[0]["citacao"] and "Proc" in r[0]["citacao"]
    assert [x["id"] for x in consulta.buscar(con, "omissao receitas")] == ["3"]
    assert consulta.buscar(con, "inexistente xyz") == []


def test_busca_com_filtro_e_validacao(con):
    assert [x["id"] for x in consulta.buscar(con, "irpj", {"turma": "T2"})] == ["3"]
    with pytest.raises(ValueError):
        consulta.buscar(con, "irpj", {"drop": "x"})
    with pytest.raises(ValueError):
        consulta.buscar(con, "a de")


def test_estatisticas(con):
    c = consulta.contagem(con, "turma")
    assert dict(zip(c["turma"], c["acordaos"])) == {"T1": 2, "T2": 2}
    t = consulta.taxa_resultado(con, "turma").set_index("turma")
    assert t.loc["T1", "NEGADO"] == 1 and t.loc["T1", "PROVIDO_PARCIAL"] == 1
    assert t.loc["T2", "total"] == 2
    so_irpj = consulta.taxa_resultado(con, "turma", termo="IRPJ").set_index("turma")
    assert so_irpj.loc["T1", "total"] == 1


def test_relator_protegido_por_amostra_minima(con):
    assert consulta.contagem(con, "relator").empty  # 4 casos < mínimo
    assert config.MIN_SAMPLE_PER_RELATOR > 4


def test_ferramentas_do_llm(con):
    out = json.loads(ask.executar(con, "buscar_acordaos", {"termos": "csll compensação"}))
    assert out[0]["id"] == "2" and "citacao" in out[0]
    assert json.loads(ask.executar(con, "obter_acordao", {"id": "3"}))["id"] == "3"
    assert "erro" in json.loads(ask.executar(con, "contagem", {"por": "cpf"}))
    assert "erro" in json.loads(ask.executar(con, "inexistente", {}))


def test_perguntar_sem_chave_falha_claro(con, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ask.perguntar(con, "?")


def test_monitor_detecta_atualizacao(tmp_path):
    from carf.solr import SolrClient

    docs = [doc(1), doc(2, dt_index="2026-05-01T00:00:00Z")]
    c = SolrClient(session=SessaoFalsa(docs), delay=0, sleep=lambda s: None)
    st = State(tmp_path / "s.json")
    assert verificar_indice(c, st)["ha_atualizacao"]  # nunca sincronizado
    st.data["last_dt_index"] = "2026-05-01T00:00:00Z"
    r = verificar_indice(c, st)
    assert not r["ha_atualizacao"] and r["pendentes"] == 1  # o próprio limite (inclusivo)
    st.data["last_dt_index"] = "2026-04-01T00:00:00Z"
    assert verificar_indice(c, st)["ha_atualizacao"]
