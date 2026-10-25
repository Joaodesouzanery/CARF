# Relatório de Impacto à Proteção de Dados (resumido)

> Modelo para revisão pelo controlador (escritório). Preencher o que estiver em branco.

**Operação:** coleta de acórdãos públicos do CARF, anonimização e consulta por pesquisa e estatística.
**Controlador:** ______  **Operador:** ______  **Encarregado (DPO):** ______  **Data:** ______

## Dados tratados
Texto de decisões administrativas. Podem conter: nomes de contribuintes, sócios, empregados,
advogados; CPF/CNPJ; endereços; dados financeiros e, eventualmente, dados sensíveis (saúde, em
casos de isenção por moléstia grave, p. ex.). Origem: índice público do CARF. Armazenado: só texto
anonimizado.

## Base legal e finalidade (a confirmar pelo controlador)
Tratamento de dados tornados manifestamente públicos pelo titular ou por ato do poder público,
para finalidade compatível (art. 7º, §§3º e 4º, LGPD), e exercício regular de direitos em processo
(art. 7º, VI). Dados sensíveis: art. 11, II, "d". Finalidade: pesquisa jurídica de jurisprudência.

## Riscos e mitigação
| Risco | Probabilidade | Impacto | Mitigação | Residual |
|---|---|---|---|---|
| Nome ou CPF não detectado permanece no texto | média | médio | regras + NER + propagação; amostra humana; auditoria | baixo/médio |
| Reidentificação por combinação (valor, atividade, cidade) | baixa | médio | processo e decisão são públicos; não se oferece busca por nome; sem perfilamento de PF | baixo |
| Perfilamento de relatores | média | médio | amostra mínima; agregados; rótulos neutros; uso restrito | baixo |
| Vazamento da base | baixa | médio | disco cifrado, acesso nominal, sem texto bruto | baixo |
| Envio a provedor de IA no exterior | média | médio | só texto anonimizado; contrato com o provedor; avaliar transferência internacional | médio |
| Resposta errada do modelo usada como parecer | média | alto | citação obrigatória, aviso, revisão por advogado | médio |

## Decisão
Prosseguir com as medidas acima. Revisar a cada 6 meses ou quando mudar o escopo.
