import json
from types import SimpleNamespace as NS

from carf.qa import ask


class ClienteFalso:
    """Imita anthropic.Anthropic().messages.create com respostas roteirizadas."""

    def __init__(self, respostas):
        self.respostas, self.chamadas = list(respostas), []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.chamadas.append(json.loads(json.dumps(kw["messages"], default=lambda o: "<bloco>")))
        self.ultimo_kw = kw
        return self.respostas.pop(0)


def uso(*blocos, parar="tool_use"):
    return NS(content=list(blocos), stop_reason=parar)


def tool(id_, nome, **args):
    return NS(type="tool_use", id=id_, name=nome, input=args)


def texto(t):
    return NS(type="text", text=t)


def test_ask_ponta_a_ponta(con):
    c = ClienteFalso([
        uso(tool("t1", "buscar_acordaos", termos="csll compensação"), tool("t2", "contagem", por="turma")),
        uso(tool("t3", "ferramenta_que_nao_existe")),
        uso(texto("Achei o acórdão 1301-000002 [id 2]."), parar="end_turn"),
    ])
    r = ask.perguntar(con, "Algo sobre CSLL?", cliente=c)
    assert r == "Achei o acórdão 1301-000002 [id 2]."
    assert len(c.chamadas) == 3
    # a 2ª chamada devolveu os resultados das DUAS ferramentas, com citação
    resultados = c.respostas  # esgotado
    assert resultados == []
    assert c.ultimo_kw["tools"] == ask.TOOLS and "citação" in c.ultimo_kw["system"].lower()


def test_resultados_das_ferramentas_chegam_ao_modelo(con):
    capturado = []

    class C(ClienteFalso):
        def _create(self, **kw):
            capturado.append(kw["messages"][-1])
            return super()._create(**kw)

    c = C([uso(tool("t1", "buscar_acordaos", termos="csll compensação")),
           uso(texto("ok"), parar="end_turn")])
    ask.perguntar(con, "q", cliente=c)
    ultimo = capturado[-1]
    assert ultimo["role"] == "user" and ultimo["content"][0]["tool_use_id"] == "t1"
    dados = json.loads(ultimo["content"][0]["content"])
    assert dados[0]["id"] == "2" and "Acórdão" in dados[0]["citacao"]


def test_erro_de_ferramenta_volta_como_json_nao_excecao(con):
    c = ClienteFalso([uso(tool("t1", "contagem", por="cpf")), uso(texto("fim"), parar="end_turn")])
    assert ask.perguntar(con, "q", cliente=c) == "fim"


def test_limite_de_turnos(con):
    c = ClienteFalso([uso(tool(f"t{i}", "contagem", por="turma")) for i in range(3)])
    assert "Limite de passos" in ask.perguntar(con, "q", cliente=c, max_turnos=3)


def test_ferramentas_novas_degradam_com_mensagem_clara(con):
    for nome, args in (("buscar_semantico", {"consulta": "x"}), ("desfecho_oficial", {"por": "tributo"}),
                       ("estoque", {"por": "tributo"})):
        assert "erro" in json.loads(ask.executar(con, nome, args))


def test_ferramentas_novas_com_dados(con, tmp_path):
    import numpy as np

    from carf import gerenciais as g
    from carf.embeddings import Indice, indexar
    from carf.qa import gerenciais as qg

    from .test_gerenciais import EST, JULG, zip_de
    from .test_semantico import SacoDePalavras

    g.ingerir_julgamentos(zip_de(tmp_path, "carf_julgamentos_2025.zip", JULG), tmp_path / "gerenciais/julgamentos")
    g.ingerir_estoque(zip_de(tmp_path, "est.zip", EST), tmp_path / "gerenciais/estoque")
    ger = qg.conectar(tmp_path)
    emb, idx = SacoDePalavras(), Indice(tmp_path, "t")
    indexar(con, idx, emb, log=lambda m: None)
    idx.carregar()
    d = json.loads(ask.executar(con, "desfecho_oficial", {"por": "tributo"}, ger=ger))
    assert {x["tributo"] for x in d} == {"COFINS", "IRPJ"}
    e = json.loads(ask.executar(con, "estoque", {"por": "tributo"}, ger=ger))
    assert e["referencia"] == "2026-09" and e["linhas"]
    s = json.loads(ask.executar(con, "buscar_semantico", {"consulta": "csll compensacao"}, sem=(idx, emb)))
    assert isinstance(s, list) and np.isscalar(len(s))
