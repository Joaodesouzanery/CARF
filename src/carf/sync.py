"""Sincronização completa e incremental com anonimização antes de gravar."""

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from . import config
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


def filtros_base(ano_min: int | None) -> list[str]:
    return [f"ano_sessao_s:[{ano_min} TO *]"] if ano_min else []


def montar_linha(doc: dict, anon, agora: datetime) -> dict:
    relator = doc.get("nome_relator_s")
    permitidos = [relator] if relator else []
    stats: Counter = Counter()

    def limpo(valor):
        out, st = anon.anonymize(valor, permitidos)
        stats.update(st)
        return out

    dt_sessao = tx.data_sessao_valida(doc.get("dt_sessao_tdt"))
    ano = dt_sessao.year if dt_sessao else tx.ano_valido(doc.get("ano_sessao_s"))
    conteudo = tx.limpar_texto(doc.get("conteudo_txt"))
    decisao = doc.get("decisao_txt")
    decisao = "\n".join(decisao) if isinstance(decisao, list) else (decisao or "")

    flags = []
    if not doc.get("dt_sessao_tdt"):
        flags.append("sem_data_sessao")
    elif dt_sessao is None:
        flags.append("data_sessao_invalida")
    if ano is None:
        flags.append("ano_invalido")
    if not conteudo:
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
        "conteudo": limpo(conteudo),
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
) -> dict:
    """Baixa, anonimiza e grava. Retoma do cursor salvo se a execução anterior foi interrompida."""
    base = filtros_base(ano_min)
    modo = "inc" if incremental else "full"
    d = state.data
    if incremental:
        if not d.get("last_dt_index"):
            raise RuntimeError("Nenhuma carga completa concluída; rode a sincronização completa antes.")
        if d.get("filters") != {"ano_min": ano_min}:
            raise RuntimeError("Filtros diferentes dos da carga completa; use os mesmos filtros.")
        fq = base + [f"dt_index_tdt:[{d['last_dt_index']} TO *]"]
    else:
        if d.get("filters") != {"ano_min": ano_min}:
            d.clear()
            d["filters"] = {"ano_min": ano_min}
        fq = base

    secao = d.setdefault(modo, {})
    if "snapshot" not in secao:
        # Marca-d'água tirada antes de baixar: qualquer doc indexado depois cai na próxima incremental.
        secao["snapshot"] = client.summary(base)["max_dt_index"]
    cursor = secao.get("cursor") or "*"
    state.save()

    anon.allowlist.adicionar(client.relatores())
    processados = novos = atualizados = ignorados = 0
    interrompido = False
    for docs, nxt, total in client.pages(fq, rows=tamanho_pagina, cursor=cursor):
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
                store.write([montar_linha(x, anon, ts) for x in docs])
            processados += len(docs)
            log(f"[{modo}] {processados}/{total} documentos gravados")
        secao["cursor"] = nxt
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
