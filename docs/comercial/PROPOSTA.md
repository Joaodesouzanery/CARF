# Proposta: inteligência de jurisprudência do CARF para o escritório

**Minuta para discussão. Valores são hipóteses a validar com o escritório. Revise com o jurídico antes de enviar.**

## O problema
A pesquisa de jurisprudência no site do CARF é lenta: o advogado busca por palavras, abre acórdão por acórdão e lê
para descobrir como os conselheiros decidem temas parecidos. Uma pergunta como "acórdãos que acolheram nulidade em
classificação fiscal" leva horas.

## O que entregamos
1. **Painel de pesquisa** (web, acesso por token do escritório): busca por palavras ou por significado, com filtros de
   matéria, tese (nulidade e prescrição acolhidas ou rejeitadas), colegiado, ano e resultado. Cada resultado traz a
   citação completa, o trecho da decisão e o link do PDF oficial.
2. **Tendências oficiais**: taxa de provimento, desprovimento e não conhecimento por tributo, ano e colegiado, a partir
   dos dados abertos do CARF.
3. **Boletim mensal** por tema escolhido pelo escritório: o que mudou, quais turmas decidem de que forma, decisões novas
   relevantes, com fonte em cada afirmação.
4. **Pesquisa sob demanda** (planos com análise): o consultor responde a uma pergunta de jurisprudência e entrega um
   relatório com os acórdãos, a leitura por colegiado e as ressalvas.

## Como tratamos dados pessoais (LGPD)
- A base usa só acórdãos públicos e é **anonimizada antes de ser gravada**: CPF, CNPJ, endereços e nomes de pessoas físicas
  são mascarados. Nomes de conselheiros e relatores são mantidos (agentes públicos no exercício da função).
- Medimos a taxa de vazamento em amostra revisada por pessoas e publicamos o resultado e o limite de confiança.
  A anonimização reduz o risco, não o elimina.
- **O texto das consultas não é registrado.** O que o advogado pesquisa revela a estratégia do cliente.
- O consultor atua como operador de dados do escritório (controlador); o contrato inclui o acordo de tratamento de dados
  (`docs/lgpd/MODELO_DPA.md`) e o relatório de impacto (`docs/lgpd/RIPD.md`).

## Limites que o escritório deve conhecer
- A leitura de tese e de resultado é **automática** e pode errar; o painel mostra "indefinida" quando os sinais se
  contradizem e sempre exibe o trecho da decisão para conferência.
- A base cobre os acórdãos publicados no índice do CARF de 2018 em diante; o voto integral vem sob demanda.
- Não é parecer jurídico nem substitui a leitura do acórdão.

## Planos (hipótese de preço, a validar)
| | Essencial | Profissional | Parceiro |
|---|---|---|---|
| Painel e API, tokens | até 5 usuários | até 15 usuários | ilimitado |
| Boletim | trimestral, 1 tema | mensal, 2 temas | mensal, até 5 temas |
| Pesquisas sob demanda | 0 | 2 por mês | 6 por mês, prazo de 48 h |
| Reunião de acompanhamento | | trimestral | mensal |
| Mensalidade sugerida | R$ 1.500 a 2.500 | R$ 4.000 a 6.000 | R$ 8.000 a 12.000 |

Pesquisa avulsa fora do plano: sugestão de R$ 800 a 1.500 por pergunta. Implantação (carga, ajuste de temas,
treinamento): sugestão de R$ 3.000 a 5.000, uma vez.

## Piloto de 30 dias
Sem custo ou com valor simbólico: o escritório escolhe **3 perguntas reais** de jurisprudência, o painel e o consultor
respondem, e comparamos com o tempo que levaria no site do CARF. Sucesso = pelo menos 2 das 3 respondidas com acórdãos
úteis em menos de 1/5 do tempo.

## Próximos passos
1. Reunião de 45 minutos (roteiro em `CHECKLIST_REUNIAO.md`).
2. Assinatura do contrato e do acordo de tratamento de dados.
3. Escolha dos 3 temas e das perguntas do piloto.
4. Entrega do token e treinamento de 30 minutos.
