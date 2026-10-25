"""Servidor do painel e da API de busca (`carf serve`).

Sigilo: a consulta de um advogado revela a estratégia do cliente. A busca vai por POST (o texto não
fica em URL de log de proxy), este módulo não registra o conteúdo das requisições e o uvicorn roda
sem access log. O acesso exige token por escritório (guardado como SHA-256).
"""

import hashlib
import hmac
import json
import time
from collections import defaultdict, deque
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from . import config
from .qa import consulta, semantico
from .qa import gerenciais as qg
from .store import Store

LINK = "https://acordaos.economia.gov.br/acordaos2/pdfs/processados/"
FILTROS_API = {"ano", "turma", "camara", "secao", "relator", "assunto", "tese_nulidade", "tese_prescricao"}
TESES = {"ACOLHIDA", "REJEITADA", "INDEFINIDA"}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def carregar_tokens(caminho: Path | None) -> dict[str, str]:
    """{sha256: nome do escritório}. Arquivo JSON; crie com `carf serve --novo-token NOME`."""
    if caminho and Path(caminho).exists():
        return json.loads(Path(caminho).read_text())
    return {}


class LimiteTaxa:
    def __init__(self, por_minuto: int, agora=time.monotonic):
        self.n, self.agora, self.janelas = por_minuto, agora, defaultdict(deque)

    def permite(self, chave: str) -> bool:
        j, t = self.janelas[chave], self.agora()
        while j and t - j[0] > 60:
            j.popleft()
        if len(j) >= self.n:
            return False
        j.append(t)
        return True


