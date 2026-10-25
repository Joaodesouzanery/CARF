import json
import zipfile
from datetime import date

import pytest
import requests

from carf import gerenciais as g
from carf.privacy import Anonymizer
from carf.qa import gerenciais as qg

JULG = (
    '﻿"numero_processo","data_sessao","resultado_julgamento","votacao","turma","tipo_resultado",'
    '"tributo","info_geral","numero_decisao","concentracao_tematica","link_pdf","texto_ementa"\n'
    '"10580730835201048","2025-06-23","Recurso Voluntário Negado","Unânime","2ª TO","Acórdão","COFINS",'
    '"x","3102-002.836","INSUMOS","http://a/1.pdf","Ementa com CPF 529.982.247-25."\n'
    '"10580730835201049","2025-06-24","Recurso Voluntário Provido em Parte","Maioria","2ª TO","Acórdão",'
    '"COFINS","x","3102-002.837","INSUMOS","http://a/2.pdf","Outra ementa."\n'
    '"10580730835201050","2025-06-25","Recurso Especial da Procuradoria Provido","Qualidade","CSRF",'
    '"Acórdão","IRPJ","x","9101-001.000","GLOSA","http://a/3.pdf","Ementa 3."\n'
    '"10580730835201051","2025-06-26",,,"2ª TO","Resolução","IRPJ","x","3102-000.001","GLOSA",,\n'
)
EST = (
    '﻿"ano_referencia","mes_referencia","numero_processo","data_protocolo","data_entrada_carf",'
    '"questionamento1","questionamento2","tipo_contribuinte","tributo","fase_processual","instancia",'
    '"concentracao_tematica"\n'
    '2026,8,"111","2021-05-24","2025-06-23","RECURSO VOLUNTÁRIO",,"PF","IRPF","Acervo","TO/TE","OMISSÃO"\n'
    '2026,9,"111","2021-05-24","2025-06-23","RECURSO VOLUNTÁRIO",,"PF","IRPF","Acervo","TO/TE","OMISSÃO"\n'
    '2026,9,"222","2021-05-25","2025-06-24","RECURSO VOLUNTÁRIO",,"PJ","IRPJ","Julgamento","TO/TE","GLOSA"\n'
)


def zip_de(tmp, nome, csv):
    p = tmp / nome
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(nome.replace(".zip", ".csv"), csv.encode("utf-8"))
    return p


@pytest.mark.parametrize("texto,desf,rec", [
    ("Recurso Voluntário Negado", "NEGADO", "VOLUNTARIO"),
    ("Recurso Voluntário Provido em Parte", "PROVIDO_PARCIAL", "VOLUNTARIO"),
    ("Recurso Voluntário Provido", "PROVIDO", "VOLUNTARIO"),
    ("Recurso Voluntário Não Conhecido", "NAO_CONHECIDO", "VOLUNTARIO"),
    ("Recurso Especial da Procuradoria Provido em Parte", "PROVIDO_PARCIAL", "ESPECIAL_PROCURADORIA"),
    ("Recurso Especial do Contribuinte Negado", "NEGADO", "ESPECIAL_CONTRIBUINTE"),
    ("Recurso de Ofício Não Conhecido", "NAO_CONHECIDO", "OFICIO"),
    ("Embargos Acolhidos em Parte", "PROVIDO_PARCIAL", "EMBARGOS"),
    ("Embargos Acolhidos", "ACOLHIDO", "EMBARGOS"),
    ("Embargos Rejeitados", "REJEITADO", "EMBARGOS"),
    ("Embargos Não Conhecidos", "NAO_CONHECIDO", "EMBARGOS"),
])
def test_desfecho_oficial(texto, desf, rec):
    assert g.desfecho(texto) == desf and g.tipo_recurso(texto) == rec


def test_nulos():
    assert g.desfecho(None) is None and g.tipo_recurso("") is None


def test_ingere_julgamentos_anonimiza_ementa(tmp_path):
    out = g.ingerir_julgamentos(zip_de(tmp_path, "carf_julgamentos_2025.zip", JULG), tmp_path / "j", Anonymizer())
    assert out.name == "julgamentos_2025.parquet"
    import pandas as pd

    df = pd.read_parquet(out)
    assert len(df) == 4 and df["ano"].unique().tolist() == [2025]
    assert "529.982.247-25" not in " ".join(df["texto_ementa"].dropna()) and "[CPF]" in df["texto_ementa"][0]
    assert pd.isna(df.loc[3, "desfecho"]) and df.loc[3, "tipo_resultado"] == "Resolução"


