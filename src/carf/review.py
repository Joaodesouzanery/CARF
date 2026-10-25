"""Revisão humana da anonimização: amostra para revisar, pontuação e taxa de vazamento."""

import csv
import math
import random
import re
from datetime import date
from pathlib import Path

from . import auditoria

COLUNAS = ["id", "citacao", "palavras", "total_mascaras", "qtd_nomes_remanescentes",
           "qtd_identificadores_remanescentes", "qtd_mascaras_indevidas", "observacoes"]
_MASCARA = re.compile(r"\[(?:NOME|CPF|CNPJ|EMAIL|TELEFONE|CEP|RG|TITULO_ELEITOR|CNH|PIS|CONTA_BANCARIA|PLACA)\]")


def _texto(r: dict) -> str:
    return "\n".join(t for t in (r.get("ementa"), r.get("decisao"), r.get("conteudo")) if t)


def _trechos(texto: str, regex: re.Pattern, n: int, raio: int) -> list[str]:
    out = []
    for m in regex.finditer(texto):
        out.append(texto[max(0, m.start() - raio) : m.end() + raio].replace("\n", " "))
        if len(out) >= n:
            break
    return out


def amostrar(con, n: int, seed: int, saida: Path, ner=None, raio: int = 140) -> dict:
    """Gera `amostra-<data>.md` (para ler) e `.csv` (para marcar). Só texto já anonimizado."""
    from .qa import consulta

    permitidos = auditoria.relatores_da_base(con)
    ids = [r[0] for r in con.execute("SELECT id FROM acordaos ORDER BY id").fetchall()]
    rng = random.Random(seed)
    escolhidos = sorted(rng.sample(ids, min(n, len(ids))))
    saida.mkdir(parents=True, exist_ok=True)
    base = saida / f"amostra-{date.today().isoformat()}-s{seed}"
    md, linhas = [f"# Amostra de revisão ({len(escolhidos)} acórdãos, semente {seed})\n",
                  ("Marque no CSV: nomes de pessoas físicas ou identificadores que ainda aparecem, "
                  "e máscaras indevidas (termo jurídico ou empresa mascarado sem necessidade).\n")], []
    for id_ in escolhidos:
        cur = con.execute("SELECT * FROM acordaos WHERE id = ?", [id_])
        r = dict(zip([c[0] for c in cur.description], cur.fetchone()))
        t = _texto(r)
        suspeitos = auditoria.candidatos_vazamento(t, ner, permitidos)
        palavras = len(t.split())
        mascaras = len(_MASCARA.findall(t))
        md += [f"## {id_}: {consulta.citacao(r)}", f"palavras: {palavras} | máscaras: {mascaras}\n"]
        if suspeitos:
            md.append("**Candidatos a vazamento (detector independente):**")
            md += [f"- `{s}`" for s in suspeitos[:8]]
        md.append("**Contexto das máscaras:**")
        md += [f"- …{x}…" for x in _trechos(t, _MASCARA, 6, raio)] or ["- (nenhuma máscara)"]
        sem = re.sub(_MASCARA, " ", t)
        meio = len(sem) // 2
        md += ["**Trecho sem máscara (leia procurando nomes):**", f"> {sem[meio : meio + 500]}".replace("\n", " "), ""]
        linhas.append({"id": id_, "citacao": consulta.citacao(r), "palavras": palavras,
                       "total_mascaras": mascaras, "qtd_nomes_remanescentes": "",
                       "qtd_identificadores_remanescentes": "", "qtd_mascaras_indevidas": "",
                       "observacoes": ""})
    base.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(linhas)
    return {"md": str(base.with_suffix(".md")), "csv": str(base.with_suffix(".csv")),
            "documentos": len(escolhidos)}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confiança de Wilson para uma proporção (bom com n pequeno e k perto de 0)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _int(v: str) -> int | None:
    v = (v or "").strip()
    return int(v) if v.isdigit() else None


def pontuar(csv_path: Path) -> dict:
    """Taxa de vazamento a partir do CSV marcado. Linhas sem marcação ficam de fora (e são contadas)."""
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    ok, pendentes = [], 0
    for r in linhas:
        nomes, ident, indev = (_int(r["qtd_nomes_remanescentes"]), _int(r["qtd_identificadores_remanescentes"]),
                               _int(r["qtd_mascaras_indevidas"]))
        if None in (nomes, ident, indev):
            pendentes += 1
            continue
        ok.append({**r, "nomes": nomes, "ident": ident, "indev": indev,
                   "palavras": int(r["palavras"]), "mascaras": int(r["total_mascaras"])})
    n = len(ok)
    com_vazamento = sum(1 for r in ok if r["nomes"] or r["ident"])
    palavras = sum(r["palavras"] for r in ok)
    vazamentos = sum(r["nomes"] + r["ident"] for r in ok)
    mascaras = sum(r["mascaras"] for r in ok)
    lo, hi = wilson(com_vazamento, n)
    return {
        "revisados": n, "pendentes": pendentes,
        "docs_com_vazamento": com_vazamento,
        "taxa_docs_com_vazamento": com_vazamento / n if n else None,
        "ic95_docs": (round(lo, 4), round(hi, 4)),
        "vazamentos_por_mil_palavras": vazamentos / (palavras / 1000) if palavras else None,
        "nomes_remanescentes": sum(r["nomes"] for r in ok),
        "identificadores_remanescentes": sum(r["ident"] for r in ok),
        "mascaras_indevidas": sum(r["indev"] for r in ok),
        "taxa_mascara_indevida": sum(r["indev"] for r in ok) / mascaras if mascaras else None,
    }