def criar_app(data_dir: Path, painel_dir: Path | None = None, tokens: dict[str, str] | None = None,
              sem_token: bool = False, por_minuto: int = 60, indice=None, embedder=None) -> Starlette:
    if not tokens and not sem_token:
        raise ValueError("sem tokens configurados; use --sem-token só em desenvolvimento local")
    store, estado = Store(data_dir), {"indice": indice, "embedder": embedder}
    limite = LimiteTaxa(por_minuto)

    def con():  # leitura nova a cada chamada: pega o que o job diário gravou
        return store.connect()

    def autenticar(req: Request) -> str:
        if sem_token:
            return "dev"
        bruto = req.headers.get("authorization", "")
        tok = bruto[7:] if bruto.lower().startswith("bearer ") else req.headers.get("x-token", "")
        h = hash_token(tok) if tok else ""
        nome = next((n for k, n in tokens.items() if hmac.compare_digest(k, h)), None) if h else None
        if not nome:
            raise HTTPException(401, "token inválido")
        if not limite.permite(h):
            raise HTTPException(429, "muitas consultas; tente em um minuto")
        return nome

    def semantico_pronto():
        if estado["indice"] is None:
            from .embeddings import Indice, criar_embedder
            ind = Indice(data_dir, "e5-small").carregar()
            if not len(ind.ids):
                return None
            estado["indice"], estado["embedder"] = ind, criar_embedder("e5-small")
        return estado["indice"], estado["embedder"]

    def linha(r: dict) -> dict:
        d = r.get("decisao") or ""
        return {"id": r["id"], "citacao": r.get("citacao"), "turma": r.get("turma"), "ano": r.get("ano"),
                "assunto": r.get("assunto"), "tese_nulidade": r.get("tese_nulidade"),
                "tese_prescricao": r.get("tese_prescricao"),
                "resultado": consulta.classificar_resultado(d), "ementa": r.get("ementa"),
                "decisao": " ".join(d.split())[:500], "iguais": r.get("iguais", 1),
                "pdf": LINK + r["nome_arquivo_pdf"] if r.get("nome_arquivo_pdf") else None}

    async def saude(_):
        return JSONResponse({"ok": True})

    async def buscar(req: Request):
        autenticar(req)
        try:
            corpo = await req.json()
        except ValueError:
            raise HTTPException(400, "JSON inválido") from None
        q = str(corpo.get("q", "")).strip()
        filtros = {k: v for k, v in (corpo.get("filtros") or {}).items() if v not in (None, "")}
        if set(filtros) - FILTROS_API:
            raise HTTPException(400, "filtro inválido")
        for k in ("tese_nulidade", "tese_prescricao"):
            if k in filtros and str(filtros[k]).upper() not in TESES:
                raise HTTPException(400, f"{k} inválido")
            if k in filtros:
                filtros[k] = str(filtros[k]).upper()
        limite_n = max(1, min(int(corpo.get("limite", 20)), 50))
        modo = corpo.get("modo", "semantico")
        c = con()
        if not q:  # só filtros
            ids = [r[0] for r in c.execute(
                f"SELECT id FROM acordaos WHERE {consulta._where(filtros)[0]} ORDER BY dt_sessao DESC LIMIT {limite_n}",
                consulta._where(filtros)[1]).fetchall()]
            res = list(semantico._linhas(c, ids).values())
        elif modo == "lexico" or (modo != "lexico" and semantico_pronto() is None):
            res = semantico.buscar(c, q, filtros, limite_n, "lexico")
            modo = "lexico"
        else:
            ind, emb = semantico_pronto()
            res = semantico.buscar(c, q, filtros, limite_n, modo, ind, emb)
        completo = semantico._linhas(c, [r["id"] for r in res])  # a busca léxica devolve menos campos
        return JSONResponse({"modo": modo, "resultados": [
            linha({**completo[r["id"]], "iguais": r.get("iguais", 1)}) for r in res if r["id"] in completo]})

    async def acordao(req: Request):
        autenticar(req)
        r = consulta.obter(con(), req.path_params["id"])
        if not r:
            raise HTTPException(404, "acórdão não encontrado")
        out = linha(r)
        out.update(ementa=r.get("ementa"), decisao=r.get("decisao"), numero_processo=r.get("numero_processo"),
                   relator=r.get("relator"), dt_sessao=str(r.get("dt_sessao") or ""), teses=r.get("teses"))
        return JSONResponse(out)

    async def tendencia(req: Request):
        autenticar(req)
        g = qg.conectar(data_dir)
        trib = req.query_params.get("tributo")
        df = qg.desfecho_por(g, "ano", {"tributo": trib} if trib else None)
        return JSONResponse(json.loads(df.to_json(orient="records")))

    async def estoque(req: Request):
        autenticar(req)
        g = qg.conectar(data_dir)
        trib = req.query_params.get("tributo")
        df = qg.estoque_por(g, "fase_processual", filtros={"tributo": trib} if trib else None)
        return JSONResponse(json.loads(df.to_json(orient="records")))

    rotas = [
        Route("/api/saude", saude),
        Route("/api/buscar", buscar, methods=["POST"]),
        Route("/api/acordao/{id}", acordao),
        Route("/api/tendencia", tendencia),
        Route("/api/estoque", estoque),
    ]
    if painel_dir and Path(painel_dir).exists():
        async def raiz(_):
            return FileResponse(Path(painel_dir) / "index.html", headers={"Cache-Control": "no-store"})

        rotas += [Route("/", raiz)]
        app = Starlette(routes=rotas)
        app.mount("/", StaticFiles(directory=str(painel_dir)), name="painel")
        return app
    return Starlette(routes=rotas)


def novo_token(arquivo: Path, escritorio: str) -> str:
    """Cria um token, grava só o hash e devolve o token (mostrado uma vez)."""
    import secrets

    tok = "carf_" + secrets.token_urlsafe(32)
    t = carregar_tokens(arquivo)
    t[hash_token(tok)] = escritorio
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(t, indent=1))
    arquivo.chmod(0o600)
    return tok


def main(data_dir=None, painel=None, host="127.0.0.1", porta=8000, tokens_arquivo=None, sem_token=False):
    import uvicorn

    data_dir = Path(data_dir or config.DATA_DIR)
    app = criar_app(data_dir, painel, carregar_tokens(tokens_arquivo), sem_token)
    uvicorn.run(app, host=host, port=porta, access_log=False, log_level="warning")
