import pytest

from carf.solr import SolrClient, SolrError
from carf.store import Store
from carf.sync import State, montar_linha, sincronizar

from .fakes import SessaoFalsa, doc


def cliente(docs, **kw):
    sessao = SessaoFalsa(docs, **kw)
    return SolrClient(session=sessao, delay=0, sleep=lambda s: None), sessao


def test_paginacao_percorre_tudo():
    c, _ = cliente([doc(i) for i in range(1, 8)])
    ids = [d["id"] for docs, _, _ in c.pages(rows=3) for d in docs]
    assert ids == [str(i) for i in range(1, 8)]


def test_retry_em_503_e_desiste_depois():
    c, s = cliente([doc(1)], falhas=[503, 503])
    assert c.summary()["num_found"] == 1
    assert len(s.chamadas) == 3
    c2, _ = cliente([doc(1)], falhas=[503] * 10)
    with pytest.raises(SolrError):
        c2.summary()


def test_respeita_intervalo_entre_requisicoes():
    esperas, t = [], [0.0]
    c = SolrClient(session=SessaoFalsa([doc(1)]), delay=1.0, clock=lambda: t[0],
                   sleep=lambda s: esperas.append(s))
    c.summary()
    c.summary()
    assert esperas == [1.0]


def test_montar_linha_anonimiza_e_marca_qualidade(anon):
    r = montar_linha(doc(1, dt_sessao_tdt="+191993-07-28T00:00:00Z", ano_sessao_s="0199"), anon,
                     __import__("datetime").datetime(2026, 10, 25))
    assert "529.982.247-25" not in r["ementa"] and "[CPF]" in r["ementa"]
    assert "João Carlos" not in r["ementa"]
    assert r["conteudo"] == "Voto do relator. Email [EMAIL]"
    assert r["ano"] is None and "data_sessao_invalida" in r["qualidade"]
    assert r["pii_mascarado"] >= 3


def rodar(c, tmp_path, anon, **kw):
    return sincronizar(c, Store(tmp_path), State(tmp_path / "state.json"), anon, log=lambda m: None, **kw)


def test_sync_completa_e_sem_texto_original_em_disco(tmp_path, anon):
    c, _ = cliente([doc(i) for i in range(1, 6)])
    r = rodar(c, tmp_path, anon)
    assert r["processados"] == 5 and r["completo"]
    con = Store(tmp_path).connect()
    assert con.execute("select count(*) from acordaos").fetchone()[0] == 5
    bruto = b"".join(p.read_bytes() for p in tmp_path.rglob("*.parquet"))
    assert b"529.982.247-25" not in bruto and "João Carlos".encode() not in bruto


def test_retomada_apos_interrupcao(tmp_path, anon):
    docs = [doc(i) for i in range(1, 11)]
    c1, _ = cliente(docs)
    parcial = rodar(c1, tmp_path, anon, limite=4, tamanho_pagina=4)
    assert parcial["processados"] == 4 and not parcial["completo"]
    estado = State(tmp_path / "state.json").data
    assert estado["full"]["cursor"] == "4" and "last_dt_index" not in estado

    c2, s2 = cliente(docs)
    final = rodar(c2, tmp_path, anon, tamanho_pagina=4)
    assert final["completo"] and final["processados"] == 6  # só o que faltava
    paginas = [p["cursorMark"] for p in s2.chamadas if "cursorMark" in p]
    assert paginas[0] == "4"
    con = Store(tmp_path).connect()
    assert con.execute("select count(distinct id) from acordaos").fetchone()[0] == 10
    assert State(tmp_path / "state.json").data["last_dt_index"] == "2026-01-01T00:00:00Z"


def test_incremental_traz_so_o_delta_e_atualiza_alterados(tmp_path, anon):
    docs = [doc(i) for i in range(1, 6)]
    rodar(cliente(docs)[0], tmp_path, anon)
    docs2 = [d for d in docs if d["id"] != "2"] + [
        doc(2, dt_index="2026-02-01T00:00:00Z", ementa_s="EMENTA NOVA SOBRE CSLL."),
        doc(6, dt_index="2026-02-01T00:00:00Z"),
    ]
    c, _ = cliente(docs2)
    r = rodar(c, tmp_path, anon, incremental=True)
    assert r == {"modo": "inc", "processados": 2, "novos": 1, "atualizados": 1, "ignorados": 4,
                 "completo": True}
    con = Store(tmp_path).connect()
    assert con.execute("select count(*) from acordaos").fetchone()[0] == 6
    assert con.execute("select ementa from acordaos where id='2'").fetchone()[0] == "EMENTA NOVA SOBRE CSLL."
    assert State(tmp_path / "state.json").data["last_dt_index"] == "2026-02-01T00:00:00Z"


def test_incremental_exige_carga_completa(tmp_path, anon):
    with pytest.raises(RuntimeError):
        rodar(cliente([doc(1)])[0], tmp_path, anon, incremental=True)


def test_compactacao_remove_versoes_antigas(tmp_path, anon):
    docs = [doc(i) for i in range(1, 4)]
    rodar(cliente(docs)[0], tmp_path, anon)
    rodar(cliente(docs + [doc(2, dt_index="2026-03-01T00:00:00Z")])[0], tmp_path, anon, incremental=True)
    store = Store(tmp_path)
    assert len(list(tmp_path.rglob("part-*.parquet"))) == 2
    assert store.compact() == 2
    assert len(list(tmp_path.rglob("part-*.parquet"))) == 1
    assert store.connect().execute("select count(*) from acordaos").fetchone()[0] == 3


def test_campos_multivalorados_nao_quebram(anon):
    d = doc(1, numero_decisao_s=["1301-000001", "x"], ementa_s=["Parte 1.", "Parte 2."],
            turma_s=["T1"], dt_sessao_tdt=["2022-03-16T00:00:00Z"], ano_sessao_s=["2022"])
    r = montar_linha(d, anon, __import__("datetime").datetime(2026, 1, 1))
    assert r["numero_decisao"] == "1301-000001" and r["turma"] == "T1"
    assert r["ementa"].startswith("Parte 1.\nParte 2.") and r["ano"] == 2022


def test_coluna_ano_continua_inteira_com_particao_desconhecida(tmp_path, anon):
    # a pasta `ano=desconhecido` não pode virar texto na coluna `ano`
    docs = [doc(1), doc(2, ano_sessao_s="0199", dt_sessao_tdt="+191993-07-28T00:00:00Z")]
    Store(tmp_path).write([montar_linha(d, anon, __import__("datetime").datetime(2026, 1, 1)) for d in docs])
    con = Store(tmp_path).connect()
    assert con.execute("select typeof(ano) from acordaos limit 1").fetchone()[0] == "INTEGER"
    assert con.execute("select count(*) from acordaos where ano is null").fetchone()[0] == 1
    assert con.execute("select max(ano) from acordaos").fetchone()[0] == 2022


def test_relator_com_cpf_da_fonte_e_descartado(tmp_path, anon):
    from datetime import datetime

    from carf.store import Store
    from carf.sync import montar_linha

    from .fakes import doc

    linha = montar_linha(doc(1, nome_relator_s="05751001842 - CPF não encontrado."), anon, datetime(2026, 1, 1))
    assert linha["relator"] is None
    # versões já gravadas antes da correção também saem mascaradas na leitura
    antiga = {**linha, "relator": "05751001842 - CPF não encontrado."}
    Store(tmp_path).write([antiga])
    assert Store(tmp_path).connect().execute("select relator from acordaos").fetchone() == (None,)
