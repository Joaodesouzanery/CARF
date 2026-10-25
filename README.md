# CARF Intelligence

Coleta acórdãos públicos do CARF, anonimiza antes de gravar e permite buscar, medir e fazer
perguntas com citação da fonte. Pensado para um piloto de consultoria com escritórios tributaristas.

## Instalação
```bash
uv venv --python 3.12 .venv && . .venv/bin/activate
uv pip install -e ".[ner,ask,dev]"      # Python 3.11 ou 3.12
```
O NER (spaCy + `pt_core_news_lg`) usa versões fixadas de `murmurhash`/`preshed`/`cymem`: as mais
novas quebram o carregamento do modelo (`OverflowError`). Sem NER o comando se recusa a rodar,
salvo `--sem-ner` (apenas regras e contexto; recall muito menor, não usar em produção).

## Uso
```bash
export CARF_DATA_DIR=./data

carf sync --ano-min 2023            # carga completa do recorte (retoma sozinha se interrompida)
carf sync --ano-min 2023 --incremental   # só o que foi indexado depois da última carga
carf check --paginas                # há novidade? (saída 10 = sim) e vigia os PDFs gerenciais
carf search "glosa despesas operacionais" --ano 2024
carf stats turma --resultado        # distribuição de resultados (heurística)
carf audit                          # varre a base atrás de identificadores
carf ask "Qual a tendência de provimento em PIS/COFINS insumos?"   # requer ANTHROPIC_API_KEY
```
Agende `carf check` (cron ou CI) e, se sair com 10, rode `carf sync --incremental`.

## Como funciona
- **Fonte:** índice Solr público de acórdãos (`acordaos.economia.gov.br`). Sincronização por
  `cursorMark`, pausa entre requisições (`CARF_REQUEST_DELAY`, padrão 0,7 s), retentativas com
  recuo exponencial e estado em `data/state.json`.
- **Atualizações:** `dt_index_tdt` (momento da indexação) é a marca-d'água. A carga completa grava
  um instantâneo *antes* de baixar, para nada indexado durante a carga se perder. O limite do
  filtro é inclusivo e o indexador carimba lotes inteiros com o mesmo instante, então a
  incremental pula o que já está gravado na mesma versão (`id` + `dt_index`).
- **Armazenamento:** Parquet por ano de sessão; DuckDB consulta com deduplicação por `id`
  (`carf compact` remove versões antigas).
- **Qualidade dos dados:** datas de sessão absurdas (ano -19, +191993) e anos como "0199" são
  descartados e sinalizados na coluna `qualidade`.
- **PDF gerencial:** o monitor baixa o PDF de dados abertos gerenciais, guarda o hash e a data
  "Atualização da apresentação" (via `pdftotext`, se instalado).

## Anonimização (camadas)
1. Regras determinísticas com validação de dígitos (CPF/CNPJ); números de processo e decisão protegidos.
2. NER em português para nomes, com filtro de vocabulário jurídico, aparo de títulos,
   propagação de sobrenomes soltos e preservação de agentes públicos.
3. Auditoria posterior e amostra humana. Detalhes e limites em `docs/lgpd/`.

## Medições (dados reais, ver `docs/lgpd/REGISTRO_OPERACOES.md`)
- NER sem filtros: ~40 máscaras de nome por documento, com muitos falsos positivos (PIS, COFINS,
  "ônus da prova"). Com os filtros: ~6 por documento, majoritariamente pessoas e empresas.
- **Desempenho:** ~0,7 s por documento (NER é o gargalo; 1 processo). O recorte 2023+ (85.710 docs)
  levaria cerca de 16 h e o índice inteiro (587.779) cerca de 5 dias. Para escalar: paralelizar
  em vários processos/máquinas ou começar por um recorte por matéria/seção.
- **Conferência com o PDF gerencial 2026-09:** acórdãos + resoluções por ano do PDF ficam 3–5%
  abaixo da contagem do índice (ex. 2023: 19.358 + 1.946 = 21.304 vs 22.477), o que indica
  cobertura consistente; a diferença não foi explicada.

## Limitações
- Resultado (provido/negado/parcial) é heurística sobre o texto; entre 0% e ~40% cai em "OUTRO" conforme a turma (amostra de 400 acórdãos).
- Não há busca semântica ainda (a busca exige todos os termos). Próximo passo natural.
- Os conjuntos "Julgamentos" e "Estoque" do dados.gov.br não foram integrados: a API exige token.
- `carf ask` não foi exercitado contra a API real (só o despacho das ferramentas é testado).

## Testes
```bash
pytest          # 69 testes, sem rede
ruff check src tests
```
