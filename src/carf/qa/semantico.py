"""Busca léxica, semântica ou híbrida, com os mesmos filtros e a mesma citação."""

from ..embeddings import Embedder, Indice, rrf
from . import consulta

MODOS = ("lexico", "semantico", "hibrido")
CAMPOS = ["id", "numero_decisao", "numero_processo", "turma", "camara", "secao", "relator",
          "dt_sessao", "ano", "ementa", "nome_arquivo_pdf"]


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


def buscar(con, consulta_txt: str, filtros=None, limite=10, modo="hibrido",
           indice: Indice | None = None, embedder: Embedder | None = None, candidatos=100) -> list[dict]:
    if modo not in MODOS:
        raise ValueError(f"modo inválido: {modo}")
    if modo == "lexico":
        return consulta.buscar(con, consulta_txt, filtros, limite, qualquer=True)
    if indice is None or embedder is None:
        raise ValueError("busca semântica exige índice de vetores e embedder")
    vetor = embedder.codificar([consulta_txt], consulta=True)[0]
    sem = indice.buscar(vetor, candidatos, _permitidos(con, filtros))
    sim = dict(sem)
    listas = [[i for i, _ in sem]]
    if modo == "hibrido":
        lex = consulta.buscar(con, consulta_txt, filtros, candidatos, qualquer=True)
        listas.append([r["id"] for r in lex])
    ordem = [i for i, _ in rrf(listas)][:limite]
    linhas = _linhas(con, ordem)
    out = []
    for i in ordem:
        if i in linhas:
            r = linhas[i]
            r["score"] = sim.get(i)
            out.append(r)
    return out
