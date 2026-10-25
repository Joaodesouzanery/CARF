import pytest

from carf.privacy import Anonymizer, residual_pii
from carf.privacy.rules import cnpj_valido, cpf_valido

CPF_OK = "529.982.247-25"
CNPJ_OK = "11.222.333/0001-81"


def limpa(texto, **kw):
    return Anonymizer(**kw).anonymize(texto)[0]


def test_validadores():
    assert cpf_valido(CPF_OK) and cpf_valido("52998224725")
    assert not cpf_valido("529.982.247-24") and not cpf_valido("111.111.111-11")
    assert cnpj_valido(CNPJ_OK) and cnpj_valido("11222333000181")
    assert not cnpj_valido("11.222.333/0001-80")


@pytest.mark.parametrize("texto,token", [
    (f"CPF {CPF_OK} do sócio", "[CPF]"),
    ("CPF 52998224725 do sócio", "[CPF]"),
    ("CPF 123.456.789-00 inválido mas formatado", "[CPF]"),
    (f"empresa {CNPJ_OK}", "[CNPJ]"),
    ("empresa 11222333000181 ltda", "[CNPJ]"),
    ("contato fulano.silva@empresa.com.br hoje", "[EMAIL]"),
    ("ligue (11) 91234-5678 agora", "[TELEFONE]"),
    ("ligue 11 91234-5678 agora", "[TELEFONE]"),
    ("telefone: 11 3456 7890", "[TELEFONE]"),
    ("CEP 01310-100 Av. Paulista", "[CEP]"),
    ("RG nº 12.345.678-9 SSP", "[RG]"),
    ("título de eleitor 1234 5678 9012", "[TITULO_ELEITOR]"),
    ("CNH: 12345678901", "[CNH]"),
    ("PIS 123.45678.90-1", "[PIS]"),
    ("agência 1234-5 conta corrente 98765-4", "[CONTA_BANCARIA]"),
    ("placa ABC-1D23 do veículo", "[PLACA]"),
])
def test_mascara_identificadores(texto, token):
    out = limpa(texto)
    assert token in out
    assert residual_pii(out) == []


def test_preserva_numeros_publicos():
    texto = ("Processo 13896.904173/2008-79, também 13896904173200879, "
             "Acórdão 1301-000.868 de 2012, valor R$ 1.234.567,89, ano 2012, art. 23 do Decreto 70.235.")
    assert limpa(texto) == texto


def test_conta_nao_mascara_prazo():
    texto = "Conta-se o prazo de 30 dias a partir de 2010; a conta do mês 12 foi paga."
    assert limpa(texto) == texto


def test_cnpj_opcional():
    assert limpa(f"empresa {CNPJ_OK}", mascarar_cnpj=False) == f"empresa {CNPJ_OK}"


def test_idempotente():
    uma = limpa(f"CPF {CPF_OK} e {CNPJ_OK}")
    assert limpa(uma) == uma


@pytest.mark.parametrize("processo", [
    "10880.909334/2020-61", "10880-909.334/2020-61", "10880-909156/2013-76", "13896904173200879",
])
def test_processos_reais_nao_viram_cep_nem_outra_coisa(processo):
    texto = f"cancelamento dos autos de infração n.º {processo} e PAF {processo}, fls. 3.040"
    assert limpa(texto) == texto


def test_cep_isolado_continua_mascarado():
    assert limpa("Av. Paulista, 1000, CEP 01310-100.") == "Av. Paulista, 1000, CEP [CEP]."


@pytest.mark.parametrize("texto", [
    "lançado na conta 4.1.2.01 - Aluguel e condomínio",
    "Foi apontada a conta 2330, de despesas",
    "valores extraídos da conta 3351 FRETE",
])
def test_conta_contabil_nao_e_conta_bancaria(texto):
    assert limpa(texto) == texto


@pytest.mark.parametrize("texto", [
    "Banco do Brasil (agência 1234-X, c/c 56789-0)",
    "créditos bancários da conta nº 12345-6, mantida no HSBC",
    "conta corrente 98765-4",
])
def test_conta_bancaria_mascarada(texto):
    out = limpa(texto)
    assert "[CONTA_BANCARIA]" in out and not any(c.isdigit() for c in out)
