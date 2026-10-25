"""Conjuntos "CARF - Julgamentos de processos" e "CARF - Estoque de processos" (dados abertos).

Os arquivos são downloads públicos; não há token. A lista de recursos vem de uma semente
(`recursos_seed.json`, capturada da página pública do conjunto) e é ampliada por padrões de URL.
"""

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from . import config

SEED = Path(__file__).with_name("recursos_seed.json")
BASE = "https://www.gov.br/carf/pt-br/acesso-a-informacao/dados-abertos/dispe/"

DESFECHOS = [
    ("NAO_CONHECIDO", re.compile(r"n[ãa]o\s+conhecid")),
    ("PROVIDO_PARCIAL", re.compile(r"provid[oa]\s+em\s+parte|acolhid[oa]s?\s+em\s+parte")),
    ("ACOLHIDO", re.compile(r"acolhid")),
    ("REJEITADO", re.compile(r"rejeitad")),
    ("NEGADO", re.compile(r"negad")),
    ("PROVIDO", re.compile(r"provid")),
]
RECURSOS = [
    ("EMBARGOS", re.compile(r"embargos")),
    ("ESPECIAL_PROCURADORIA", re.compile(r"especial\s+da\s+procuradoria")),
    ("ESPECIAL_CONTRIBUINTE", re.compile(r"especial\s+do\s+contribuinte")),
    ("OFICIO", re.compile(r"de\s+of[ií]cio")),
    ("VOLUNTARIO", re.compile(r"volunt[áa]rio")),
]


@dataclass(frozen=True)
class Recurso:
    conjunto: str
    nome: str
    formato: str
    url: str
    arquivo_atualizado: str = ""

    @property
    def arquivo(self) -> str:
        return self.url.split("/@@download/")[0].rsplit("/", 1)[-1]


def carregar_recursos() -> list[Recurso]:
    dados = json.loads(SEED.read_text(encoding="utf-8"))["recursos"]
    return [Recurso(**r) for r in dados]


def candidatos_novos(conhecidos: list[Recurso], hoje: date | None = None) -> list[Recurso]:
    """URLs previsíveis ainda não listadas: julgamentos do próximo ano e semestres de estoque."""
    hoje = hoje or date.today()
    vistos = {r.arquivo.lower() for r in conhecidos}
    cand = []
    for ano in range(hoje.year - 1, hoje.year + 1):
        cand.append(("julgamentos", f"carf_julgamentos_{ano}.zip"))
        for sem in (1, 2):
            cand.append(("estoque", f"carf_estoque_{ano}_{sem}semestre.zip"))
        cand.append(("estoque", f"carf_estoque_{ano}_2semestreparcial.zip"))
    return [
        Recurso(c, f"(candidato) {a}", "CSV", BASE + a)
        for c, a in cand
        if a.lower() not in vistos
    ]


def desfecho(resultado: str | None) -> str | None:
    if not isinstance(resultado, str) or not resultado:
        return None
    t = resultado.casefold()
    for nome, rx in DESFECHOS:
        if rx.search(t):
            return nome
    return "OUTRO"


def tipo_recurso(resultado: str | None) -> str | None:
    if not isinstance(resultado, str) or not resultado:
        return None
    t = resultado.casefold()
    for nome, rx in RECURSOS:
        if rx.search(t):
            return nome
    return "OUTRO"


