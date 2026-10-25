# Registro de operações de tratamento

| Data | Operação | Escopo | Base | Responsável | Resultado / observações |
|---|---|---|---|---|---|
| 2026-10-25 | Teste de carga com NER (600 docs, sessões ≥ 2023) | desenvolvimento | pesquisa | consultoria | auditoria sem resíduos por regra; 40 docs amostrados ~6 máscaras de nome/doc |
| 2026-10-25 | Carga leve 2023+ (85.710 acórdãos), anonimizador com vocabulário do corpus | desenvolvimento | pesquisa | consultoria | contagem = numFound do índice; `carf audit` sem resíduos |
| 2026-10-25 | Auditoria profunda (300 acórdãos), com relatores da base como agentes públicos | desenvolvimento | pesquisa | consultoria | 1/300 com candidato (dígitos, não nome); sem prova de ausência: ver Limites |
| 2026-10-25 | Medição de máscaras de nome em 300 acórdãos (ementa+decisão) | desenvolvimento | pesquisa | consultoria | 12 máscaras (0,18/1000 palavras); 2.006 menções a agentes públicos preservadas |
| 2026-10-25 | Pré-revisão por IA de 100 acórdãos (texto anonimizado completo) | desenvolvimento | pesquisa | consultoria | 13 máscaras (0 em contribuinte PF); 1 vazamento (2 nomes, "Srs. ... e ..."), regra de contexto corrigida e base reconstruída; NÃO é revisão humana |
| 2026-10-25 | Textos livres dos CSVs oficiais deixam de ser guardados | desenvolvimento | minimização | consultoria | ementa/decisão dos CSVs não são necessárias; a ementa vem do índice, anonimizada |
| | | | | | |

## Controle de qualidade por amostra humana
| Data | Lote | Amostra | Nomes de PF remanescentes | Identificadores remanescentes | Aprovado? |
|---|---|---|---|---|---|
| | | | | | |
