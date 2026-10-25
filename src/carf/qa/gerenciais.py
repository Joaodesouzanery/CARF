"""Estatísticas sobre os dados abertos oficiais (Julgamentos e Estoque)."""

from pathlib import Path

import duckdb
import pandas as pd

from .. import config

DIM_JULG = {"ano", "turma", "tributo", "concentracao_tematica", "tipo_recurso", "desfecho",
            "votacao", "tipo_resultado"}
DIM_EST = {"tributo", "fase_processual", "instancia", "tipo_contribuinte", "concentracao_tematica",
           "questionamento1"}


def conectar(data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    raiz = (data_dir or config.DATA_DIR) / "gerenciais"
    con = duckdb.connect()
    for nome in ("julgamentos", "estoque"):
        arquivos = list((raiz / nome).glob("*.parquet"))
        if arquivos:
            glob = str(raiz / nome / "*.parquet").replace("'", "''")
            con.execute(
                f"CREATE VIEW {nome} AS SELECT * FROM read_parquet('{glob}', union_by_name=true)"
            )
    return con


def _filtros(filtros: dict | None, permitidos: set[str]) -> tuple[str, list]:
    cond, params = [], []
    for k, v in (filtros or {}).items():
        if k not in permitidos:
            raise ValueError(f"filtro inválido: {k}")
        cond.append(f"{k} = ?")
        params.append(v)
    return " AND ".join(cond) or "true", params


def desfecho_por(con, por: str, filtros=None, so_acordaos=True) -> pd.DataFrame:
    """Distribuição OFICIAL de resultados (não é heurística) por dimensão."""
    if por not in DIM_JULG - {"desfecho"}:
        raise ValueError(f"dimensão inválida: {por}")
    where, params = _filtros(filtros, DIM_JULG)
    extra = " AND tipo_resultado = 'Acórdão'" if so_acordaos else ""
    df = con.execute(
        f"""SELECT coalesce(CAST({por} AS VARCHAR), '(não informado)') AS {por}, desfecho, count(*) AS n
            FROM julgamentos
            WHERE {where}{extra} AND desfecho IS NOT NULL GROUP BY 1, 2""",
        params,
    ).df()
    if df.empty:
        return df
    tab = df.pivot_table(index=por, columns="desfecho", values="n", fill_value=0).reset_index()
    cols = [c for c in tab.columns if c != por]
    tab[cols] = tab[cols].astype(int)
    tab["total"] = tab[cols].sum(axis=1)
    return tab.sort_values("total", ascending=False)


def estoque_por(con, por: str, ano: int | None = None, mes: int | None = None, filtros=None):
    """Processos em estoque por dimensão, no último mês disponível se não informado."""
    if por not in DIM_EST:
        raise ValueError(f"dimensão inválida: {por}")
    where, params = _filtros(filtros, DIM_EST)
    if ano is None or mes is None:
        ano, mes = con.execute(
            "SELECT ano_referencia, mes_referencia FROM estoque "
            "ORDER BY 1 DESC, 2 DESC LIMIT 1"
        ).fetchone()
    df = con.execute(
        f"""SELECT {por} AS {por}, count(DISTINCT numero_processo) AS processos FROM estoque
            WHERE ano_referencia = ? AND mes_referencia = ? AND {where} GROUP BY 1 ORDER BY 2 DESC""",
        [ano, mes, *params],
    ).df()
    df.attrs["referencia"] = f"{ano}-{mes:02d}"
    return df
