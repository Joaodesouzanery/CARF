"""Gera src/carf/privacy/vocab_comum.txt: palavras que aparecem em minúscula em muitos acórdãos.

Uma entidade cujos termos são TODOS vocabulário comum (ex.: "DESPESAS MÉDICAS") não é nome de
pessoa. Nomes próprios quase nunca aparecem em minúscula, então não entram na lista.

Uso: python scripts/gerar_vocabulario.py DATA_DIR [MIN_DOCS]
"""

import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from carf.privacy.ner import Allowlist  # noqa: F401  (garante o mesmo pacote instalado)
from carf.store import Store

DESTINO = Path(__file__).resolve().parent.parent / "src/carf/privacy/vocab_comum.txt"
PALAVRA = re.compile(r"(?<![\w\[])[a-zà-ÿ]{4,}(?![\w\]])")


def main(data_dir: str, minimo: int = 25):
    con = Store(data_dir).connect()
    docs = Counter()
    for ementa, decisao in con.execute("SELECT ementa, decisao FROM acordaos").fetchall():
        docs.update(set(PALAVRA.findall(f"{ementa or ''} {decisao or ''}")))
    # nomes de relatores nunca entram, mesmo que apareçam em minúscula por erro de OCR
    relatores = {t for (r,) in con.execute("SELECT DISTINCT relator FROM acordaos").fetchall() if r
                 for t in re.findall(r"[a-zà-ÿ]{4,}", unicodedata.normalize("NFC", r.lower()))}
    vocab = sorted(p for p, n in docs.items() if n >= minimo and p not in relatores)
    DESTINO.write_text("\n".join(vocab) + "\n", encoding="utf-8")
    print(f"{len(vocab)} palavras (>= {minimo} acórdãos) em {DESTINO}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 25)
