# CARF Intelligence

Coleta acórdãos públicos do CARF, anonimiza **antes de gravar**, e permite buscar (lexical,
semântica ou híbrida), medir resultados e fazer perguntas com citação da fonte. Também integra os
dados abertos oficiais de **Julgamentos** e **Estoque** de processos. Pensado para um piloto de
consultoria com escritórios tributaristas.

## Instalação
```bash
scripts/setup.sh        # Python 3.12 + dependências com as versões fixadas do NER
. .venv/bin/activate
```
O NER (spaCy + `pt_core_news_lg`) usa versões fixadas de `murmurhash`/`preshed`/`cymem`: as mais
novas quebram o carregamento do modelo (`OverflowError`). Sem NER o comando se recusa a rodar,
salvo `--sem-ner` (apenas regras e contexto; recall muito menor, não usar em produção).
Também há `Dockerfile` para rodar fora do ambiente de desenvolvimento.

## Fluxo típico
```bash
export CARF_DATA_DIR=./data

# 1) Acórdãos. Camada leve (metadados + ementa + decisão), em paralelo: ~30 min para 2023+
carf sync --ano-min 2023 --leve --workers 3      # retomável; `carf status` mostra o progresso
carf check --paginas                             # há novidade? (saída 10 = sim)
carf sync --ano-min 2023 --incremental           # traz só o que mudou (usa os mesmos filtros)
carf texto 10006836                              # voto integral de um acórdão, anonimizado

# 2) Dados abertos oficiais (sem token)
carf gerenciais atualizar --workers 3            # baixa só o que mudou (ETag/hash) e ingere; www.gov.br primeiro
carf gerenciais desfechos tributo                # resultado OFICIAL por tributo/turma/ano/tema
carf gerenciais estoque fase_processual          # acervo pendente no mês mais recente

# 3) Busca e perguntas
carf embed                                       # vetoriza ementas com o e5-small (~40 min para 85 mil)
carf search "conceito de insumo" --ano 2025      # semântica e5 (padrão); --modo hibrido p/ números e citações
carf stats turma --resultado                     # heurística sobre o texto da decisão
carf ask "Qual a tendência de provimento em PIS/COFINS?"   # requer ANTHROPIC_API_KEY

# 4) Qualidade e LGPD
carf audit                                       # regras: nada detectável pode restar
carf audit --profundo --n 300                    # detectores independentes, em amostra
carf review amostra --n 100                      # gera planilha para revisão humana
carf review pontuar revisao/amostra-....csv      # taxa de vazamento com IC de Wilson
```
Agende `carf check --paginas` (cron/CI) e, se sair com 10, rode `carf sync --incremental`
e `carf gerenciais atualizar`.

## Como funciona
- **Fonte dos acórdãos:** índice Solr público (`acordaos.economia.gov.br`), por `cursorMark`,
  pausa entre requisições (`CARF_REQUEST_DELAY`), retentativas com recuo e estado em disco.
  O campo `conteudo_txt` é só armazenado: a busca no servidor usa `_texto`. A busca principal é
  **local** de propósito: as consultas de um advogado revelam a estratégia do cliente e não devem
  ficar em log de servidor de terceiros.
- **Camada leve × texto integral:** a carga leve guarda metadados, ementa e decisão (cerca de
  1,7 mil caracteres por acórdão). O voto integral vem sob demanda (`carf texto`), anonimizado.
  Isso torna a carga ~35x mais rápida que a do texto integral (o NER é o gargalo).
- **Carga paralela:** o recorte é dividido em fatias disjuntas (ano × seção) com uma fatia residual
  por exclusão, então a partição é completa mesmo quando as facetas do Solr erram a contagem.
  Cada fatia tem estado próprio; uma fatia com erro não derruba as outras, e reexecutar retoma.
- **Atualizações:** `dt_index_tdt` é a marca-d'água. A carga grava um instantâneo *antes* de baixar.
  O limite do filtro é inclusivo e o indexador carimba lotes inteiros com o mesmo instante, então a
  incremental pula o que já está gravado na mesma versão (`id` + `dt_index`).
- **Dados oficiais:** os arquivos de Julgamentos e Estoque são downloads públicos em `www.gov.br`.
  Não há token: a API do portal dados.gov.br exige credencial, mas não é necessária. A lista de
  recursos está em `src/carf/recursos_seed.json`; URLs previsíveis (ano/semestre novo) são testadas
  a cada atualização. Anos antigos ficam em `carf.economia.gov.br` (precisa estar liberado na rede).
- **Armazenamento:** Parquet por ano de sessão; DuckDB consulta com deduplicação por `id`.
- **Qualidade dos dados:** datas de sessão absurdas (ano -19, +191993) e anos como "0199" são
  descartados e sinalizados em `qualidade`. Campos multivalorados do Solr são normalizados.

