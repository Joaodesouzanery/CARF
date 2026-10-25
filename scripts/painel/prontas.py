"""Pesquisas prontas do painel: roda no servidor a busca semântica (e5) com filtros e grava os ids em
ordem de relevância. O painel só exibe; a busca por significado não roda no navegador.

Uso: python scripts/painel/prontas.py DATA_DIR SAIDA_DIR [--por-pesquisa 30]
"""

import argparse
import json
from pathlib import Path

from carf import config
from carf.embeddings import Indice, criar_embedder
from carf.qa import consulta, semantico
from carf.store import Store

PESQUISAS = [
    ("Nulidade acolhida em classificação fiscal",
     "nulidade do lançamento classificação fiscal de mercadorias NCM",
     {"assunto": "classificação de mercadorias", "tese_nulidade": "ACOLHIDA"}),
    ("Nulidade acolhida por cerceamento de defesa",
     "nulidade da decisão por cerceamento do direito de defesa, não enfrentou argumentos e provas",
     {"tese_nulidade": "ACOLHIDA"}),
    ("Nulidade acolhida por vício material no lançamento",
     "nulidade do lançamento por vício material, erro na identificação do sujeito passivo ou na capitulação legal",
     {"tese_nulidade": "ACOLHIDA"}),
    ("Conceito de insumo no PIS e na Cofins",
     "conceito de insumo essencialidade e relevância créditos de PIS e Cofins não cumulativos", {}),
    ("Decadência: art. 150, § 4º, do CTN",
     "decadência do direito de lançar, pagamento antecipado, art. 150 § 4º do CTN", {}),
    ("Multa qualificada: fraude e evidente intuito",
     "multa de ofício qualificada de 150% evidente intuito de fraude, sonegação, simulação", {}),
    ("Responsabilidade solidária de sócios e administradores",
     "responsabilidade tributária de sócio administrador, art. 135 do CTN, excesso de poderes", {}),
    ("Depósitos bancários de origem não comprovada",
     "omissão de rendimentos por depósitos bancários de origem não comprovada, art. 42 da Lei 9.430", {}),
    ("Prescrição intercorrente no processo administrativo",
     "prescrição intercorrente no processo administrativo fiscal, Súmula CARF nº 11", {}),
    ("Ágio e amortização por rentabilidade futura",
     "amortização de ágio por expectativa de rentabilidade futura, laudo de avaliação, empresa veículo", {}),
    ("Preço de transferência",
     "preço de transferência métodos PIC PRL margem de lucro operações com partes vinculadas", {}),
    ("Concomitância com ação judicial",
     "concomitância entre processo administrativo e ação judicial, renúncia às instâncias administrativas, Súmula CARF 1", {}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("saida")
    ap.add_argument("--por-pesquisa", type=int, default=30)
    ap.add_argument("--modelo", default="e5-small")
    a = ap.parse_args()
    config.DATA_DIR = a.data_dir
    con = Store(a.data_dir).connect()
    indice, emb = Indice(a.data_dir, a.modelo).carregar(), criar_embedder(a.modelo)
    out = []
    for titulo, q, filtros in PESQUISAS:
        r = semantico.buscar(con, q, filtros, a.por_pesquisa, "semantico", indice, emb)
        ids = [x["id"] for x in r]
        mapa = {x["id"]: x for x in r}
        anos = sorted({int(x["ano"]) for x in r if x.get("ano")})
        res = {}
        for x in r:
            k = consulta.classificar_resultado(x.get("decisao"))
            res[k] = res.get(k, 0) + 1
        out.append({"titulo": titulo, "q": q, "ids": ids, "anos": anos, "res": res, "filtros": list(filtros),
                    "iguais": {i: mapa[i].get("iguais", 1) for i in ids if mapa[i].get("iguais", 1) > 1}})
        print(f"{titulo}: {len(ids)}")
    (Path(a.saida) / "prontas.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
