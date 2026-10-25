from datetime import datetime

import numpy as np
import pytest

from carf.embeddings import Embedder, Indice, indexar, rrf
from carf.qa import consulta, semantico
from carf.store import Store
from carf.sync import montar_linha

from .fakes import doc

TEMAS = ["insumo credito pis cofins", "glosa despesas operacionais", "omissao receitas depositos bancarios",
         "multa isolada compensacao"]


class SacoDePalavras(Embedder):
    """Embedder de teste: vetor de presença de palavras-chave (determinístico, sem modelo)."""

    nome, dim = "teste", 12

    def __init__(self):
        self.vocab = sorted({w for t in TEMAS for w in t.split()})
        self.dim = len(self.vocab)

    def codificar(self, textos, consulta=False):
        m = np.zeros((len(textos), self.dim), dtype=np.float32)
        for i, t in enumerate(textos):
            for j, w in enumerate(self.vocab):
                if w in t.lower():
                    m[i, j] = 1
        n = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(n == 0, 1, n)


@pytest.fixture
def base(tmp_path, anon):
    docs = [
        doc(1, ementa_s="Crédito de PIS e COFINS sobre insumo essencial.", turma_s="T1", ano_sessao_s="2023"),
        doc(2, ementa_s="Glosa de despesas operacionais sem prova.", turma_s="T1", ano_sessao_s="2024"),
        doc(3, ementa_s="Omissão de receitas por depósitos bancários.", turma_s="T2", ano_sessao_s="2024"),
        doc(4, ementa_s="Multa isolada e compensação indevida.", turma_s="T2", ano_sessao_s="2024"),
        doc(5, ementa_s="Preliminar de nulidade rejeitada.", turma_s="T2", ano_sessao_s="2024"),
    ]
    st = Store(tmp_path)
    st.write([montar_linha(d, anon, datetime(2026, 1, 1)) for d in docs])
    return tmp_path, st.connect()


def test_rrf_favorece_quem_aparece_nas_duas():
    r = rrf([["a", "b", "c"], ["b", "c", "d"]])
    assert [i for i, _ in r][:2] == ["b", "c"] and {i for i, _ in r} == {"a", "b", "c", "d"}


def test_indexar_busca_e_retoma(base):
    raiz, con = base
    emb, idx = SacoDePalavras(), Indice(raiz, "teste")
    assert indexar(con, idx, emb, lote=2, limite=3, log=lambda m: None) == 3
    assert indexar(con, idx, emb, lote=2, log=lambda m: None) == 2  # só o que faltava
    assert indexar(con, idx, emb, log=lambda m: None) == 0
    idx.carregar()
    assert len(idx.ids) == 5 and idx.mat.dtype == np.float32
    top = idx.buscar(emb.codificar(["glosa despesas"], consulta=True)[0], k=2)
    assert top[0][0] == "2" and top[0][1] > top[1][1]


def test_semantico_acha_sem_o_termo_exato(base):
    raiz, con = base
    emb, idx = SacoDePalavras(), Indice(raiz, "teste")
    indexar(con, idx, emb, log=lambda m: None)
    idx.carregar()
    # a consulta não contém "omissão"; o embedder a aproxima de "receitas depósitos"
    r = semantico.buscar(con, "receitas depositos bancarios", modo="semantico", indice=idx, embedder=emb, limite=2)
    assert r[0]["id"] == "3" and "citacao" in r[0] and r[0]["score"] > 0.5


def test_filtros_valem_na_busca_semantica(base):
    raiz, con = base
    emb, idx = SacoDePalavras(), Indice(raiz, "teste")
    indexar(con, idx, emb, log=lambda m: None)
    idx.carregar()
    r = semantico.buscar(con, "glosa despesas", {"turma": "T2"}, 5, "semantico", idx, emb)
    assert "2" not in [x["id"] for x in r] and all(x["turma"] == "T2" for x in r)


def test_hibrido_junta_lexico_e_semantico(base):
    raiz, con = base
    emb, idx = SacoDePalavras(), Indice(raiz, "teste")
    indexar(con, idx, emb, log=lambda m: None)
    idx.carregar()
    r = semantico.buscar(con, "preliminar nulidade", modo="hibrido", indice=idx, embedder=emb, limite=3)
    assert r[0]["id"] == "5"  # o vetor não conhece essas palavras; a parte léxica resolve
    assert semantico.buscar(con, "glosa", modo="lexico", limite=3)[0]["id"] == "2"
    with pytest.raises(ValueError):
        semantico.buscar(con, "x", modo="semantico")
    with pytest.raises(ValueError):
        semantico.buscar(con, "x", modo="outro")


def test_lexico_qualquer_ranqueia_por_termos_casados(base):
    _, con = base
    r = consulta.buscar(con, "glosa despesas operacionais omissao", qualquer=True, limite=5)
    assert r[0]["id"] == "2" and len(r) >= 2
    assert consulta.buscar(con, "glosa omissao", qualquer=False) == []  # E: nenhum tem ambos


def test_indice_deduplica_por_id(tmp_path):
    idx = Indice(tmp_path, "m")
    idx.gravar(["a", "b"], np.array([[1, 0], [0, 1]], dtype=np.float32))
    idx.gravar(["a"], np.array([[0, 1]], dtype=np.float32))  # versão nova de "a"
    idx.carregar()
    assert len(idx.ids) == 2
    assert idx.buscar(np.array([0, 1], dtype=np.float32), 2)[0][1] == pytest.approx(1.0, abs=1e-3)


def test_agrupa_ementas_iguais_salvo_datas():
    from carf.qa.semantico import agrupar_iguais

    linhas = [
        {"id": "1", "ementa": "Assunto: PIS Período de apuração: 01/01/2013 a 31/03/2013 FRETE. CRÉDITO."},
        {"id": "2", "ementa": "Assunto: PIS Período de apuração: 01/04/2013 a 30/06/2013 FRETE. CRÉDITO."},
        {"id": "3", "ementa": "Outra ementa diferente."},
        {"id": "4", "ementa": "Assunto: PIS Período de apuração: 01/07/2013 a 30/09/2013 FRETE. CRÉDITO."},
    ]
    g = agrupar_iguais(linhas, 10)
    assert [r["id"] for r in g] == ["1", "3"] and g[0]["iguais"] == 3 and g[0]["ids_iguais"] == ["2", "4"]
    assert agrupar_iguais(linhas, 1) == g[:1]


def test_busca_agrupada_completa_o_limite_com_distintos(base):
    raiz, con = base
    emb, idx = SacoDePalavras(), Indice(raiz, "teste")
    indexar(con, idx, emb, log=lambda m: None)
    idx.carregar()
    r = semantico.buscar(con, "irpj csll compensacao", modo="semantico", indice=idx, embedder=emb, limite=3)
    assert len({x["id"] for x in r}) == len(r) and all("iguais" in x for x in r)
