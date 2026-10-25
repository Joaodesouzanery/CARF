"""Mede a heurística de resultado contra o resultado oficial (CSV de Julgamentos).

Uso: python scripts/avaliar_resultado.py DATA_DIR ANO [N] [PULAR]  (PULAR separa uma amostra de validação)
Só entram decisões com um único recurso no gabarito (sem ambiguidade).
"""

import sys

import pandas as pd

from carf.qa.consulta import classificar_resultado
from carf.solr import SolrClient


def main(data_dir: str, ano: int, n: int = 2000, pular: int = 0):
    c = SolrClient(delay=0.3)
    linhas = []
    for docs, _, _ in c.pages(fq=[f"ano_sessao_s:{ano}"], fl=("numero_decisao_s", "decisao_txt"), rows=250):
        linhas += docs
        if len(linhas) >= pular + n:
            break
    linhas = linhas[pular:]
    sol = pd.DataFrame(
        [{"numero_decisao": d["numero_decisao_s"], "decisao": "\n".join(d.get("decisao_txt") or [])}
         for d in linhas]
    )
    j = pd.read_parquet(f"{data_dir}/gerenciais/julgamentos/julgamentos_{ano}.parquet",
                        columns=["numero_decisao", "desfecho", "tipo_resultado"])
    j = j[j.tipo_resultado == "Acórdão"]
    unico = j.groupby("numero_decisao").filter(lambda g: len(g) == 1)
    m = sol.merge(unico, on="numero_decisao")
    m["heur"] = m.decisao.map(classificar_resultado)
    decide = m[~m.heur.isin(["OUTRO", "MISTO"])]
    print(f"ano {ano}: {len(m)} decisões com gabarito único (de {len(sol)} lidas)")
    print(f"OUTRO {(m.heur == 'OUTRO').mean():.1%} | MISTO {(m.heur == 'MISTO').mean():.1%}")
    print(f"acurácia quando decide: {(decide.heur == decide.desfecho).mean():.1%} (n={len(decide)})")
    print(f"acurácia geral (OUTRO/MISTO contam como erro): {(m.heur == m.desfecho).mean():.1%}")
    print(pd.crosstab(m.desfecho, m.heur).to_string())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), *(int(a) for a in sys.argv[3:5]))
