"""Armazenamento em Parquet particionado por ano, consultado via DuckDB."""

import uuid
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("numero_processo", pa.string()),
        ("numero_decisao", pa.string()),
        ("relator", pa.string()),
        ("secao", pa.string()),
        ("camara", pa.string()),
        ("turma", pa.string()),
        ("dt_sessao", pa.date32()),
        ("ano", pa.int32()),
        ("ementa", pa.string()),
        ("decisao", pa.string()),
        ("conteudo", pa.string()),
        ("tem_texto", pa.bool_()),
        ("nome_arquivo_pdf", pa.string()),
        ("dt_index", pa.timestamp("us")),
        ("dt_atualizacao", pa.timestamp("us")),
        ("qualidade", pa.string()),
        ("pii_mascarado", pa.int32()),
        ("processado_em", pa.timestamp("us")),
    ]
)


FACETS_COLS = ["assunto", "assunto_norm", "teses", "tese_nulidade", "tese_prescricao", "tributo", "desfecho_oficial", "votacao", "tipo_recurso", "sumulas"]


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.dir = self.root / "acordaos"
        self.facets_path = self.root / "facets.parquet"  # matéria/teses derivadas (carf enriquecer)

    def _particao(self, ano) -> Path:
        return self.dir / f"ano={ano if ano is not None else 'desconhecido'}"

    def write(self, rows: list[dict]) -> int:
        por_ano: dict = {}
        for r in rows:
            por_ano.setdefault(r.get("ano"), []).append(r)
        for ano, grupo in por_ano.items():
            d = self._particao(ano)
            d.mkdir(parents=True, exist_ok=True)
            tabela = pa.Table.from_pylist(grupo, schema=SCHEMA)
            tmp = d / f".part-{uuid.uuid4().hex}.tmp"
            pq.write_table(tabela, tmp, compression="zstd")
            tmp.rename(d / f"part-{uuid.uuid4().hex}.parquet")
        return len(rows)

    def _arquivos(self) -> list[Path]:
        return sorted(self.dir.glob("ano=*/part-*.parquet")) if self.dir.exists() else []

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Conexão com a view `acordaos` já deduplicada por id (vale a versão mais recente)."""
        con = duckdb.connect()
        if self._arquivos():
            glob = str(self.dir / "ano=*" / "part-*.parquet").replace("'", "''")
            con.execute(
                f"""CREATE VIEW acordaos_base AS SELECT * EXCLUDE (rn) REPLACE (
                      CASE WHEN regexp_matches(relator, '\\d{{6,}}') THEN NULL ELSE relator END AS relator) FROM (
                      SELECT *, row_number() OVER (
                        PARTITION BY id
                        ORDER BY dt_index DESC NULLS LAST, processado_em DESC) AS rn
                      FROM read_parquet('{glob}', union_by_name=true, hive_partitioning=false)) WHERE rn = 1"""
            )
        else:
            cols = ", ".join(f"NULL::{_duck(f.type)} AS {f.name}" for f in SCHEMA)
            con.execute(f"CREATE VIEW acordaos_base AS SELECT {cols} WHERE false")
        if self.facets_path.exists():
            fp = str(self.facets_path).replace("'", "''")
            tem = set(pq.read_schema(self.facets_path).names)  # facets antigos podem não ter colunas novas
            sel = ", ".join(f"f.{c}" if c in tem else f"NULL::VARCHAR AS {c}" for c in FACETS_COLS)
            con.execute(f"CREATE VIEW acordaos AS SELECT b.*, {sel} FROM acordaos_base b "
                        f"LEFT JOIN read_parquet('{fp}') f USING (id)")
        else:
            nulos = ", ".join(f"NULL::VARCHAR AS {c}" for c in FACETS_COLS)
            con.execute(f"CREATE VIEW acordaos AS SELECT *, {nulos} FROM acordaos_base")
        return con

    def existing(self, ids: list[str]) -> dict[str, object]:
        """id -> dt_index já gravado, para os ids pedidos."""
        if not ids or not self._arquivos():
            return {}
        qs = ",".join("?" * len(ids))
        rows = self.connect().execute(f"SELECT id, dt_index FROM acordaos_base WHERE id IN ({qs})", ids)
        return dict(rows.fetchall())

    def compact(self) -> int:
        """Reescreve cada partição sem versões antigas; devolve arquivos removidos."""
        con = self.connect()
        removidos = 0
        for d in sorted(p for p in self.dir.glob("ano=*") if p.is_dir()):
            antigos = sorted(d.glob("part-*.parquet"))
            if len(antigos) < 2:
                continue
            ano = d.name.split("=", 1)[1]
            filtro = "ano IS NULL" if ano == "desconhecido" else f"ano = {int(ano)}"
            tmp = d / f".compact-{uuid.uuid4().hex}.tmp"
            con.execute(f"COPY (SELECT * FROM acordaos_base WHERE {filtro}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
            for f in antigos:
                f.unlink()
            tmp.rename(d / f"part-{uuid.uuid4().hex}.parquet")
            removidos += len(antigos)
        return removidos


def _duck(t) -> str:
    return {
        "string": "VARCHAR",
        "date32[day]": "DATE",
        "int32": "INTEGER",
        "timestamp[us]": "TIMESTAMP",
        "bool": "BOOLEAN",
    }[str(t)]
