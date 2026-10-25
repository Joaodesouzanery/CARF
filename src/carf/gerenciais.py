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


def urls_candidatas(rec: Recurso) -> list[str]:
    """O mesmo arquivo costuma existir em www.gov.br (nome em minúsculas) e no host antigo."""
    novo = BASE + rec.arquivo.lower()
    return [novo] if rec.url == novo else [novo, rec.url]


def baixar(rec: Recurso, destino: Path, estado: dict, session=None) -> dict:
    """Baixa só se mudou (ETag/Last-Modified). Devolve {'status': ..., 'arquivo': Path|None}."""
    session = session or requests.Session()
    destino.mkdir(parents=True, exist_ok=True)
    meta = estado.get(rec.url, {})
    alvo = destino / rec.arquivo
    headers = {"User-Agent": config.USER_AGENT}
    if meta and alvo.exists():
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
    resp, falha = None, "inexistente"
    for url in urls_candidatas(rec):
        try:
            r = session.get(url, headers=headers, timeout=300, allow_redirects=True)
        except requests.RequestException as exc:
            falha = "inacessivel"
            erro = type(exc).__name__
            continue
        if r.status_code in (200, 304):
            resp = r
            break
        if r.status_code != 404:
            falha = f"http_{r.status_code}"
    if resp is None:
        out = {"status": falha, "arquivo": None}
        if falha == "inacessivel":
            out["erro"] = erro
        return out
    if resp.status_code == 304:
        return {"status": "inalterado", "arquivo": alvo}
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


TEXTOS_LIVRES = ("texto_ementa", "info_geral")


def ingerir_julgamentos(zip_path: Path, saida: Path, anon=None, com_texto: bool = False) -> Path:
    """Por minimização, os textos livres (ementa, decisão) NÃO são guardados por padrão: a ementa do
    acórdão já vem do índice e nada aqui depende delas. Com `com_texto`, passam pelo anonimizador."""
    df = _ler_csv(zip_path)
    df["data_sessao"] = pd.to_datetime(df["data_sessao"], errors="coerce").dt.date
    df["ano"] = pd.to_datetime(df["data_sessao"], errors="coerce").dt.year.astype("Int32")
    df["desfecho"] = df["resultado_julgamento"].map(desfecho)
    df["tipo_recurso"] = df["resultado_julgamento"].map(tipo_recurso)
    if not com_texto:
        df = df.drop(columns=[c for c in TEXTOS_LIVRES if c in df])
    elif anon is not None:
        for col in TEXTOS_LIVRES:
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


def _ingerir_job(args):
    """Roda em processo próprio (carga paralela): cada processo cria seu anonimizador."""
    zip_path, conjunto, pasta, sem_ner, manter_cnpj, anonimizar, com_texto = args
    if conjunto == "estoque":
        return ingerir_estoque(Path(zip_path), Path(pasta)).name
    anon = None
    if anonimizar and com_texto:
        from . import anonimizador

        anon = anonimizador.criar(sem_ner, manter_cnpj)
    return ingerir_julgamentos(Path(zip_path), Path(pasta), anon, com_texto).name


def _ingerir_lote(jobs, workers, anon, sem_ner, manter_cnpj, log, com_texto=False):
    """jobs: [(zip, conjunto, pasta)]. Em paralelo quando workers > 1 (o NER é o gargalo)."""
    if workers > 1 and len(jobs) > 1:
        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context

        args = [(str(z), c, str(p), sem_ner, manter_cnpj, anon is not None, com_texto) for z, c, p in jobs]
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
            for (z, _, _), nome in zip(jobs, ex.map(_ingerir_job, args), strict=True):
                log(f"{Path(z).name} -> {nome}")
        return
    for z, c, p in jobs:
        alvo = ingerir_julgamentos(z, p, anon, com_texto) if c == "julgamentos" else ingerir_estoque(z, p)
        log(f"{Path(z).name} -> {alvo.name}")


def atualizar(data_dir: Path, anon=None, session=None, incluir_candidatos=True, log=print,
              workers: int = 1, sem_ner: bool = False, manter_cnpj: bool = False,
              com_texto: bool = False) -> dict:
    """Baixa o que mudou e reingere. Estado em data/gerenciais/estado.json."""
    raiz = data_dir / "gerenciais"
    est_path = raiz / "estado.json"
    estado = json.loads(est_path.read_text()) if est_path.exists() else {}
    recursos = [r for r in carregar_recursos() if r.formato.upper() == "CSV"]
    if incluir_candidatos:
        recursos += candidatos_novos(recursos)
    resumo: dict = {"novos": [], "alterados": [], "inalterados": 0, "inacessiveis": [], "ausentes": 0}
    jobs = []
    for rec in recursos:
        r = baixar(rec, raiz / "raw", estado, session)
        st = r["status"]
        if st in ("novo", "alterado"):
            jobs.append((r["arquivo"], rec.conjunto, raiz / rec.conjunto))
            resumo["novos" if st == "novo" else "alterados"].append(rec.arquivo)
        elif st == "inalterado":
            resumo["inalterados"] += 1
        elif st == "inacessivel":
            resumo["inacessiveis"].append(rec.arquivo)
        else:
            resumo["ausentes"] += 1
        raiz.mkdir(parents=True, exist_ok=True)
        est_path.write_text(json.dumps(estado, indent=1, ensure_ascii=False))  # progresso salvo
    _ingerir_lote(jobs, workers, anon, sem_ner, manter_cnpj, log, com_texto)
    return resumo


def reingerir(data_dir: Path, anon=None, log=print, com_texto: bool = False) -> list[str]:
    """Reprocessa os ZIPs já baixados (sem rede), por exemplo após melhorar a anonimização."""
    raiz = data_dir / "gerenciais"
    feitos = []
    for z in sorted((raiz / "raw").glob("*.zip")):
        if z.name.startswith("carf_julgamentos_"):
            alvo = ingerir_julgamentos(z, raiz / "julgamentos", anon, com_texto)
        elif "estoque" in z.name.lower():
            alvo = ingerir_estoque(z, raiz / "estoque")
        else:
            continue
        log(f"{z.name} -> {alvo.name}")
        feitos.append(z.name)
    return feitos
