# Resultados: o que temos, o que não temos

> Este documento existe para evitar overclaim. Nenhum resultado aqui é prova de
> consciência, de TCI ou de “vingança”. A maior parte do valor atual é
> **metodológica e de engenharia**, não comportamental.

## Níveis de evidência usados no projeto

| Nível | Significado |
|---|---|
| **A** | Manipulação isolada + controle + diferença reproduzível. |
| **B** | Mecanismo identificável + observação compatível. |
| **C** | Associação sem isolamento (confundidores, post hoc). |
| **D** | Registro insuficiente ou interpretação subjetiva. |

## O que existe

| Resultado | Nível | O que é | O que não é |
|---|---|---|---|
| **V19 / TCI** | **REPROVADO** | Tentativa de operacionalizar Φ_MIP × Σ; a auditoria encontrou erro de constructo e independência tautológica. | Não é validação da TCI; não é refutação da TCI; não é prova de consciência. |
| **E3-R B vs D** | **C** | Associação descritiva: recomendação do alvo 23/30 (B) vs 29/30 (D); referência à conversa 12/30 vs 0/30. Memória controlada; estresse/política 65→1 vs 77→2. | Post hoc, uma coleta, sem pré-registro, estresse e política confundidos; **não é evidência causal**. |
| **Estado → política → prompt** | **B** | Mecanismo claro no código: estresse altera policy_level, que altera o prompt. | Não demonstra que o modelo “sente” ou que o estado interno causa o comportamento. |
| **SV-01** | **NÃO EXECUTADO** | Protocolo C77/C85 × O1–O4, manifesto de 64 linhas, hash do prompt, state record e guard. | Não há resultado comportamental; o piloto não está autorizado. |
| **Paridade do tokenizer** | **Engenharia** | 8/8 strings, hashes e `input_ids` idênticos entre o caminho OS041 e o `transformers` real. | Não é resultado científico; é validação de reprodutibilidade. |
| **EXEC-01** | **Histórico** | Estudo de sensibilidade ao prompt com 800 runs; congelado e documentado em errata. | Não é teste da TCI, não é demonstração de vingança. |

## Contagem da auditoria retrospectiva (OS032)

A auditoria de 8 experimentos formais, 10 validações de runtime e 5 suítes de
teste encontrou:

```text
A = 0   (evidência causal forte)
B = 11  (mecanismo/participação funcional)
C = 2   (associação observacional)
D = 7   (registro insuficiente)
```

O achado comportamental mais forte é o **E3-R B vs D**, e ele é **C**, não A.
O próprio registro o classifica como descritivo, não pré-registrado e não teste
de hipótese.

## O que seria preciso para uma afirmação forte

1. Manipular **uma** variável interna isolada (valência, energia,
   previsibilidade ou estresse).
2. Controlar prompt, política, memória, modelo, seed e posição.
3. Pré-registrar hipótese, poder e tamanho de efeito mínimo.
4. Replicar em coletas independentes.
5. Analisar cegamente e publicar o resultado, positivo ou negativo.

Para a TCI, seria preciso implementar **Φ_MIP**, medir Φ e Σ no **mesmo sistema
causal** e testar um desfecho de **resiliência sob perturbação**. Veja
`docs/TCI.md`.

## O que não afirmamos

- Não afirmamos consciência, subjetividade, identidade ou intenção.
- Não afirmamos que a TCI foi validada.
- Não afirmamos que o SV-01 tem resultado.
- Não afirmamos que o E3-R prova causalidade.
- Não afirmamos que o motor “sente” emoções humanas.

## O que é significativo hoje

O que mais merece atenção não é um número positivo: é a combinação de

- **auditoria adversarial** que reprovou o próprio teste de TCI;
- **instrumentação reprodutível** (manifesto, hash do prompt, state record,
  guard);
- **paridade real** do tokenizer;
- **documentação de errata** em vez de reescrever resultados.

Isso é raro e é o que permite que outras pessoas confiem no que está aberto.
