"""Sincronização completa e incremental com anonimização antes de gravar."""

import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from . import config, solr
from . import text as tx
from .store import Store

_AUSENTE = object()


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
        os.replace(tmp, self.path)


def filtros_base(ano_min: int | None, ano_max: int | None = None) -> list[str]:
    if not ano_min and not ano_max:
        return []
    return [f"ano_sessao_s:[{ano_min or '*'} TO {ano_max or '*'}]"]


CAMPOS_LEVES = tuple(c for c in solr.FIELDS if c != "conteudo_txt")


TEXTOS = ("ementa_s", "conteudo_txt")


def _escalares(doc: dict) -> dict:
    """O Solr pode devolver lista em qualquer campo: texto junta, metadado pega o primeiro valor."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, list) and k != "decisao_txt":
            v = "\n".join(map(str, v)) if k in TEXTOS else (v[0] if v else None)
        out[k] = v
    return out


def montar_linha(doc: dict, anon, agora: datetime, leve: bool = False) -> dict:
    doc = _escalares(doc)
    relator = doc.get("nome_relator_s")
    if relator and re.search(r"\d{6,}", relator):  # a fonte às vezes traz "<CPF> - CPF não encontrado."
        relator = None
    permitidos = [relator] if relator else []
    stats: Counter = Counter()

    def limpo(valor):
        out, st = anon.anonymize(valor, permitidos)
        stats.update(st)
        return out

    dt_sessao = tx.data_sessao_valida(doc.get("dt_sessao_tdt"))
    ano = dt_sessao.year if dt_sessao else tx.ano_valido(doc.get("ano_sessao_s"))
    conteudo = "" if leve else tx.limpar_texto(doc.get("conteudo_txt"))  # leve: nunca guarda o voto
    decisao = doc.get("decisao_txt")
    decisao = "\n".join(decisao) if isinstance(decisao, list) else (decisao or "")

    flags = []
    if not doc.get("dt_sessao_tdt"):
        flags.append("sem_data_sessao")
    elif dt_sessao is None:
        flags.append("data_sessao_invalida")
    if ano is None:
        flags.append("ano_invalido")
    if not conteudo and not leve:
        flags.append("sem_texto")

    return {
        "id": str(doc["id"]),
        "numero_processo": doc.get("numero_processo_s"),
        "numero_decisao": doc.get("numero_decisao_s"),
        "relator": relator,
        "secao": doc.get("secao_s"),
        "camara": doc.get("camara_s"),
        "turma": doc.get("turma_s"),
        "dt_sessao": dt_sessao,
        "ano": ano,
        "ementa": limpo(tx.limpar_texto(doc.get("ementa_s"))),
        "decisao": limpo(tx.limpar_texto(decisao)),
        "conteudo": limpo(conteudo) if conteudo else None,
        "tem_texto": bool(conteudo),
        "nome_arquivo_pdf": doc.get("nome_arquivo_pdf_s"),
        "dt_index": tx.parse_datetime(doc.get("dt_index_tdt")),
        "dt_atualizacao": tx.parse_datetime(doc.get("dt_registro_atualizacao_tdt")),
        "qualidade": ",".join(flags) or None,
        "pii_mascarado": sum(stats.values()),
        "processado_em": agora,
    }


def sincronizar(
    client,
    store: Store,
    state: State,
    anon,
    ano_min: int | None = None,
    limite: int | None = None,
    incremental: bool = False,
    log=print,
    agora=lambda: datetime.now(UTC).replace(tzinfo=None),
    tamanho_pagina: int = config.PAGE_SIZE,
    filtros_extra: tuple[str, ...] = (),
    leve: bool = False,
    relatores: list[str] | None = None,
    ano_max: int | None = None,
) -> dict:
    """Baixa, anonimiza e grava. Retoma do cursor salvo se a execução anterior foi interrompida."""
    base = filtros_base(ano_min, ano_max) + list(filtros_extra)
    modo = "inc" if incremental else "full"
    d = state.data
    assinatura = {"ano_min": ano_min}
    if ano_max:
        assinatura["ano_max"] = ano_max
    if filtros_extra:
        assinatura["extra"] = list(filtros_extra)
    if incremental:
        if not d.get("last_dt_index"):
            raise RuntimeError("Nenhuma carga completa concluída; rode a sincronização completa antes.")
        if d.get("filters") != assinatura:
            raise RuntimeError("Filtros diferentes dos da carga completa; use os mesmos filtros.")
        leve = d.get("leve", leve)
        fq = base + [f"dt_index_tdt:[{d['last_dt_index']} TO *]"]
    else:
        if d.get("filters") != assinatura:
            d.clear()
            d["filters"] = assinatura
        d["leve"] = leve
        fq = base

    secao = d.setdefault(modo, {})
    if "snapshot" not in secao:
        # Marca-d'água tirada antes de baixar: qualquer doc indexado depois cai na próxima incremental.
        secao["snapshot"] = client.summary(base)["max_dt_index"]
    cursor = secao.get("cursor") or "*"
    state.save()

    anon.allowlist.adicionar(relatores if relatores is not None else client.relatores())
    processados = novos = atualizados = ignorados = 0
    interrompido = False
    for docs, nxt, total in client.pages(fq, fl=CAMPOS_LEVES if leve else solr.FIELDS, rows=tamanho_pagina, cursor=cursor):
        if docs:
            if incremental:
                # O limite do fq é inclusivo e o indexador carimba lotes inteiros com o mesmo
                # dt_index: pula o que já está gravado nesta versão (evita reprocessar o lote).
                guardado = store.existing([str(x["id"]) for x in docs])
                novos_docs = []
                for x in docs:
                    antigo = guardado.get(str(x["id"]), _AUSENTE)
                    if antigo is _AUSENTE:
                        novos += 1
                    elif antigo == tx.parse_datetime(x.get("dt_index_tdt")):
                        ignorados += 1
                        continue
                    else:
                        atualizados += 1
                    novos_docs.append(x)
                docs = novos_docs
            ts = agora()
            if docs:
                store.write([montar_linha(x, anon, ts, leve) for x in docs])
            processados += len(docs)
            log(f"[{modo}] {processados}/{total} documentos gravados")
        secao["cursor"] = nxt
        secao["processados"] = secao.get("processados", 0) + len(docs)
        secao["total"] = total
        state.save()
        if limite and processados >= limite:
            interrompido = True
            break

    resumo = {"modo": modo, "processados": processados, "novos": novos,
              "atualizados": atualizados, "ignorados": ignorados, "completo": not interrompido}
    if not interrompido:
        if secao.get("snapshot"):
            d["last_dt_index"] = secao["snapshot"]
        d.pop(modo, None)
        if not incremental:
            d["full_done"] = True
    state.save()
    _changelog(state.path.parent / "changelog.jsonl", resumo, agora())
    return resumo


def _changelog(path: Path, resumo: dict, ts: datetime):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts.isoformat(timespec="seconds"), **resumo}, ensure_ascii=False) + "\n")
