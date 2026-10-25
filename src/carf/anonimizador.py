"""Fábrica do anonimizador usado pela CLI e pelos processos da carga paralela."""

from .privacy import Anonymizer
from .privacy.ner import NomesPorContexto, SpacyNomes


def criar(sem_ner: bool = False, manter_cnpj: bool = False) -> Anonymizer:
    try:
        nomes = SpacyNomes()
    except Exception as exc:
        if not sem_ner:
            raise RuntimeError(
                f"NER indisponível ({exc}). Instale `.[ner]` ou use --sem-ner para a reserva por "
                "contexto (recall muito menor; não use em produção)."
            ) from exc
        nomes = NomesPorContexto()
    return Anonymizer(nomes=nomes, mascarar_cnpj=not manter_cnpj)
