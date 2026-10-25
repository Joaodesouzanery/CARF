"""Auditoria da base gravada: nenhum identificador detectável por regra pode restar."""

import random
import re
from collections import Counter

from .privacy import residual_pii

COLUNAS = ("ementa", "decisao", "conteudo")


def auditar(con, mascarar_cnpj=True) -> dict:
    achados: Counter = Counter()
    ids: dict[str, list[str]] = {}
    total = 0
    for id_, *textos in con.execute(f"SELECT id, {', '.join(COLUNAS)} FROM acordaos").fetchall():
        total += 1
        for col, t in zip(COLUNAS, textos):
            for rotulo in residual_pii(t, mascarar_cnpj):
                achados[rotulo] += 1
                ids.setdefault(rotulo, []).append(id_)
    return {"documentos": total, "residuos": dict(achados),
            "exemplos": {k: v[:5] for k, v in ids.items()}}


# --- Auditoria "profunda": detectores diferentes dos usados para anonimizar -----------------------
_DIGITOS = re.compile(r"(?<![\d./-])\d{9,14}(?![\d./-])")
_CPF_PERTO = re.compile(r"(?i)\bcpf\b\D{0,25}\d[\d.\- ]{5,}")
_SR_NOME = re.compile(r"\b(?:Sr|Sra)\.?\s+(?!\[)[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]+")
_PROCESSO = re.compile(r"\d{4,5}[.\-]?\d{3}[.\-]?\d{3}/\d{4}-\d{2}|\d{17}")


def candidatos_vazamento(texto: str, ner=None) -> list[str]:
    """Trechos que ainda parecem dado pessoal num texto JÁ anonimizado.

    Usa regex frouxos (não os da anonimização) e, se houver, um NER cujas entidades passam pelo
    mesmo filtro de `refinar`. Não é independência total (o NER é do mesmo tipo): serve para
    achar o que as regras exatas deixaram passar, não para provar que não há nada.
    """
    from .privacy.ner import palavras_minusculas, refinar
    from .privacy.rules import Span

    achados = []
    sem_proc = _PROCESSO.sub(" ", texto)
    achados += [f"dígitos: {m.group()}" for m in _DIGITOS.finditer(sem_proc)]
    achados += [f"cpf: {m.group().strip()}" for m in _CPF_PERTO.finditer(sem_proc)]
    achados += [f"tratamento+nome: {m.group()}" for m in _SR_NOME.finditer(texto)]
    if ner is not None:
        comuns = palavras_minusculas(texto)
        for sp in ner.detectar(texto):
            ref = refinar(texto, Span(sp.start, sp.end, "NOME"), comuns)
            if ref and ref.label == "NOME" and "[" not in texto[ref.start : ref.end]:
                achados.append(f"nome: {texto[ref.start : ref.end]}")
    return achados


def auditar_profundo(con, n: int = 200, seed: int = 1, ner=None) -> dict:
    ids = [r[0] for r in con.execute("SELECT id FROM acordaos ORDER BY id").fetchall()]
    amostra = random.Random(seed).sample(ids, min(n, len(ids)))
    por_tipo: Counter = Counter()
    exemplos: dict[str, list[str]] = {}
    docs_com = 0
    for id_ in amostra:
        row = con.execute(f"SELECT {', '.join(COLUNAS)} FROM acordaos WHERE id = ?", [id_]).fetchone()
        achados = candidatos_vazamento("\n".join(t for t in row if t), ner)
        docs_com += bool(achados)
        for a in achados:
            tipo = a.split(":")[0]
            por_tipo[tipo] += 1
            exemplos.setdefault(tipo, []).append(f"{id_}: {a}")
    return {"amostra": len(amostra), "docs_com_candidatos": docs_com,
            "por_tipo": dict(por_tipo), "exemplos": {k: v[:6] for k, v in exemplos.items()}}
