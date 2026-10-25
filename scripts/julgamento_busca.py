"""Avaliação de busca por julgamento de relevância (pooling).

  gerar   DATA_DIR MODELO [MODELO...]   -> data/review/busca-julgamento.csv (para marcar 0/1/2)
  pontuar CSV                           -> P@10 e nDCG@10 por método

Cada consulta é executada em todos os métodos; a união dos 8 primeiros de cada um vai para a
planilha SEM dizer quem trouxe o quê (a coluna de métodos fica separada). Relevância: 0 = não,
1 = relacionado, 2 = responde bem. O gabarito oficial `concentracao_tematica` NÃO serve aqui: ele
classifica o tipo de lançamento, não o assunto jurídico da ementa.
"""

import csv
import math
import sys
from pathlib import Path

from carf.embeddings import Indice, criar_embedder
from carf.qa import consulta, semantico
from carf.store import Store

CONSULTAS = [
    "conceito de insumo essencialidade relevância crédito PIS COFINS",
    "omissão de rendimentos depósitos bancários origem não comprovada",
    "decadência lançamento por homologação artigo 150 parágrafo 4º",
    "multa qualificada dolo sonegação fraude 150%",
    "responsabilidade solidária sócio administrador artigo 135 CTN",
    "dedução de despesas médicas glosa comprovação IRPF",
    "amortização de ágio rentabilidade futura dedutibilidade",
    "preço de transferência métodos PRL",
    "participação nos lucros e resultados contribuição previdenciária",
    "ressarcimento crédito presumido IPI",
    "imunidade entidade sem fins lucrativos requisitos",
    "ganho de capital alienação de imóvel",
    "grupo econômico de fato solidariedade contribuições previdenciárias",
    "nulidade do lançamento cerceamento de defesa",
    "prescrição intercorrente processo administrativo fiscal",
    "arbitramento do lucro lucro presumido",
    "juros sobre capital próprio dedutibilidade",
    "subvenção para investimento crédito presumido ICMS base de cálculo",
    "exclusão do ICMS da base de cálculo do PIS e da COFINS",
    "incentivos fiscais lei do bem pesquisa e desenvolvimento",
]
TOP = 8


def metodos(con, raiz: Path, modelos: list[str]):
    out = {"lexico-OU": lambda q: consulta.buscar(con, q, None, TOP, qualquer=True)}
    for m in modelos:
        emb, idx = criar_embedder(m), Indice(raiz, m).carregar()
        out[f"semantico-{m}"] = lambda q, e=emb, i=idx: semantico.buscar(con, q, None, TOP, "semantico", i, e)
        out[f"hibrido-{m}"] = lambda q, e=emb, i=idx: semantico.buscar(con, q, None, TOP, "hibrido", i, e)
    return out


def gerar(data_dir: str, modelos: list[str]):
    raiz = Path(data_dir)
    con = Store(raiz).connect()
    ms = metodos(con, raiz, modelos)
    linhas = []
    for qi, q in enumerate(CONSULTAS, 1):
        pool: dict[str, dict] = {}
        for nome, fn in ms.items():
            for rank, r in enumerate(fn(q), 1):
                d = pool.setdefault(r["id"], {"r": r, "ranks": {}})
                d["ranks"][nome] = rank
        for id_, d in sorted(pool.items(), key=lambda x: min(x[1]["ranks"].values())):
            r = d["r"]
            linhas.append({"q": qi, "consulta": q, "id": id_, "citacao": r["citacao"],
                           "ementa": (r["ementa"] or "")[:420].replace("\n", " "),
                           "ranks": ";".join(f"{k}={v}" for k, v in d["ranks"].items()), "relevante": ""})
    destino = raiz / "review" / "busca-julgamento.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)
    print(f"{len(linhas)} linhas em {destino}")


def pontuar(caminho: str):
    with open(caminho, newline="", encoding="utf-8") as f:
        linhas = [r for r in csv.DictReader(f) if r["relevante"].strip() != ""]
    por_q: dict[int, list[dict]] = {}
    for r in linhas:
        por_q.setdefault(int(r["q"]), []).append(r)
    metodos_vistos = sorted({k.split("=")[0] for r in linhas for k in r["ranks"].split(";") if k})
    print(f"{len(por_q)} consultas julgadas, {len(linhas)} documentos\n")
    print(f"{'método':24s} {'P@8':>6s} {'nDCG@8':>7s}")
    for m in metodos_vistos:
        p, n = [], []
        for rs in por_q.values():
            rank = {r["id"]: int(dict(x.split("=") for x in r["ranks"].split(";"))[m])
                    for r in rs if m in r["ranks"]}
            rel = {r["id"]: int(r["relevante"]) for r in rs}
            top = sorted(rank, key=rank.get)[:TOP]
            p.append(sum(rel[i] > 0 for i in top) / TOP)
            dcg = sum((2 ** rel[i] - 1) / math.log2(k + 2) for k, i in enumerate(top))
            ideal = sorted(rel.values(), reverse=True)[:TOP]
            idcg = sum((2 ** g - 1) / math.log2(k + 2) for k, g in enumerate(ideal))
            n.append(dcg / idcg if idcg else 0.0)
        print(f"{m:24s} {sum(p) / len(p):6.3f} {sum(n) / len(n):7.3f}")


if __name__ == "__main__":
    if sys.argv[1] == "gerar":
        gerar(sys.argv[2], sys.argv[3:])
    else:
        pontuar(sys.argv[2])