def baixar(rec: Recurso, destino: Path, estado: dict, session=None) -> dict:
    """Baixa só se mudou (ETag/Last-Modified). Devolve {'status': ..., 'arquivo': Path|None}."""
    session = session or requests.Session()
    destino.mkdir(parents=True, exist_ok=True)
    meta = estado.get(rec.url, {})
    headers = {"User-Agent": config.USER_AGENT}
    if meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]
    alvo = destino / rec.arquivo
    if not (meta and alvo.exists()):
        headers.pop("If-None-Match", None)
        headers.pop("If-Modified-Since", None)
    try:
        resp = session.get(rec.url, headers=headers, timeout=300, allow_redirects=True)
    except requests.RequestException as exc:
        return {"status": "inacessivel", "erro": type(exc).__name__, "arquivo": None}
    if resp.status_code == 304:
        return {"status": "inalterado", "arquivo": alvo}
    if resp.status_code == 404:
        return {"status": "inexistente", "arquivo": None}
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "arquivo": None}
    sha = hashlib.sha256(resp.content).hexdigest()
    if meta.get("sha256") == sha and alvo.exists():
        return {"status": "inalterado", "arquivo": alvo}
    alvo.write_bytes(resp.content)
    estado[rec.url] = {
        "sha256": sha,
        "bytes": len(resp.content),
        "etag": resp.headers.get("ETag"),
        "last_modified": resp.headers.get("Last-Modified"),
        "arquivo": str(alvo),
    }
    return {"status": "novo" if not meta else "alterado", "arquivo": alvo}


def _ler_csv(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(nome) as f:
            return pd.read_csv(io.TextIOWrapper(f, encoding="utf-8-sig"), dtype=str)


def ingerir_julgamentos(zip_path: Path, saida: Path, anon=None) -> Path:
    df = _ler_csv(zip_path)
    df["data_sessao"] = pd.to_datetime(df["data_sessao"], errors="coerce").dt.date
    df["ano"] = pd.to_datetime(df["data_sessao"], errors="coerce").dt.year.astype("Int32")
    df["desfecho"] = df["resultado_julgamento"].map(desfecho)
    df["tipo_recurso"] = df["resultado_julgamento"].map(tipo_recurso)
    if anon is not None:
        for col in ("texto_ementa", "info_geral"):
            df[col] = [anon.anonymize(v)[0] if isinstance(v, str) else v for v in df[col]]
    saida.mkdir(parents=True, exist_ok=True)
    anos = df["ano"].dropna().unique()
    alvo = saida / f"julgamentos_{int(anos[0]) if len(anos) == 1 else zip_path.stem}.parquet"
    df.to_parquet(alvo, index=False, compression="zstd")
    return alvo


def ingerir_estoque(zip_path: Path, saida: Path) -> Path:
    df = _ler_csv(zip_path)
    for col in ("ano_referencia", "mes_referencia"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int32")
    for col in ("data_protocolo", "data_entrada_carf"):
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    saida.mkdir(parents=True, exist_ok=True)
    alvo = saida / f"{zip_path.stem}.parquet"
    df.to_parquet(alvo, index=False, compression="zstd")
    return alvo


def atualizar(data_dir: Path, anon=None, session=None, incluir_candidatos=True, log=print) -> dict:
    """Baixa o que mudou e reingere. Estado em data/gerenciais/estado.json."""
    raiz = data_dir / "gerenciais"
    est_path = raiz / "estado.json"
    estado = json.loads(est_path.read_text()) if est_path.exists() else {}
    recursos = [r for r in carregar_recursos() if r.formato.upper() == "CSV"]
    if incluir_candidatos:
        recursos += candidatos_novos(recursos)
    resumo: dict = {"novos": [], "alterados": [], "inalterados": 0, "inacessiveis": [], "ausentes": 0}
    for rec in recursos:
        r = baixar(rec, raiz / "raw", estado, session)
        st = r["status"]
        if st in ("novo", "alterado"):
            ingestor = ingerir_julgamentos if rec.conjunto == "julgamentos" else ingerir_estoque
            pasta = raiz / rec.conjunto
            alvo = (
                ingestor(r["arquivo"], pasta, anon)
                if rec.conjunto == "julgamentos"
                else ingestor(r["arquivo"], pasta)
            )
            resumo["novos" if st == "novo" else "alterados"].append(rec.arquivo)
            log(f"[{rec.conjunto}] {rec.arquivo} -> {alvo.name}")
        elif st == "inalterado":
            resumo["inalterados"] += 1
        elif st == "inacessivel":
            resumo["inacessiveis"].append(rec.arquivo)
        else:
            resumo["ausentes"] += 1
    raiz.mkdir(parents=True, exist_ok=True)
    est_path.write_text(json.dumps(estado, indent=1, ensure_ascii=False))
    return resumo
