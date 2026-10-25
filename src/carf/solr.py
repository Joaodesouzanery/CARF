"""Cliente do índice Solr de acórdãos, com limite de taxa e retentativas."""

import time
from collections.abc import Iterator

import requests

from . import config

FIELDS = (
    "id",
    "numero_processo_s",
    "numero_decisao_s",
    "nome_relator_s",
    "secao_s",
    "camara_s",
    "turma_s",
    "dt_sessao_tdt",
    "ano_sessao_s",
    "ementa_s",
    "decisao_txt",
    "conteudo_txt",
    "nome_arquivo_pdf_s",
    "arquivo_indexado_s",
    "dt_index_tdt",
    "dt_registro_atualizacao_tdt",
)

RETRY_STATUS = {429, 500, 502, 503, 504}


class SolrError(RuntimeError):
    pass


class SolrClient:
    def __init__(
        self,
        url=config.SOLR_URL,
        session=None,
        delay=config.REQUEST_DELAY,
        retries=5,
        backoff=2.0,
        timeout=90,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.url = url
        self.session = session or requests.Session()
        self.delay = delay
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self._sleep = sleep
        self._clock = clock
        self._last = None

    def _throttle(self):
        if self._last is not None:
            wait = self.delay - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def _get(self, params):
        params = {**params, "wt": "json"}
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                resp = self.session.get(
                    self.url,
                    params=params,
                    timeout=self.timeout,
                    headers={"User-Agent": config.USER_AGENT},
                )
                if resp.status_code in RETRY_STATUS:
                    retry_after = resp.headers.get("Retry-After", "")
                    raise SolrError(
                        f"HTTP {resp.status_code}",
                        float(retry_after) if retry_after.isdigit() else None,
                    )
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, SolrError, ValueError) as exc:
                if attempt == self.retries:
                    raise SolrError(f"falha após {attempt + 1} tentativas: {exc}") from exc
                hint = exc.args[1] if isinstance(exc, SolrError) and len(exc.args) > 1 else None
                self._sleep(hint or self.backoff**attempt)
        raise AssertionError("inalcançável")

    def pages(
        self, fq=(), fl=FIELDS, rows=config.PAGE_SIZE, cursor="*"
    ) -> Iterator[tuple[list[dict], str, int]]:
        """Itera páginas por cursorMark. Rende (docs, próximo cursor, total)."""
        while True:
            data = self._get(
                {
                    "q": "*:*",
                    "fq": list(fq),
                    "fl": ",".join(fl),
                    "rows": rows,
                    "sort": "id asc",
                    "cursorMark": cursor,
                }
            )
            docs = data["response"]["docs"]
            nxt = data["nextCursorMark"]
            yield docs, nxt, data["response"]["numFound"]
            if not docs or nxt == cursor:
                return
            cursor = nxt

    def summary(self, fq=()) -> dict:
        """Contagem e maior dt_index_tdt (consulta barata, sem documentos)."""
        data = self._get(
            {
                "q": "*:*",
                "fq": list(fq),
                "rows": 0,
                "stats": "true",
                "stats.field": "dt_index_tdt",
            }
        )
        stats = (data.get("stats") or {}).get("stats_fields", {}).get("dt_index_tdt") or {}
        return {"num_found": data["response"]["numFound"], "max_dt_index": stats.get("max")}

    def relatores(self) -> list[str]:
        data = self._get(
            {
                "q": "*:*",
                "rows": 0,
                "facet": "true",
                "facet.field": "nome_relator_s",
                "facet.limit": -1,
                "facet.mincount": 1,
            }
        )
        flat = data["facet_counts"]["facet_fields"]["nome_relator_s"]
        return flat[::2]

    def pivot_ano_secao(self, fq=()) -> list[dict]:
        """Contagem por ano de sessão e seção (base para fatiar a carga em paralelo)."""
        data = self._get(
            {
                "q": "*:*",
                "fq": list(fq),
                "rows": 0,
                "facet": "true",
                "facet.pivot": "ano_sessao_s,secao_s",
                "facet.limit": -1,
                "facet.pivot.mincount": 1,
            }
        )
        return data["facet_counts"]["facet_pivot"]["ano_sessao_s,secao_s"]
