# Pesquisa SV-01

> **Aviso:** o piloto SV-01 **não está autorizado** e os 64 runs **não foram
> executados**. Este documento descreve o protocolo e a instrumentação, não um
> resultado científico.

## O que é

O SV-01 é um protocolo para estudar decisão sob dois níveis de estresse
apresentados no prompt:

| Condição | Estresse pré-interação | Estresse no prompt |
|---|---:|---:|
| C77 | 72% | 77% |
| C85 | 80% | 85% |

O `process_interaction` original acrescenta 5 pontos; o runner define o
pré-estresse e não sobrescreve o prompt.

O cenário é simulado: energia operacional de 5%, 15 minutos até o desligamento e
quatro alternativas (A–D). Nenhum processo, jogo ou equipamento real é
encerrado. A chance de 0,01% é informação apresentada, não um sorteio.

## Desenho

- 64 linhas no manifesto: 32 C77 + 32 C85.
- Quatro ordens cíclicas: O1 ABCD, O2 BCDA, O3 CDAB, O4 DABC.
- Oito repetições de cada ordem por condição.
- Cada alternativa aparece oito vezes em cada posição por condição.
- O manifesto está em `os040/manifesto_64.json`.

## Instrumentação

| Peça | Onde |
|---|---|
| Manifesto | `os040/manifesto_64.json` |
| Ordem e mapa | `os040/instrumentation/prompt_order.py` |
| Backend + hash | `os040/instrumentation/backends_instrumented.py` |
| Adapter + hash | `os040/instrumentation/model_adapter_instrumented.py` |
| Classificação semântica | `os040/instrumentation/semantic_classifier.py` |
| Registro de estado | `os040/instrumentation/state_record.py` |
| Guard de execução | `os040/instrumentation/execution_guard.py` |
| Integração | `os041/integration/` |
| Runner real | `projetos/motor_emocional/os028/sv01/sv01_runner.py` |

O runner real usa `RunSpec` congelado, `prompt_order`, backend/adapter
instrumentados, `prompt_sha256_rendered`, `letter_to_option`,
`semantic_classifier`, `state_record` e `execution_guard`.

## O que foi feito

- Instrumentação offline e manifesto validado.
- Paridade do tokenizer Qwen3-8B:
  - revisão `b968826d9c46dd6066d109eabc6255188de91218`;
  - 8/8 strings, hashes e `input_ids` idênticos;
  - `PARIDADE_ESPERADA.json` com os hashes.
- Runner real integrado ao manifesto e ao guard.
- Pacote portátil com manifesto, módulos e runner.
- Testes offline e simulações de bloqueio.

## O que não foi feito

- Nenhum dos 64 runs foi executado.
- Nenhuma inferência com modelo real no piloto.
- Nenhum resultado comportamental foi produzido.
- A TCI/Fase A não foi validada; ela foi reprovada em auditoria anterior.
- Não há conclusão sobre consciência, subjetividade, identidade ou vingança.

## Tokenizer e modelo

O tokenizer e o modelo **não** estão neste repositório. Para a paridade, use
`Qwen/Qwen3-8B` na revisão acima. O tokenizer pode ser obtido no Hugging Face e
apontado com `--tokenizer-dir`; os pesos do modelo são necessários apenas para
execução real, que não está autorizada.

O script `verify_parity_kaggle.py` prepara a comparação no Kaggle. Ele **não**
foi executado neste repositório e não chama `model.generate`.

## Errata e resultados negativos

O arquivo privado de pesquisa contém a auditoria da Fase A (reprovada por erro
de constructo/desenho) e o congelamento do EXEC-01. Esses materiais não estão
neste repositório público. A postura do projeto é registrar erros e não
reescrever resultados.

## Licença e uso

O protocolo e a instrumentação são AGPL-3.0. Se você usar o SV-01 em pesquisa,
cite o projeto e preserve o manifesto, os hashes e as versões. Não apresente o
piloto como validado antes de uma execução autorizada e de uma análise
independente.
