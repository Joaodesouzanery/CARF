import json
from datetime import datetime

import pytest
from starlette.testclient import TestClient

from carf import server
from carf.store import Store
from carf.sync import montar_linha
from carf.teses import construir_facets

from .fakes import doc

AGORA = datetime(2026, 10, 25)
TOKEN = "carf_teste"


@pytest.fixture
def app(tmp_path, anon):
    docs = [
        doc(1, ementa_s="Assunto: Classificação de Mercadorias Ano-calendário: 2015 NULIDADE. OCORRÊNCIA. Vício.",
            decisao_txt=["Acordam em declarar a nulidade do despacho decisório."]),
        doc(2, ementa_s="Assunto: IRPJ Exercício: 2010 NULIDADE. INOCORRÊNCIA. Não há cerceamento.",
            decisao_txt=["Acordam em rejeitar a preliminar de nulidade e negar provimento."]),
    ]
    st = Store(tmp_path)
    st.write([montar_linha(d, anon, AGORA) for d in docs])
    construir_facets(st, log=lambda *_: None)
    return server.criar_app(tmp_path, tokens={server.hash_token(TOKEN): "Escritório Teste"}, por_minuto=5)


def test_sem_token_recusa(app):
    c = TestClient(app)
    assert c.get("/api/saude").status_code == 200
    assert c.post("/api/buscar", json={"q": "nulidade"}).status_code == 401
    assert c.post("/api/buscar", json={"q": "x"}, headers={"Authorization": "Bearer errado"}).status_code == 401


def test_busca_com_filtros_de_tese(app):
    c = TestClient(app)
    h = {"Authorization": f"Bearer {TOKEN}"}
    r = c.post("/api/buscar", headers=h, json={
        "q": "nulidade", "modo": "lexico",
        "filtros": {"assunto": "classificação de mercadorias", "tese_nulidade": "acolhida"}})
    assert r.status_code == 200
    res = r.json()["resultados"]
    assert [x["id"] for x in res] == ["1"] and res[0]["tese_nulidade"] == "ACOLHIDA"
    assert c.post("/api/buscar", headers=h, json={"q": "x", "filtros": {"senha": "1"}}).status_code == 400
    # só filtros, sem texto
    r = c.post("/api/buscar", headers=h, json={"filtros": {"tese_nulidade": "REJEITADA"}})
    assert [x["id"] for x in r.json()["resultados"]] == ["2"]


def test_semantico_sem_indice_cai_para_lexico(app):
    r = TestClient(app).post("/api/buscar", headers={"x-token": TOKEN}, json={"q": "nulidade"})
    assert r.status_code == 200 and r.json()["modo"] == "lexico"


def test_limite_de_taxa(app):
    c = TestClient(app)
    h = {"Authorization": f"Bearer {TOKEN}"}
    codigos = [c.get("/api/acordao/1", headers=h).status_code for _ in range(7)]
    assert codigos[:5] == [200] * 5 and codigos[5] == 429


def test_acordao_inexistente(app):
    assert TestClient(app).get("/api/acordao/999", headers={"x-token": TOKEN}).status_code == 404


def test_consulta_nao_vai_para_o_log(app, caplog):
    caplog.set_level("DEBUG")
    TestClient(app).post("/api/buscar", headers={"x-token": TOKEN}, json={"q": "estrategia-secreta-do-cliente"})
    assert "estrategia-secreta" not in caplog.text


def test_exige_token_ou_flag(tmp_path):
    with pytest.raises(ValueError):
        server.criar_app(tmp_path)
    assert server.criar_app(tmp_path, sem_token=True)


def test_novo_token_guarda_so_o_hash(tmp_path):
    arq = tmp_path / "t.json"
    tok = server.novo_token(arq, "Martinelli")
    guardado = json.loads(arq.read_text())
    assert tok not in arq.read_text() and guardado[server.hash_token(tok)] == "Martinelli"


def test_voto_integral_com_trechos(tmp_path, anon):
    app = server.criar_app(tmp_path, tokens={server.hash_token(TOKEN): "X"},
                           obter_voto=lambda i: {"conteudo": "Texto longo. A multa qualificada exige dolo comprovado. Fim.",
                                                 "citacao": "Acórdão 1", "nome_arquivo_pdf": "a.pdf"} if i == "7" else None)
    c = TestClient(app)
    h = {"x-token": TOKEN}
    r = c.get("/api/voto/7?q=multa qualificada", headers=h).json()
    assert r["trechos"] and "multa qualificada" in r["trechos"][0] and r["pdf"].endswith("a.pdf")
    assert c.get("/api/voto/8", headers=h).status_code == 404
    assert c.get("/api/voto/abc", headers=h).status_code == 400


def test_parecidos_usa_vetores(tmp_path, anon):
    import numpy as np

    from carf.embeddings import Indice
    from carf.store import Store
    from carf.sync import montar_linha

    docs = [doc(i, ementa_s=f"Ementa {i}") for i in (1, 2, 3)]
    Store(tmp_path).write([montar_linha(d, anon, AGORA) for d in docs])
    ind = Indice.__new__(Indice)
    ind.ids = np.array(["1", "2", "3"], dtype=object)
    ind.mat = np.array([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32)
    app = server.criar_app(tmp_path, tokens={server.hash_token(TOKEN): "X"}, indice=ind, embedder=object())
    r = TestClient(app).post("/api/parecidos", headers={"x-token": TOKEN}, json={"id": "1", "limite": 2}).json()
    assert [x["id"] for x in r["resultados"]][0] == "2"