def monta(tmp_path):
    g.ingerir_julgamentos(zip_de(tmp_path, "carf_julgamentos_2025.zip", JULG), tmp_path / "gerenciais" / "julgamentos")
    g.ingerir_estoque(zip_de(tmp_path, "est.zip", EST), tmp_path / "gerenciais" / "estoque")
    return qg.conectar(tmp_path)


def test_estatisticas_oficiais(tmp_path):
    con = monta(tmp_path)
    t = qg.desfecho_por(con, "tributo").set_index("tributo")
    assert t.loc["COFINS", "NEGADO"] == 1 and t.loc["COFINS", "PROVIDO_PARCIAL"] == 1
    assert "total" in t and t.loc["IRPJ", "total"] == 1  # resolução não conta
    e = qg.estoque_por(con, "tributo")
    assert e.attrs["referencia"] == "2026-09" and dict(zip(e["tributo"], e["processos"])) == {"IRPF": 1, "IRPJ": 1}
    with pytest.raises(ValueError):
        qg.estoque_por(con, "numero_processo")


class RespostaFalsa:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas, self.chamadas = respostas, []

    def get(self, url, headers=None, **kw):
        self.chamadas.append((url, dict(headers or {})))
        r = self.respostas[url]
        if isinstance(r, Exception):
            raise r
        return r


REC = g.Recurso("julgamentos", "x", "CSV", g.BASE + "carf_julgamentos_2025.zip")


def test_baixar_novo_inalterado_e_alterado(tmp_path):
    estado = {}
    s = SessaoFalsa({REC.url: RespostaFalsa(200, b"abc", {"ETag": "v1", "Last-Modified": "Wed"})})
    assert g.baixar(REC, tmp_path, estado, s)["status"] == "novo"
    assert g.baixar(REC, tmp_path, estado, s)["status"] == "inalterado"  # mesmo hash
    assert s.chamadas[1][1]["If-None-Match"] == "v1"  # pergunta condicional
    s.respostas[REC.url] = RespostaFalsa(304)
    assert g.baixar(REC, tmp_path, estado, s)["status"] == "inalterado"
    s.respostas[REC.url] = RespostaFalsa(200, b"novo conteudo")
    assert g.baixar(REC, tmp_path, estado, s)["status"] == "alterado"


def test_baixar_host_bloqueado_ou_inexistente(tmp_path):
    s = SessaoFalsa({REC.url: requests.ConnectionError("proxy 403")})
    assert g.baixar(REC, tmp_path, {}, s)["status"] == "inacessivel"
    s = SessaoFalsa({REC.url: RespostaFalsa(404)})
    assert g.baixar(REC, tmp_path, {}, s)["status"] == "inexistente"


def test_seed_e_candidatos():
    rs = g.carregar_recursos()
    assert sum(r.conjunto == "julgamentos" for r in rs) == 15 and any(r.arquivo == "carf_julgamentos_2025.zip" for r in rs)
    assert all(r.arquivo.endswith((".zip", ".pdf")) for r in rs)
    novos = [r.arquivo for r in g.candidatos_novos(rs, date(2026, 10, 25))]
    assert "carf_julgamentos_2026.zip" in novos and "carf_julgamentos_2025.zip" not in novos


def test_atualizar_ponta_a_ponta(tmp_path):
    csvs = {
        g.BASE + "carf_julgamentos_2025.zip": zip_de(tmp_path, "carf_julgamentos_2025.zip", JULG).read_bytes(),
    }
    class Sess:
        def get(self, url, headers=None, **kw):
            if url in csvs:
                return RespostaFalsa(200, csvs[url])
            return RespostaFalsa(404)
    r = g.atualizar(tmp_path / "d", session=Sess(), log=lambda m: None)
    assert r["novos"] == ["carf_julgamentos_2025.zip"] and r["ausentes"] > 0
    assert json.loads((tmp_path / "d/gerenciais/estado.json").read_text())
    assert g.atualizar(tmp_path / "d", session=Sess(), log=lambda m: None)["inalterados"] == 1
