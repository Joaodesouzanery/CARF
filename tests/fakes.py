"""Solr falso em memória: cursorMark, fq de dt_index e falhas injetáveis."""

import re


class RespostaFalsa:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))


def doc(i, dt_index="2026-01-01T00:00:00Z", **kw):
    base = {
        "id": str(i), "numero_processo_s": f"13896.{i:06d}/2020-11", "numero_decisao_s": f"1301-{i:06d}",
        "nome_relator_s": "PAULO JAKSON DA SILVA LUCAS", "turma_s": "Primeira Turma", "camara_s": "Terceira Câmara",
        "secao_s": "Primeira Seção", "dt_sessao_tdt": "2022-03-16T00:00:00Z", "ano_sessao_s": "2022",
        "ementa_s": f"IRPJ. Glosa de despesas {i}. Contribuinte João Carlos da Silva CPF 529.982.247-25.",
        "decisao_txt": ["Acordam os membros por unanimidade, negar provimento ao recurso voluntário."],
        "conteudo_txt": "Metadados => a: b | Conteúdo => \nVoto do relator. Email x@y.com.br\n",
        "nome_arquivo_pdf_s": f"{i}.pdf", "dt_index_tdt": dt_index,
        "dt_registro_atualizacao_tdt": "2026-01-01T00:00:00Z",
    }
    base.update(kw)
    return base


class SessaoFalsa:
    """Imita requests.Session contra um índice Solr com `docs`."""

    def __init__(self, docs, falhas=(), tamanho_max=None):
        self.docs = sorted(docs, key=lambda d: d["id"])
        self.falhas = list(falhas)  # status HTTP a devolver nas primeiras chamadas
        self.chamadas = []

    def get(self, url, params=None, **kw):
        self.chamadas.append(params)
        if self.falhas:
            return RespostaFalsa(self.falhas.pop(0))
        sel = list(self.docs)
        for fq in params.get("fq", []):
            m = re.match(r"dt_index_tdt:\[(.+) TO \*\]", fq)
            if m:
                sel = [d for d in sel if d.get("dt_index_tdt", "") >= m.group(1)]
            m = re.match(r"ano_sessao_s:\[(\d+) TO \*\]", fq)
            if m:
                sel = [d for d in sel if d.get("ano_sessao_s", "") >= m.group(1)]
        if params.get("facet"):
            nomes = sorted({d["nome_relator_s"] for d in self.docs})
            return RespostaFalsa(data={"facet_counts": {"facet_fields": {
                "nome_relator_s": [x for n in nomes for x in (n, 1)]}}})
        if params.get("stats"):
            mx = max((d["dt_index_tdt"] for d in sel), default=None)
            return RespostaFalsa(data={"response": {"numFound": len(sel), "docs": []},
                                       "stats": {"stats_fields": {"dt_index_tdt": {"max": mx}}}})
        cur = params["cursorMark"]
        ini = 0 if cur == "*" else int(cur)
        rows = params["rows"]
        pag = sel[ini : ini + rows]
        nxt = str(ini + len(pag)) if pag else cur
        return RespostaFalsa(data={"response": {"numFound": len(sel), "docs": pag}, "nextCursorMark": nxt})
