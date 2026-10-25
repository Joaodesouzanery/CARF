"""Compara busca léxica, semântica e híbrida usando o TEMA OFICIAL como gabarito de relevância.

Para cada tema de `concentracao_tematica` (CSV oficial de Julgamentos) com amostra suficiente, a
consulta é o texto do tema e os documentos relevantes são os acórdãos marcados com aquele tema.
Mede precisão@10 e MRR. É um gabarito imperfeito (o tema nem sempre aparece na ementa), mas
objetivo e igual para todos os métodos.

Uso: python scripts/avaliar_busca.py DATA_DIR ANO MODELO [MODELO...]
"""

import sys
from pathlib import Path

import pandas as pd

from carf.embeddings import Indice, criar_embedder
from carf.qa import consulta, semantico
from carf.store import Store


def temas(data_dir: Path, ano: int, ids_na_base: set[str], minimo: int = 40, top: int = 30):
    j = pd.read_parquet(data_dir / f"gerenciais/julgamentos/julgamentos_{ano}.parquet",
                        columns=["numero_decisao", "concentracao_tematica", "tipo_resultado"])
    j = j[(j.tipo_resultado == "Acórdão") & j.concentracao_tematica.notna()]
    uni = j.groupby("numero_decisao").filter(lambda g: g.concentracao_tematica.nunique() == 1)
    uni = uni.drop_duplicates("numero_decisao")
    return uni, minimo, top


def main(data_dir: str, ano: int, modelos: list[str]):
    raiz = Path(data_dir)
    con = Store(raiz).connect()
    base = con.execute("SELECT id, numero_decisao FROM acordaos WHERE ano = ?", [ano]).df()
    uni, minimo, top = temas(raiz, ano, set(base.id))
    m = base.merge(uni, on="numero_decisao")
    contagem = m.concentracao_tematica.value_counts()
    escolhidos = contagem[contagem >= minimo].head(top).index.tolist()
    print(f"{len(base)} acórdãos de {ano} na base; {len(m)} com tema único; {len(escolhidos)} temas avaliados\n")
    runs = {"lexico-E": lambda q: consulta.buscar(con, q, None, 10),
            "lexico-OU": lambda q: consulta.buscar(con, q, None, 10, qualquer=True)}
    for nome in modelos:
        emb, idx = criar_embedder(nome), Indice(raiz, nome).carregar()
        runs[f"semantico-{nome}"] = lambda q, e=emb, i=idx: semantico.buscar(con, q, None, 10, "semantico", i, e)
        runs[f"hibrido-{nome}"] = lambda q, e=emb, i=idx: semantico.buscar(con, q, None, 10, "hibrido", i, e)
    res = {k: {"p10": [], "mrr": []} for k in runs}
    for tema in escolhidos:
        rel = set(m[m.concentracao_tematica == tema].id)
        consulta_txt = tema.lower()
        for nome, fn in runs.items():
            try:
                ids = [r["id"] for r in fn(consulta_txt)]
            except ValueError:
                ids = []
            acertos = [i in rel for i in ids]
            res[nome]["p10"].append(sum(acertos) / 10)
            res[nome]["mrr"].append(next((1 / (p + 1) for p, a in enumerate(acertos) if a), 0.0))
    print(f"{'método':28s} {'P@10':>6s} {'MRR':>6s}")
    for nome, r in res.items():
        print(f"{nome:28s} {sum(r['p10']) / len(escolhidos):6.3f} {sum(r['mrr']) / len(escolhidos):6.3f}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3:])
