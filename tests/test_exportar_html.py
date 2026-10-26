import sys
from pathlib import Path

import pytest

from carf.store import Store
from carf.teses import construir_facets

from .test_teses import EM_CF, EM_REJ, _linha

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "painel"))
import exportar_html


@pytest.fixture
def base(tmp_path):
    st = Store(tmp_path)
    st.write([_linha(1, EM_CF, "declarar a nulidade do despacho decisório"),
              _linha(2, EM_REJ, "rejeitar a preliminar de nulidade e negar provimento")])
    construir_facets(st, log=lambda *_: None)
    # o painel também lê o dado oficial; sem ele o gerador não deve quebrar o teste: cria vazio
    return tmp_path


def test_html_unico_com_filtro(base, tmp_path, monkeypatch):
    monkeypatch.setattr(exportar_html.exportar, "exportar_oficial",
                        lambda raiz, saida: (saida / "oficial.json").write_text('{"tendencia":[],"estoque":{"ref":"","linhas":[]}}'))
    out = tmp_path / "x.html"
    r = exportar_html.montar(base, out, nulidade="acolhida")
    html = out.read_text()
    assert r["acordaos"] == 1 and "window.__DADOS" in html and "</script><script" not in html.split("window.__DADOS")[0]
    assert "Classificação de Mercadorias" in html and "INOCORRÊNCIA" not in html


def test_limite_de_tamanho(base, tmp_path, monkeypatch):
    monkeypatch.setattr(exportar_html.exportar, "exportar_oficial",
                        lambda raiz, saida: (saida / "oficial.json").write_text('{"tendencia":[],"estoque":{"ref":"","linhas":[]}}'))
    with pytest.raises(SystemExit):
        exportar_html.montar(base, tmp_path / "y.html", limite_mb=0.001)


def test_compactado_volta_igual(base, tmp_path, monkeypatch):
    import base64
    import gzip
    import json
    import re

    monkeypatch.setattr(exportar_html.exportar, "exportar_oficial",
                        lambda raiz, saida: (saida / "oficial.json").write_text('{"tendencia":[],"estoque":{"ref":"","linhas":[]}}'))
    out = tmp_path / "z.html"
    exportar_html.montar(base, out, compactar=True)
    html = out.read_text()
    gz = json.loads(re.search(r"window\.__GZ=(\{.*?\});", html).group(1))
    ano = json.loads(gzip.decompress(base64.b64decode(gz["dados/ano-2024.json"])))
    assert sorted(r[0] for r in ano["rows"]) == ["1", "2"]
