"""Auditoria da base gravada: nenhum identificador detectável por regra pode restar."""

from collections import Counter

from .privacy import residual_pii

COLUNAS = ("ementa", "decisao", "conteudo")


def auditar(con, mascarar_cnpj=True) -> dict:
    achados: Counter = Counter()
    ids: dict[str, list[str]] = {}
    total = 0
    for id_, *textos in con.execute(f"SELECT id, {', '.join(COLUNAS)} FROM acordaos").fetchall():
        total += 1
        for col, t in zip(COLUNAS, textos):
            for rotulo in residual_pii(t, mascarar_cnpj):
                achados[rotulo] += 1
                ids.setdefault(rotulo, []).append(id_)
    return {"documentos": total, "residuos": dict(achados),
            "exemplos": {k: v[:5] for k, v in ids.items()}}
