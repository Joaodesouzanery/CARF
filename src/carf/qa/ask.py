"""Perguntas em linguagem natural: o modelo só enxerga texto já anonimizado, via ferramentas."""

import json
import os
from datetime import date, datetime

from . import consulta
from . import gerenciais as ger_mod
from . import semantico as sem_mod

MODELO = os.environ.get("CARF_MODEL", "claude-sonnet-5-5")

SYSTEM = """Você é um assistente de pesquisa de jurisprudência do CARF para advogados tributaristas.
Regras:
- Responda apenas com base nos resultados das ferramentas. Se não houver base, diga que não encontrou.
- Cite cada afirmação jurídica com a citação devolvida pela ferramenta (número do acórdão, processo,
  turma, data). Nunca invente números, ementas ou resultados.
- Para taxas de provimento/negativa prefira `desfecho_oficial` (dado aberto oficial do CARF, só
  disponível para os anos carregados). `taxa_resultado` é heurística sobre o texto da decisão:
  sinalize essa limitação. `estoque` traz o acervo pendente por mês.
- Para perguntas conceituais use `buscar_semantico`; para termos exatos, `buscar_acordaos`.
- Não tente identificar contribuintes pessoa física; o texto vem anonimizado e deve permanecer assim.
- Isto é apoio à pesquisa, não parecer jurídico nem previsão de resultado."""

TOOLS = [
    {"name": "buscar_acordaos",
     "description": "Busca acórdãos por termos (todos devem aparecer). Retorna ementa e citação.",
     "input_schema": {"type": "object", "properties": {
         "termos": {"type": "string"},
         "filtros": {"type": "object", "description": "ano, turma, camara, secao, relator"},
         "limite": {"type": "integer", "default": 8}}, "required": ["termos"]}},
    {"name": "buscar_semantico",
     "description": "Busca por significado (híbrida: semântica + palavras). Use para perguntas "
                    "conceituais. Retorna ementa e citação.",
     "input_schema": {"type": "object", "properties": {
         "consulta": {"type": "string"},
         "filtros": {"type": "object", "description": "ano, turma, camara, secao, relator"},
         "limite": {"type": "integer", "default": 8}}, "required": ["consulta"]}},
    {"name": "desfecho_oficial",
     "description": "Resultado OFICIAL dos julgamentos (dado aberto) por tributo, turma, ano, "
                    "concentracao_tematica, tipo_recurso ou votacao.",
     "input_schema": {"type": "object", "properties": {
         "por": {"type": "string"}, "filtros": {"type": "object"}}, "required": ["por"]}},
    {"name": "estoque",
     "description": "Processos em estoque no CARF (mês mais recente) por tributo, fase_processual, "
                    "instancia, tipo_contribuinte ou concentracao_tematica.",
     "input_schema": {"type": "object", "properties": {"por": {"type": "string"}}, "required": ["por"]}},
    {"name": "obter_acordao",
     "description": "Retorna um acórdão completo (anonimizado) pelo id.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "contagem",
     "description": "Conta acórdãos por ano, turma, camara, secao ou relator.",
     "input_schema": {"type": "object", "properties": {
         "por": {"type": "string"}, "filtros": {"type": "object"}}, "required": ["por"]}},
    {"name": "taxa_resultado",
     "description": "Distribuição de resultados (provido, negado, parcial...) por dimensão; "
                    "opcionalmente só ementas que contenham um termo. Heurística.",
     "input_schema": {"type": "object", "properties": {
         "por": {"type": "string"}, "filtros": {"type": "object"}, "termo": {"type": "string"}},
         "required": ["por"]}},
]


def _json(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def executar(con, nome: str, args: dict, ger=None, sem=None) -> str:
    """`ger`: conexão dos dados oficiais; `sem`: (indice, embedder) da busca semântica."""
    try:
        if nome == "buscar_semantico":
            if sem is None:
                return json.dumps({"erro": "busca semântica indisponível: gere os vetores com `carf embed`"})
            r = sem_mod.buscar(con, args["consulta"], args.get("filtros"), min(args.get("limite", 8), 20),
                               "hibrido", sem[0], sem[1])
        elif nome in ("desfecho_oficial", "estoque"):
            if ger is None:
                return json.dumps({"erro": "dados oficiais indisponíveis: rode `carf gerenciais atualizar`"})
            if nome == "desfecho_oficial":
                r = ger_mod.desfecho_por(ger, args["por"], args.get("filtros")).head(50).to_dict("records")
            else:
                df = ger_mod.estoque_por(ger, args["por"])
                r = {"referencia": df.attrs["referencia"], "linhas": df.head(50).to_dict("records")}
        elif nome == "buscar_acordaos":
            r = consulta.buscar(con, args["termos"], args.get("filtros"), min(args.get("limite", 8), 20))
        elif nome == "obter_acordao":
            r = consulta.obter(con, args["id"])
            if r:
                r["conteudo"] = (r.get("conteudo") or "")[:12000]
        elif nome == "contagem":
            r = consulta.contagem(con, args["por"], args.get("filtros")).head(50).to_dict("records")
        elif nome == "taxa_resultado":
            r = consulta.taxa_resultado(con, args["por"], args.get("filtros"), args.get("termo")
                                        ).head(50).to_dict("records")
        else:
            return json.dumps({"erro": f"ferramenta desconhecida: {nome}"})
        return json.dumps(r, default=_json, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001  devolve o erro ao modelo para ele corrigir a chamada
        return json.dumps({"erro": str(exc)}, ensure_ascii=False)


def perguntar(con, pergunta: str, cliente=None, modelo=MODELO, max_turnos=8, ger=None, sem=None) -> str:
    if cliente is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("Defina ANTHROPIC_API_KEY para usar `carf ask`.")
        import anthropic

        cliente = anthropic.Anthropic()
    msgs = [{"role": "user", "content": pergunta}]
    for _ in range(max_turnos):
        resp = cliente.messages.create(
            model=modelo, max_tokens=2500, system=SYSTEM, tools=TOOLS, messages=msgs)
        msgs.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id, "content": executar(con, b.name, b.input, ger, sem)}
            for b in resp.content if b.type == "tool_use"]})
    return "Limite de passos atingido sem resposta final."
