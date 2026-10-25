"""Voto integral sob demanda: baixa do índice, anonimiza e guarda (só o texto limpo)."""

import re
from datetime import UTC, datetime

from .solr import FIELDS
from .sync import montar_linha


def baixar_texto(client, store, anon, id_: str, agora=None) -> dict | None:
    if not re.fullmatch(r"\d+", str(id_)):
        raise ValueError("id inválido (esperado só dígitos)")
    docs, _, _ = next(client.pages([f"id:{id_}"], fl=FIELDS, rows=1))
    if not docs:
        return None
    ts = agora or datetime.now(UTC).replace(tzinfo=None)
    linha = montar_linha(docs[0], anon, ts, leve=False)
    store.write([linha])  # mesma versão (dt_index), processado_em mais novo: vence na deduplicação
    return linha
