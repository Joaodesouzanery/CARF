"""Detecção de atualizações: índice de acórdãos (dt_index_tdt) e publicações gerenciais do CARF."""

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import requests

from . import config
from .sync import State, filtros_base

_LINK = re.compile(
    r"""href=["']([^"']*dados-abertos[^"']*\.(?:pdf|csv|xlsx|zip))["']""", re.IGNORECASE
)
_DATA_PDF = re.compile(r"Atualiza[çc][ãa]o da apresenta[çc][ãa]o:\s*(\d{2}/\d{2}/\d{4})")


def verificar_indice(client, state: State) -> dict:
    """Consulta barata: há algo indexado depois da última sincronização?"""
    d = state.data
    base = filtros_base((d.get("filters") or {}).get("ano_min"))
    remoto = client.summary(base)
    ultimo = d.get("last_dt_index")
    pendentes = None
    if ultimo:
        pendentes = client.summary(base + [f"dt_index_tdt:[{ultimo} TO *]"])["num_found"]
    return {
        "remoto_max_dt_index": remoto["max_dt_index"],
        "remoto_total": remoto["num_found"],
        "ultimo_sincronizado": ultimo,
        "pendentes": pendentes,
        "ha_atualizacao": bool(
            remoto["max_dt_index"] and (not ultimo or remoto["max_dt_index"] > ultimo)
        ),
    }


def data_do_pdf(pdf: Path) -> str | None:
    """Lê 'Atualização da apresentação: dd/mm/aaaa' do PDF (requer pdftotext)."""
    if not shutil.which("pdftotext"):
        return None
    texto = subprocess.run(
        ["pdftotext", "-layout", "-l", "2", str(pdf), "-"],
        capture_output=True, text=True, check=False,
    ).stdout
    m = _DATA_PDF.search(texto)
    return m.group(1) if m else None


def vigiar_paginas(state: State, data_dir: Path, session=None, baixar=True) -> dict:
    """Detecta links novos e PDFs alterados nas páginas de dados abertos do CARF."""
    session = session or requests.Session()
    headers = {"User-Agent": config.USER_AGENT}
    vistos = state.data.setdefault("gerenciais", {})
    novos, alterados = [], []
    for pagina in config.CARF_PAGES:
        html = session.get(pagina, headers=headers, timeout=60).text
        for href in sorted(set(_LINK.findall(html))):
            url = requests.compat.urljoin(pagina, href)
            registro = vistos.get(url)
            if not baixar:
                if registro is None:
                    novos.append(url)
                continue
            conteudo = session.get(url, headers=headers, timeout=180).content
            sha = hashlib.sha256(conteudo).hexdigest()
            if registro and registro["sha256"] == sha:
                continue
            destino = data_dir / "gerenciais" / url.rsplit("/", 1)[-1]
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(conteudo)
            vistos[url] = {"sha256": sha, "bytes": len(conteudo),
                           "atualizacao": data_do_pdf(destino), "arquivo": str(destino)}
            (alterados if registro else novos).append(url)
    state.save()
    return {"novos": novos, "alterados": alterados}
