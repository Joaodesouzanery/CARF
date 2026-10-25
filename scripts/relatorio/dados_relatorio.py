"""Prepara dados.json e grafico.png para o Boletim de Jurisprudência (scripts/relatorio/gerar.js).

Uso: python scripts/relatorio/dados_relatorio.py DATA_DIR SAIDA_DIR --tributos PIS,COFINS \
        --inicio 2026-07-01 --fim 2026-09-30 --termo insumo [--ano-ini 2018 --ano-fim 2025]
Resultados por ano/colegiado vêm do dado aberto OFICIAL; as novidades do período usam o índice de
acórdãos e a leitura automática (indicativa) da decisão.
"""

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import matplotlib
import pandas as pd

from carf.qa import consulta
from carf.qa import gerenciais as qg
from carf.store import Store

matplotlib.use("Agg")
import matplotlib.pyplot as plt

LINK = "https://acordaos.economia.gov.br/acordaos2/pdfs/processados/"


def turma_bonita(t: str) -> str:
    m = re.match(r"(\d+)ª (TO|TE|TURMA)-(?:(\d+)ªCÂMARA-)?(\d+)ªSEÇÃO", t)
    if "CSRF" in t:
        return f"{t.split('ª')[0]}ª Turma da Câmara Superior (CSRF)"
    if m:
        tipo = {"TO": "Turma Ordinária", "TE": "Turma Extraordinária"}.get(m.group(2), "Turma")
        cam = f" / {m.group(3)}ª Câmara" if m.group(3) else ""
        return f"{m.group(1)}ª {tipo}{cam} / {m.group(4)}ª Seção"
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("saida")
    ap.add_argument("--tributos", default="PIS,COFINS")
    ap.add_argument("--inicio", default="2026-07-01")
    ap.add_argument("--fim", default="2026-09-30")
    ap.add_argument("--termo", default="insumo")
    ap.add_argument("--ano-ini", type=int, default=2018)
    ap.add_argument("--ano-fim", type=int, default=2025)
    a = ap.parse_args()
    raiz, saida = Path(a.data_dir), Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    trib = [t.strip().upper() for t in a.tributos.split(",")]
    lista = ",".join(f"'{t}'" for t in trib)
    con, g = Store(raiz).connect(), qg.conectar(raiz)
    out = {"tributos": trib}

    df = g.execute(f"""SELECT ano, desfecho, count(*) n FROM julgamentos WHERE tipo_resultado='Acórdão'
                       AND desfecho IS NOT NULL AND tributo IN ({lista}) AND ano BETWEEN ? AND ? GROUP BY 1,2""",
                   [a.ano_ini, a.ano_fim]).df()
    t = df.pivot_table(index="ano", columns="desfecho", values="n", fill_value=0)
    t["total"] = t.sum(axis=1)
    out["ano"] = [{"ano": int(i), "total": int(r.total),
                   "prov": round(float((r.get("PROVIDO", 0) + r.get("PROVIDO_PARCIAL", 0)) / r.total), 4),
                   "neg": round(float(r.get("NEGADO", 0) / r.total), 4),
                   "nc": round(float(r.get("NAO_CONHECIDO", 0) / r.total), 4)} for i, r in t.iterrows()]

    d = g.execute(f"""SELECT turma, desfecho, count(*) n FROM julgamentos WHERE tipo_resultado='Acórdão'
                      AND desfecho IS NOT NULL AND tributo IN ({lista}) AND ano=? GROUP BY 1,2""", [a.ano_fim]).df()
    tt = d.pivot_table(index="turma", columns="desfecho", values="n", fill_value=0)
    tt["total"] = tt.sum(axis=1)
    tt = tt[tt.total >= 30].sort_values("total", ascending=False).head(6)
    out["turma"] = [{"turma": k, "turma_fmt": turma_bonita(k), "total": int(r.total),
                     "prov": round(float((r.get("PROVIDO", 0) + r.get("PROVIDO_PARCIAL", 0)) / r.total), 4),
                     "neg": round(float(r.get("NEGADO", 0) / r.total), 4)} for k, r in tt.iterrows()]

    ano, mes = g.execute("SELECT ano_referencia, mes_referencia FROM estoque ORDER BY 1 DESC, 2 DESC LIMIT 1").fetchone()
    e = g.execute(f"""SELECT DISTINCT ON (numero_processo) numero_processo, fase_processual, data_entrada_carf FROM estoque
                      WHERE ano_referencia=? AND mes_referencia=? AND tributo IN ({lista})""", [ano, mes]).df()
    dias = (pd.to_datetime(dt.date(ano, mes, 28)) - pd.to_datetime(e.data_entrada_carf)).dt.days
    total_geral = g.execute("SELECT count(DISTINCT numero_processo) FROM estoque WHERE ano_referencia=? AND mes_referencia=?",
                            [ano, mes]).fetchone()[0]
    out["estoque"] = {"ref": f"{mes:02d}/{ano}", "pis_cofins": len(e), "total_geral": int(total_geral),
                      "mediana_dias": int(dias.median()), "p90_dias": int(dias.quantile(0.9)),
                      "fases": e.fase_processual.value_counts().head(5).to_dict()}

    filtro = " OR ".join(f"lower(ementa) LIKE '%{t.lower()}%'" for t in trib)
    q = con.execute(f"""SELECT id,numero_decisao,numero_processo,turma,relator,dt_sessao,ementa,decisao,nome_arquivo_pdf FROM acordaos
                        WHERE dt_sessao BETWEEN DATE '{a.inicio}' AND DATE '{a.fim}' AND ({filtro})""").df()
    q["res"] = q.decisao.map(consulta.classificar_resultado)
    total_per = con.execute(f"SELECT count(*) FROM acordaos WHERE dt_sessao BETWEEN DATE '{a.inicio}' AND DATE '{a.fim}'").fetchone()[0]
    out["q3"] = {"n": len(q), "res": q.res.value_counts().to_dict(), "total_periodo": int(total_per)}
    sel = q[q.ementa.str.lower().str.contains(a.termo.lower())].sort_values("dt_sessao", ascending=False).head(5)
    out["novidades"] = [{"cit": f"Acórdão {r.numero_decisao}", "proc": r.numero_processo, "turma": turma_bonita(r.turma) if r.turma else "",
                         "data": r.dt_sessao.strftime("%d/%m/%Y"), "res": r.res, "ementa": " ".join(r.ementa.split())[:330],
                         "link": LINK + str(r.nome_arquivo_pdf)} for r in sel.itertuples()]
    (saida / "dados.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    anos = [str(r["ano"]) for r in out["ano"]]
    _, ax = plt.subplots(figsize=(7.2, 3.2), dpi=200)
    ax.plot(anos, [r["prov"] * 100 for r in out["ano"]], marker="o", color="#1F3864", lw=2.2, label="Provido (total ou parcial)")
    ax.plot(anos, [r["neg"] * 100 for r in out["ano"]], marker="o", color="#C0504D", lw=2.2, label="Negado")
    ax.plot(anos, [r["nc"] * 100 for r in out["ano"]], marker="o", color="#7F7F7F", lw=1.6, ls="--", label="Não conhecido")
    for r, x in zip(out["ano"], anos, strict=True):
        ax.annotate(f'{r["prov"] * 100:.0f}%', (x, r["prov"] * 100), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8, color="#1F3864")
    ax.set_ylabel("% dos recursos julgados")
    ax.set_ylim(0, 80)
    ax.grid(axis="y", alpha=0.3)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.14))
    plt.tight_layout()
    plt.savefig(saida / "grafico.png")
    print(f"ok: {saida}")


if __name__ == "__main__":
    main()
