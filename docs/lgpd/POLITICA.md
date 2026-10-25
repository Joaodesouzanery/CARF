# Política de tratamento de dados (LGPD)

> Modelo técnico-operacional. **Não é parecer jurídico**: deve ser revisado e adotado pelo
> jurídico do escritório contratante antes do uso com clientes.

## 1. Papéis
- **Escritório (controlador):** decide finalidades e meios; responde perante titulares e ANPD.
- **Consultoria (operador):** trata dados somente conforme instruções documentadas no contrato (DPA).
- **Fontes:** acórdãos publicados pelo CARF (acesso público). Não se trata nenhum dado de cliente
  do escritório nesta base; processos e dados de clientes ficam em ambiente separado e só entram
  por decisão do controlador e em contrato próprio.

## 2. Finalidade e necessidade
Pesquisa de jurisprudência e estatística de julgamento para atuação em contencioso tributário.
Fora do escopo: identificar, listar ou perfilar contribuintes pessoa física; avaliar pessoas.
Dado público não é dado livre: a finalidade e a minimização continuam exigíveis.

## 3. O que o sistema faz (controles implementados no código)
| Controle | Onde |
|---|---|
| Identificadores diretos mascarados antes de gravar (CPF, CNPJ, e-mail, telefone, CEP, RG, título de eleitor, CNH, PIS/NIT, conta bancária, placa) | `privacy/rules.py` |
| Nomes de pessoas físicas mascarados (NER + regras de contexto + propagação de sobrenome) | `privacy/ner.py` |
| Agentes públicos preservados: relatores (lista oficial do índice) e quem vem após título judicial (ministro, conselheiro, desembargador, juiz, relator) | `privacy/ner.py` |
| Texto bruto **nunca** gravado em disco; só o texto limpo | `sync.py` |
| Números de processo e de decisão preservados (públicos; necessários para citação) | `privacy/rules.py` |
| Estatística por relator só com amostra mínima (30 acórdãos) | `qa/consulta.py` |
| O modelo de linguagem recebe apenas texto já anonimizado | `qa/ask.py` |
| Auditoria da base (`carf audit`, código de saída 1 se achar resíduo) | `auditoria.py` |

## 4. Limites conhecidos (informar ao controlador)
- A anonimização reduz risco, **não o elimina**. Nenhum método é infalível; há falsos negativos
  (ex.: nome próprio único sem contexto, apelidos, nomes em tabelas ou OCR ruim) e falsos
  positivos (palavras comuns mascaradas).
- Nomes de autores de doutrina, advogados e empresas com nome de pessoa também são mascarados
  (opção conservadora).
- Conta bancária só é mascarada com contexto bancário próximo ("agência", "c/c", nome de banco).
- `carf audit` usa as mesmas regras da anonimização: serve para detectar regressão, **não prova**
  ausência de dado pessoal. A qualidade é medida por amostragem humana (seção 6).
- A classificação de resultado (provido/negado/...) é heurística sobre o texto da decisão.

## 5. Relatores e conselheiros
Atuação em julgamento é pública. Mesmo assim: apresentar apenas estatísticas agregadas de
julgamento, com amostra mínima, rótulos neutros, sem inferir características pessoais e sem
juízo de valor. Nunca usar para pressionar ou expor agente público.

## 6. Controle de qualidade (antes de cada entrega a cliente)
1. `carf audit` sem resíduos.
2. Amostra aleatória de 100 documentos revisada por pessoa: contar nomes de pessoas físicas
   remanescentes e identificadores. Registrar a taxa em `REGISTRO_OPERACOES.md`.
3. Se a taxa de vazamento passar do limite acordado com o escritório, suspender a entrega e
   ajustar regras/modelo.

## 7. Segurança
Disco cifrado; segredos em variáveis de ambiente (nunca no repositório); acesso por usuário
nominal com log; `data/` fora do controle de versão; backups cifrados; retenção definida no DPA.

## 8. Incidentes e direitos dos titulares
Comunicar o controlador sem demora (prazo no DPA). Pedidos de titulares são encaminhados ao
controlador; a exclusão de um documento é feita por `id` e registrada.

## 9. Relatórios ao cliente final
Todo relatório leva o aviso: "Ferramenta de apoio à pesquisa; não constitui parecer jurídico nem
previsão de resultado." Citar sempre a fonte (acórdão, processo, turma, data).
