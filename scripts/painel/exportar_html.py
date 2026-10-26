"""Gera UM arquivo .html com a jurisprudência embutida (abre offline, sem token), para entregar um recorte.

Uso: python scripts/painel/exportar_html.py DATA_DIR SAIDA.html [--ano-min 2018 --ano-max 2026]
        [--assunto "classificação de mercadorias"] [--nulidade acolhida] [--prescricao rejeitada]
        [--termo "cerceamento"] [--limite-mb 12]
"""

import argparse
import base64
import gzip
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import exportar

from carf.qa import consulta
from carf.store import Store

PAGINA = Path(__file__).parent / "painel.html"


def montar(data_dir, saida, ano_min=2018, ano_max=9999, assunto=None, nulidade=None, prescricao=None,
           termo=None, limite_mb=12.0, compactar=False, revisao=None, revisao_csv=None, prontas=None) -> dict:
    filtro, params = "", []
    if assunto:
        filtro += " AND assunto_norm LIKE ?"
        params.append(f"%{consulta._norm(assunto)}%")
    for col, v in (("tese_nulidade", nulidade), ("tese_prescricao", prescricao)):
        if v:
            filtro += f" AND {col} = ?"
            params.append(v.upper())
    for t in (consulta._norm(x) for x in (termo or "").split() if len(x) > 2):
        filtro += " AND strip_accents(lower(ementa)) LIKE ?"
        params.append(f"%{t}%")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        meta = exportar.exportar_anos(Store(data_dir).connect(), tmp, ano_min, ano_max, filtro, params)
        exportar.exportar_oficial(Path(data_dir), tmp)
        if revisao:
            exportar.exportar_revisao(Path(revisao), tmp, revisao_csv)
        dados = {"meta.json": json.loads((tmp / "meta.json").read_text()),
                 "oficial.json": json.loads((tmp / "oficial.json").read_text())}
        if (tmp / "revisao.json").exists():
            dados["revisao.json"] = json.loads((tmp / "revisao.json").read_text())
        if prontas and Path(prontas).exists():
            dados["prontas.json"] = json.loads(Path(prontas).read_text())
        gz = {}
        for a in meta["anos"]:
            bruto = (tmp / "dados" / f"ano-{a}.json").read_bytes()
            if compactar:  # um ano vira texto base64 do gzip; a página descomprime só quando o ano é aberto
                gz[f"dados/ano-{a}.json"] = base64.b64encode(gzip.compress(bruto, 9)).decode()
            else:
                dados[f"dados/ano-{a}.json"] = json.loads(bruto)
    blob = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    blob_gz = json.dumps(gz, separators=(",", ":"))
    html = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
            f"<script>window.__DADOS={blob};window.__GZ={blob_gz};</script>{PAGINA.read_text()}</body></html>")
    mb = len(html.encode()) / 1e6
    if mb > limite_mb:
        raise SystemExit(f"{mb:.1f} MB passa do limite de {limite_mb} MB; estreite anos ou filtros")
    Path(saida).write_text(html)
    return {"acordaos": sum(meta["n"].values()), "mb": round(mb, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("saida")
    ap.add_argument("--ano-min", type=int, default=2018)
    ap.add_argument("--ano-max", type=int, default=9999)
    ap.add_argument("--assunto")
    ap.add_argument("--nulidade", choices=["acolhida", "rejeitada", "indefinida"])
    ap.add_argument("--prescricao", choices=["acolhida", "rejeitada", "indefinida"])
    ap.add_argument("--termo")
    ap.add_argument("--limite-mb", type=float, default=12.0)
    ap.add_argument("--compactar", action="store_true", help="gzip por ano: cabem todos os acórdãos em um arquivo só")
    ap.add_argument("--revisao", help="amostra .md da revisão LGPD")
    ap.add_argument("--revisao-csv", help="CSV marcado da revisão")
    ap.add_argument("--prontas", help="prontas.json gerado por prontas.py")
    a = ap.parse_args()
    r = montar(a.data_dir, a.saida, a.ano_min, a.ano_max, a.assunto, a.nulidade, a.prescricao, a.termo, a.limite_mb,
               a.compactar, a.revisao, a.revisao_csv, a.prontas)
    print(f"ok: {r['acordaos']} acórdãos, {r['mb']} MB -> {a.saida}")


if __name__ == "__main__":
    main()
