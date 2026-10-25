from pathlib import Path

from carf import parallel as par
from carf.privacy import Anonymizer
from carf.solr import SolrClient
from carf.store import Store
from carf.sync import State

from .fakes import SessaoFalsa, doc


def corpus():
    docs, i = [], 0
    for ano in ("2023", "2024", "2025"):
        for secao, n in (("Primeira Seção", 5), ("Segunda Seção", 3), (None, 2)):
            for _ in range(n):
                i += 1
                extra = {"secao_s": secao, "ano_sessao_s": ano,
                         "dt_sessao_tdt": f"{ano}-03-16T00:00:00Z"}
                if secao is None:
                    extra.pop("secao_s")
                docs.append(doc(i, **extra))
    return docs


def cliente(docs):
    return SolrClient(session=SessaoFalsa(docs), delay=0, sleep=lambda s: None)


def test_fatiar_particao_completa_e_disjunta():
    docs = corpus()
    c = cliente(docs)
    us = par.fatiar(c, 2023)
    assert sum(u.n for u in us) == len(docs)
    cobertura = []
    for u in us:
        ids = [d["id"] for pag, _, _ in c.pages(["ano_sessao_s:[2023 TO *]", *u.fq], rows=7) for d in pag]
        cobertura += ids
    assert sorted(cobertura) == sorted(d["id"] for d in docs)  # nada some
    assert len(cobertura) == len(set(cobertura))  # nada repete


def test_distribuir_equilibra_e_nao_perde():
    us = [par.Unidade((f"a{i}",), n) for i, n in enumerate([50, 40, 30, 30, 20, 10, 10])]
    filas = par.distribuir(us, 3)
    assert sorted(u.fq for f in filas for u in f) == sorted(u.fq for u in us)
    cargas = [sum(u.n for u in f) for f in filas]
    assert max(cargas) - min(cargas) <= 20 and len(filas) == 3
    assert len(par.distribuir(us[:2], 5)) == 2  # sem filas vazias


def serial(data_dir_ignorado=None, limite_por_fila=None):
    docs = corpus()

    def executar(args):
        data_dir, fila, ano_min, leve, _, _, limite, ano_max = args
        return par.executar_fila(cliente(docs), Anonymizer(), Path(data_dir), fila, ano_min, leve,
                                 limite or limite_por_fila, log=lambda m: None, tamanho_pagina=4, ano_max=ano_max)
    return docs, executar


def rodar(tmp_path, executar, docs, **kw):
    return par.sincronizar_paralelo(tmp_path, 2023, workers=3, executor=executar,
                                    client=cliente(docs), log=lambda m: None, **kw)


def test_carga_paralela_leve_completa_e_retomavel(tmp_path):
    docs, executar = serial()
    r = rodar(tmp_path, executar, docs)
    assert r["completo"] and r["processados"] == len(docs)
    con = Store(tmp_path).connect()
    n, distintos, com_texto = con.execute(
        "select count(*), count(distinct id), count(*) filter (where tem_texto) from acordaos").fetchone()
    assert (n, distintos, com_texto) == (len(docs), len(docs), 0)  # leve: sem texto integral
    assert con.execute("select count(*) from acordaos where conteudo is not null").fetchone()[0] == 0
    g = State(tmp_path / "state.json").data
    assert g["full_done"] and g["last_dt_index"] == "2026-01-01T00:00:00Z" and g["leve"]
    # segunda execução: tudo já concluído, nada é reprocessado
    assert rodar(tmp_path, executar, docs)["processados"] == 0


def test_interrupcao_e_retomada_sem_duplicar(tmp_path):
    docs = corpus()
    _, parcial = serial(limite_por_fila=4)
    r1 = rodar(tmp_path, parcial, docs, limite=4)
    assert not r1["completo"] and not (tmp_path / "state.json").exists()  # global só ao final
    _, completo = serial()
    r2 = rodar(tmp_path, completo, docs)
    assert r2["completo"]
    n, d = Store(tmp_path).connect().execute("select count(*), count(distinct id) from acordaos").fetchone()
    assert d == len(docs) and n >= d  # versões repetidas são deduplicadas na view


def test_status(tmp_path):
    docs, executar = serial()
    assert par.status(tmp_path)["estado"] == "sem carga em andamento"
    rodar(tmp_path, executar, docs)
    st = par.status(tmp_path)
    assert st["unidades_concluidas"] == st["unidades"] and st["total_documentos"] == len(docs)


def test_incremental_depois_da_carga_paralela(tmp_path):
    from carf.sync import sincronizar

    docs, executar = serial()
    rodar(tmp_path, executar, docs)
    docs2 = docs + [doc(999, dt_index="2026-02-01T00:00:00Z", ano_sessao_s="2025",
                        dt_sessao_tdt="2025-05-05T00:00:00Z", secao_s="Primeira Seção")]
    r = sincronizar(cliente(docs2), Store(tmp_path), State(tmp_path / "state.json"), Anonymizer(),
                    ano_min=2023, incremental=True, log=lambda m: None)
    assert r["novos"] == 1 and r["completo"]
    assert Store(tmp_path).connect().execute("select tem_texto from acordaos where id='999'").fetchone()[0] is False


def test_leve_nao_marca_sem_texto(tmp_path):
    docs, executar = serial()
    rodar(tmp_path, executar, docs)
    q = Store(tmp_path).connect().execute("select count(*) from acordaos where qualidade like '%sem_texto%'")
    assert q.fetchone()[0] == 0


def test_unidade_com_erro_nao_derruba_as_outras(tmp_path, monkeypatch):
    docs, executar = serial()
    original = par.sincronizar
    chamadas = {"n": 0}

    def quebra_a_primeira(*a, **kw):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise TypeError("campo inesperado")
        return original(*a, **kw)

    monkeypatch.setattr(par, "sincronizar", quebra_a_primeira)
    r = rodar(tmp_path, executar, docs)
    assert not r["completo"] and len(r["erros"]) == 1 and "campo inesperado" in r["erros"][0]["erro"]
    # reexecução sem o defeito conclui só o que faltava
    monkeypatch.setattr(par, "sincronizar", original)
    r2 = rodar(tmp_path, executar, docs)
    assert r2["completo"] and not r2["erros"]
    d = Store(tmp_path).connect().execute("select count(distinct id) from acordaos").fetchone()[0]
    assert d == len(docs)


def test_faixa_de_anos_soma_a_carga_anterior(tmp_path):
    docs = corpus()  # 2023, 2024, 2025
    _, executar = serial()
    par.sincronizar_paralelo(tmp_path, 2025, workers=2, executor=executar, client=cliente(docs), log=lambda m: None)
    antes = State(tmp_path / "state.json").data
    assert antes["filters"] == {"ano_min": 2025}
    # segunda carga: só 2023-2024; o recorte global passa a 2023 e a marca-d'água não avança
    r = par.sincronizar_paralelo(tmp_path, 2023, workers=2, executor=executar, client=cliente(docs),
                                 log=lambda m: None, ano_max=2024)
    glob = State(tmp_path / "state.json").data
    assert r["completo"] and glob["filters"] == {"ano_min": 2023} and glob["full_done"]
    assert glob["last_dt_index"] <= antes["last_dt_index"]
    n = Store(tmp_path).connect().execute("select count(distinct id) from acordaos").fetchone()[0]
    assert n == len(docs)


def test_filtros_base_com_faixa():
    from carf.sync import filtros_base

    assert filtros_base(None) == [] and filtros_base(2018) == ["ano_sessao_s:[2018 TO *]"]
    assert filtros_base(2018, 2022) == ["ano_sessao_s:[2018 TO 2022]"]
