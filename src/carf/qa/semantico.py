"""Busca léxica, semântica ou híbrida, com os mesmos filtros e a mesma citação."""

import re

from ..embeddings import Embedder, Indice, rrf
from . import consulta

MODOS = ("lexico", "semantico", "hibrido")
CAMPOS = ["id", "numero_decisao", "numero_processo", "turma", "camara", "secao", "relator",
          "dt_sessao", "ano", "ementa", "decisao", "nome_arquivo_pdf", "assunto", "tese_nulidade",
          "tese_prescricao"]


def _permitidos(con, filtros) -> set[str] | None:
    if not filtros:
        return None
    where, params = consulta._where(filtros)
    return {r[0] for r in con.execute(f"SELECT id FROM acordaos WHERE {where}", params).fetchall()}


def _linhas(con, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    qs = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT {', '.join(CAMPOS)} FROM acordaos WHERE id IN ({qs})", ids).fetchall()
    out = {}
    for row in rows:
        r = dict(zip(CAMPOS, row))
        r["citacao"] = consulta.citacao(r)
        out[r["id"]] = r
    return out


def _chave(ementa: str | None) -> str:
    """Ementas iguais salvo datas/números (recursos repetitivos) caem na mesma chave."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", (ementa or "").lower())).strip()[:300]


def agrupar_iguais(linhas: list[dict], limite: int) -> list[dict]:
    """Colapsa ementas repetidas: mantém a de melhor posição e conta as demais em `iguais`."""
    grupos: dict[str, dict] = {}
    for r in linhas:
        k = _chave(r.get("ementa"))
        if k in grupos:
            grupos[k]["iguais"] += 1
            grupos[k].setdefault("ids_iguais", []).append(r["id"])
        else:
            grupos[k] = {**r, "iguais": 1}
    return list(grupos.values())[:limite]


def buscar(con, consulta_txt: str, filtros=None, limite=10, modo="semantico",
           indice: Indice | None = None, embedder: Embedder | None = None, candidatos=100,
           agrupar=True) -> list[dict]:
    """`agrupar`: junta acórdãos de ementa idêntica (traz mais candidatos para completar o limite)."""
    if modo not in MODOS:
        raise ValueError(f"modo inválido: {modo}")
    n = limite * 6 if agrupar else limite
    if modo == "lexico":
        r = consulta.buscar(con, consulta_txt, filtros, n, qualquer=True)
        return agrupar_iguais(r, limite) if agrupar else r
    if indice is None or embedder is None:
        raise ValueError("busca semântica exige índice de vetores e embedder")
    vetor = embedder.codificar([consulta_txt], consulta=True)[0]
    sem = indice.buscar(vetor, candidatos, _permitidos(con, filtros))
    sim = dict(sem)
    listas = [[i for i, _ in sem]]
    if modo == "hibrido":
        lex = consulta.buscar(con, consulta_txt, filtros, candidatos, qualquer=True)
        listas.append([r["id"] for r in lex])
    ordem = [i for i, _ in rrf(listas)][:n]
    linhas = _linhas(con, ordem)
    out = []
    for i in ordem:
        if i in linhas:
            r = linhas[i]
            r["score"] = sim.get(i)
            out.append(r)
    return agrupar_iguais(out, limite) if agrupar else out