## Anonimização (camadas)
1. **Regras determinísticas** com validação de dígitos (CPF/CNPJ). Números de processo (todas as
   variantes de formatação) e de decisão são protegidos. Conta bancária só com contexto de banco.
2. **NER em português** para nomes, com: filtro de vocabulário jurídico; **vocabulário comum
   derivado do corpus** (palavra que aparece em minúscula em muitos acórdãos não é nome);
   aparo de títulos; propagação de sobrenomes soltos; **preservação de agentes públicos**
   (relatores da base, quem vem após título judicial, quem é seguido de "Presidente"/"Redator").
3. **Auditoria** (`carf audit`, `--profundo`) e **revisão humana** de amostra. Detalhes e limites em
   `docs/lgpd/`.

## Medições (dados reais)
- **Cobertura:** a carga leve de 2023+ trouxe 85.710 acórdãos distintos, igual ao `numFound` do
  índice, e as contagens por ano batem com o índice. O índice tem 19.691 acórdãos+resoluções em
  2025 contra 19.525 no CSV oficial (+0,85%); as 2.385 resoluções batem exatamente com o PDF gerencial.
- **Classificação de resultado × resultado oficial** (`scripts/avaliar_resultado.py`, decisões com um
  único recurso, 2025, três amostras separadas, a terceira não vista durante o ajuste): "OUTRO" entre
  0,9% e 4,6%; acurácia geral entre 92,7% e 97,6%; quando decide, entre 97,8% e 98,6%.
  Quando o ano tem CSV oficial, **use o resultado oficial** (`carf gerenciais desfechos`).
- **Anonimização de nomes:** NER sem filtros ~40 máscaras/doc (muitas indevidas: PIS, COFINS,
  "ônus da prova"); com os filtros e o vocabulário do corpus, em ementa+decisão: 12 máscaras em
  300 acórdãos (0,18 por mil palavras), quase todas pessoas ou empresas; 2.006 menções a agentes
  públicos preservadas. **Taxa de vazamento real:** depende da revisão humana (pendente).
- **Busca** (`scripts/julgamento_busca.py`; 20 consultas conceituais, 548 acórdãos julgados por IA às
  cegas quanto ao método; P@8 / nDCG@8): **e5 semântica 0,96 / 0,95**; e5 híbrida 0,83 / 0,81; spaCy
  semântica 0,78 / 0,55; léxica ingênua (qualquer termo, não é BM25) 0,33 / 0,21. Cerca de 16% do top-8
  é ementa repetida (recursos repetitivos): os resultados agrupam ementas idênticas (`iguais`).
- **Qualidade dos dados oficiais:** o rótulo de tributo muda entre anos ("COFINS" x "COFINS - CONTRIBUIÇÃO
  PARA O FINANCIAMENTO..."); fica a sigla normalizada (`tributo`) e o original (`tributo_original`).
  Até 2017 há muitos "não informado" (~48 mil registros no total).
- **Pré-revisão por IA de 100 acórdãos** (antes da correção das listas de nomes): 1 vazamento (2 nomes) em
  100 documentos (IC 95%: 0,2% a 5,4%), já corrigido. **Não substitui a revisão humana.**
- **Desempenho:** texto integral ~0,7 s/doc/processo; camada leve ~50 docs/s com 3 processos.

## Limitações
- A anonimização reduz risco, **não o elimina**. `carf audit` usa as mesmas regras e o auditor
  profundo usa NER do mesmo tipo: servem para achar regressões, não provam ausência de dado pessoal.
- Nomes de doutrinadores, advogados e empresas com nome de pessoa podem ser mascarados;
  agentes públicos não listados e sem título podem ser mascarados.
- Busca semântica: avaliada com julgamento de relevância feito por IA (aproximação). O advogado deve
  validar uma amostra (`revisao/busca-julgamento.csv`). O tema oficial (`concentracao_tematica`) não
  serve de gabarito: classifica o tipo de lançamento, não o assunto da ementa. O e5 precisa dos hosts
  `huggingface.co`, `cas-server.xethub.hf.co` e `us.aws.cdn.hf.co` liberados na primeira execução.
- Os textos livres dos CSVs oficiais (ementa, decisão) não são guardados (minimização).
- `carf ask` foi testado com cliente falso (laço de ferramentas, erros, limite de turnos), mas não
  contra a API real (falta a chave).
- Resultado heurístico (anos sem CSV oficial): vale a taxa acima; MISTO/OUTRO são abstenções.

## Testes
```bash
pytest          # 151 testes, sem rede
ruff check src tests scripts
```
