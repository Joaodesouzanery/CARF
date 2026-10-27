from datetime import date

from carf.text import ano_valido, data_sessao_valida, limpar_texto

TIKA = "Metadados => pdf:PDFVersion: 1.4; X: y | Conteúdo => \nS1­C3T1 \n\nFl. 1 \n\n \n \n\nTexto"


def test_remove_cabecalho_tika_e_soft_hyphen():
    assert limpar_texto(TIKA) == "S1C3T1\n\nFl. 1\n\nTexto"


def test_datas_absurdas():
    hoje = date(2026, 10, 25)
    assert data_sessao_valida("2012-03-16T00:00:00Z", hoje) == date(2012, 3, 16)
    assert data_sessao_valida("-0019-09-09T00:00:00Z", hoje) is None
    assert data_sessao_valida("+191993-07-28T00:00:00Z", hoje) is None
    assert data_sessao_valida(None, hoje) is None
    assert ano_valido("0199", hoje) is None and ano_valido("2012", hoje) == 2012


def test_marca_dagua_vertical_removida():
    from carf.text import limpar_texto

    bruto = "D\nO\n\nC\nU\n\nM\nE\n\nN\nT\nO\n\nMINISTÉRIO DA FAZENDA\nAcórdão 1"
    assert limpar_texto(bruto).startswith("MINISTÉRIO DA FAZENDA")
