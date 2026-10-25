"""Carga em paralelo: fatias disjuntas (ano x seção), um processo por grupo de fatias."""

import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path

from . import anonimizador
from .solr import SolrClient
from .store import Store
from .sync import State, filtros_base, sincronizar


@dataclass(frozen=True)
class Unidade:
    fq: tuple[str, ...]
    n: int

    @property
    def chave(self) -> str:
        return hashlib.sha1("|".join(self.fq).encode()).hexdigest()[:10]


def _q(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fatiar(client, ano_min: int | None = None, ano_max: int | None = None) -> list[Unidade]:
    """Particiona o recorte em unidades disjuntas e completas (nada some, nada repete)."""
    unidades = []
    for no in client.pivot_ano_secao(filtros_base(ano_min, ano_max)):
        ano = f"ano_sessao_s:{_q(str(no['value']))}"
        filhos = no.get("pivot") or []
        for f in filhos:
            unidades.append(Unidade((ano, f"secao_s:{_q(str(f['value']))}"), f["count"]))
        resto = no["count"] - sum(f["count"] for f in filhos)
        if resto > 0:
            if filhos:
                excluir = " OR ".join(_q(str(f["value"])) for f in filhos)
                unidades.append(Unidade((ano, f"-secao_s:({excluir})"), resto))
            else:
                unidades.append(Unidade((ano, "-secao_s:[* TO *]"), resto))
    # As contagens por faceta podem somar menos que o total do índice: a unidade residual é
    # definida por exclusão, então a partição é completa por construção.
    if unidades:
        cobertas = " OR ".join("(" + " AND ".join(u.fq) + ")" for u in unidades)
        residual = (f"-({cobertas})",)
        n = client.summary(filtros_base(ano_min, ano_max) + list(residual))["num_found"]
        if n > 0:
            unidades.append(Unidade(residual, n))
    return unidades


def distribuir(unidades: list[Unidade], n: int) -> list[list[Unidade]]:
    """Maiores primeiro, sempre na fila menos carregada (equilibra o tempo total)."""
    filas: list[list[Unidade]] = [[] for _ in range(n)]
    carga = [0] * n
    for u in sorted(unidades, key=lambda x: -x.n):
        i = carga.index(min(carga))
        filas[i].append(u)
        carga[i] += u.n
    return [f for f in filas if f]


def _estado_unidade(data_dir: Path, u: Unidade) -> State:
    return State(data_dir / "state" / f"unidade-{u.chave}.json")


def executar_fila(client, anon, data_dir: Path, fila: list[Unidade], ano_min, leve, limite=None,
                  log=print, ano_max=None, **kw) -> list[dict]:
    """Roda as unidades da fila em sequência; unidades já concluídas são puladas (retomada)."""
    relatores = client.relatores()
    store, resultados = Store(data_dir), []
    for u in fila:
        estado = _estado_unidade(data_dir, u)
        if estado.data.get("full_done"):
            resultados.append({"unidade": u.chave, "pulada": True})
            continue
        try:
            r = sincronizar(client, store, estado, anon, ano_min=ano_min, ano_max=ano_max, limite=limite, leve=leve,
                            filtros_extra=u.fq, relatores=relatores,
                            log=lambda m, k=u.chave: log(f"[{k}] {m}"), **kw)
        except Exception as exc:  # noqa: BLE001  uma unidade ruim não derruba as outras
            # o cursor fica salvo: reexecutar retoma de onde parou
            resultados.append({"unidade": u.chave, "fq": list(u.fq), "erro": repr(exc)[:300]})
            log(f"[{u.chave}] ERRO: {exc!r}")
            continue
        resultados.append({"unidade": u.chave, **r})
    return resultados


def _processo(args):
    data_dir, fila, ano_min, leve, sem_ner, manter_cnpj, limite, ano_max = args
    client = SolrClient()
    anon = anonimizador.criar(sem_ner, manter_cnpj)
    return executar_fila(client, anon, Path(data_dir), fila, ano_min, leve, limite, ano_max=ano_max)


def sincronizar_paralelo(data_dir: Path, ano_min=None, workers=3, leve=True, sem_ner=False,
                         manter_cnpj=False, limite=None, executor=None, client=None, log=print,
                         ano_max=None) -> dict:
    """Coordena a carga. Só marca a carga global como concluída quando todas as unidades terminam."""
    client = client or SolrClient()
    unidades = fatiar(client, ano_min, ano_max)
    filas = distribuir(unidades, workers)
    (data_dir / "state").mkdir(parents=True, exist_ok=True)
    run = data_dir / "state" / "run.json"
    if not run.exists():
        run.write_text(json.dumps({"inicio": time.time(), "ano_min": ano_min, "ano_max": ano_max, "leve": leve,
                                   "total": sum(u.n for u in unidades), "unidades": len(unidades)}))
    log(f"{len(unidades)} unidades, {sum(u.n for u in unidades)} documentos, {len(filas)} processos")
    args = [(str(data_dir), f, ano_min, leve, sem_ner, manter_cnpj, limite, ano_max) for f in filas]
    if executor is not None:  # injeção para testes (execução no mesmo processo)
        resultados = [r for a in args for r in executor(a)]
    else:
        with ProcessPoolExecutor(max_workers=len(filas), mp_context=get_context("spawn")) as ex:
            resultados = [r for lote in ex.map(_processo, args) for r in lote]
    completo = all(
        _estado_unidade(data_dir, u).data.get("full_done") for u in unidades
    )
    if completo:
        marcas = [_estado_unidade(data_dir, u).data.get("last_dt_index") for u in unidades]
        marcas = [m for m in marcas if m]
        glob = State(data_dir / "state.json")
        anterior = glob.data if glob.data.get("full_done") else {}
        novo = {"filters": {"ano_min": ano_min}, "leve": leve, "full_done": True}
        if ano_max:
            # faixa parcial (ex.: 2018-2022) somada a uma carga anterior: o recorte global passa a
            # ser o mais amplo, e a marca-d'água a mais antiga, para a incremental não perder nada
            ant_min = (anterior.get("filters") or {}).get("ano_min")
            if anterior and ant_min:
                novo["filters"] = {"ano_min": min(ano_min or ant_min, ant_min)}
                marcas += [anterior["last_dt_index"]] if anterior.get("last_dt_index") else []
        if marcas:
            novo["last_dt_index"] = min(marcas)  # conservador: a incremental refaz o que faltar
        glob.data = novo
        glob.save()
    return {"unidades": len(unidades), "processos": len(filas), "completo": completo,
            "processados": sum(r.get("processados", 0) for r in resultados),
            "erros": [r for r in resultados if "erro" in r]}


def status(data_dir: Path, agora=time.time) -> dict:
    run = data_dir / "state" / "run.json"
    if not run.exists():
        return {"estado": "sem carga em andamento"}
    info = json.loads(run.read_text())
    feitos = concluidas = 0
    for f in (data_dir / "state").glob("unidade-*.json"):
        d = json.loads(f.read_text())
        if d.get("full_done"):
            concluidas += 1
            continue
        feitos += (d.get("full") or {}).get("processados", 0)
    return {"unidades_concluidas": concluidas, "unidades": info["unidades"],
            "total_documentos": info["total"], "decorrido_s": int(agora() - info["inicio"]),
            "parciais_em_unidades_abertas": feitos}
