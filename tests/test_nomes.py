from carf.privacy import Anonymizer
from carf.privacy.ner import Allowlist, NomesPorContexto, normalizar_nome

from .conftest import NomesFalso


def test_normalizar():
    assert normalizar_nome("JOÃO Carlos da Silva") == ["joao", "carlos", "silva"]


def test_allowlist_aceita_variacoes_do_relator():
    al = Allowlist(["PAULO JAKSON DA SILVA LUCAS"])
    assert al.permite("Paulo Jakson da Silva Lucas")
    assert al.permite("Conselheiro Paulo Jakson")
    assert not al.permite("Paulo")  # nome único nunca é permitido
    assert not al.permite("Paulo Souza")


def test_mascara_contribuinte_e_preserva_relator(anon):
    texto = "O contribuinte João Carlos da Silva recorreu. Relator Paulo Jakson da Silva Lucas votou."
    out, st = anon.anonymize(texto, permitidos=["PAULO JAKSON DA SILVA LUCAS"])
    assert "João Carlos" not in out and "[NOME]" in out
    assert "Paulo Jakson da Silva Lucas" in out
    assert st["NOME"] == 1


def test_nome_dentro_de_numero_publico_nao_e_tocado():
    anon = Anonymizer(nomes=NomesFalso(["Maria Souza"]))
    out, _ = anon.anonymize("Maria Souza, processo 13896.904173/2008-79, CPF 529.982.247-25")
    assert out == "[NOME], processo 13896.904173/2008-79, CPF [CPF]"


def test_reserva_por_contexto():
    texto = "Recorrente: Carlos Alberto de Souza apresentou recurso."
    spans = NomesPorContexto().detectar(texto)
    assert [texto[s.start : s.end] for s in spans] == ["Carlos Alberto de Souza"]


def test_sem_ner_so_regras():
    out, _ = Anonymizer().anonymize("João Silva CPF 529.982.247-25")
    assert out == "João Silva CPF [CPF]"


def _refina(texto):
    from carf.privacy.ner import refinar
    from carf.privacy.rules import Span

    sp = refinar(texto, Span(0, len(texto), "NOME"))
    return texto[sp.start : sp.end] if sp else None


def test_refinar_descarta_siglas_e_termos_juridicos():
    for t in ["COFINS", "PIS", "inciso II", "ÔNUS DA PROVA", "Despacho Decisório", "Turma Julgadora",
              "NEGAR-LHE PROVIMENTO", "DO DECURSO INTEGRAL", "Condeno o Réu", "Desembargador Relator",
              "PREVIDENCIÁRIAS\n\nPeríodo"]:
        assert _refina(t) is None, t


def test_refinar_apara_titulos_e_marcadores():
    assert _refina("Conselheiro Damião Cordeiro de Moraes") == "Damião Cordeiro de Moraes"
    assert _refina("Rayd Santana Ferreira\n\nFl") == "Rayd Santana Ferreira"
    assert _refina("Miriam Denise Xavier – Relatora") == "Miriam Denise Xavier"
    assert _refina("Ana Carolina da Silva Barbosa -") == "Ana Carolina da Silva Barbosa"


def test_propaga_sobrenome_solto_mas_poupa_agente_publico():
    anon = Anonymizer(nomes=NomesFalso(["João Carlos da Silva", "Paulo Jakson da Silva Lucas"]))
    texto = ("O contribuinte João Carlos da Silva recorreu. Disse o Sr. Silva que João pagou. "
             "Relator Paulo Jakson da Silva Lucas votou.")
    out, _ = anon.anonymize(texto, permitidos=["PAULO JAKSON DA SILVA LUCAS"])
    assert out == ("O contribuinte [NOME] recorreu. Disse o Sr. [NOME] que [NOME] pagou. "
                   "Relator Paulo Jakson da Silva Lucas votou.")


def test_nao_propaga_palavra_comum_nem_sufixo():
    anon = Anonymizer(nomes=NomesFalso(["Wilsom de Moraes Filho"]))
    out, _ = anon.anonymize("Wilsom de Moraes Filho é o filho de Moraes; Filho do dono.")
    assert out.startswith("[NOME] é o filho de [NOME]") and "Filho do dono" in out


def test_oficial_por_titulo_nao_e_mascarado():
    from carf.privacy.ner import refinar
    from carf.privacy.rules import Span

    for t, esperado in [("Ministro Luís Roberto Barroso", "OFICIAL"), ("Conselheira Maria Souza", "OFICIAL"),
                        ("Sr. Maria Souza", "NOME"), ("Professora Maria Sylvia Zanella", "NOME")]:
        assert refinar(t, Span(0, len(t), "NOME")).label == esperado, t


def test_palavra_que_existe_em_minuscula_nao_e_nome():
    from carf.privacy.ner import palavras_minusculas, refinar
    from carf.privacy.rules import Span

    texto = "Ação Direta de Inconstitucionalidade. A inconstitucionalidade da ação direta foi reconhecida."
    sp = Span(0, len("Ação Direta"), "NOME")
    assert refinar(texto, sp, palavras_minusculas(texto)) is None
    assert refinar("Maria Souza decidiu.", Span(0, 11, "NOME"), palavras_minusculas("Maria Souza decidiu.")) is not None


def test_vocabulario_comum_do_corpus_descarta_titulos_em_caixa_alta():
    from carf.privacy.ner import refinar, vocabulario_comum
    from carf.privacy.rules import Span

    assert "despesas" in vocabulario_comum() and "silva" not in vocabulario_comum()
    for t in ("DESPESAS MÉDICAS", "Deduções Comprovadas", "Repercussão Geral"):
        assert refinar(t, Span(0, len(t), "NOME")) is None, t
    for t in ("Maria Souza", "JOÃO CARLOS PEREIRA", "Marcelo de Sousa Sateles"):
        assert refinar(t, Span(0, len(t), "NOME")) is not None, t


def test_nome_seguido_de_funcao_publica_e_oficial():
    from carf.privacy.ner import refinar
    from carf.privacy.rules import Span

    t = "Pedro Sousa Bispo  Presidente Redator"
    sp = refinar(t, Span(0, len(t), "NOME"))
    assert sp.label == "OFICIAL" and t[sp.start : sp.end] == "Pedro Sousa Bispo"
    t2 = "INTERESSE COMUM NA SITUAÇÃO QUE CONSTITUA"
    assert refinar(t2, Span(0, len(t2), "NOME")) is None
