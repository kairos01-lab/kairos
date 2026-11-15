# Contribuindo com o Kairós

Obrigado pelo interesse. Este é um alpha de pesquisa; contribuições pequenas e
bem explicadas são mais úteis do que grandes refatorações sem contexto.

## Antes de abrir um PR

1. Abra uma issue descrevendo o problema ou a ideia.
2. Rode os testes relevantes:

```bash
python -m unittest discover -s tests -v
```

3. Verifique se você não incluiu segredos, dados pessoais, resultados brutos,
   modelos, binários grandes ou chaves privadas.
4. Mantenha o escopo: uma mudança por PR.

## Estilo

- Python 3.11+; siga o estilo do arquivo que está editando.
- Não altere a lógica experimental do SV-01 sem uma issue e revisão.
- Não renomeie campos do `state_record` ou do manifesto sem discussão.
- Prefira mensagens claras em português ou inglês; o código atual usa português.

## Licença do projeto

O projeto é distribuído sob **GNU Affero General Public License v3, SPDX
`AGPL-3.0-only`** (`LICENSE`). Ao contribuir, você concorda que sua contribuição
será distribuída sob essa licença.

Não há exigência de CLA (Contributor License Agreement) neste momento. DCO não
é transferência automática de direitos autorais.

## Developer Certificate of Origin (DCO)

Cada contribuidor confirma que:

- criou a contribuição e tem direito de submetê-la; ou
- recebeu autorização adequada para submetê-la;
- identificou código e materiais de terceiros;
- informou quando utilizou código gerado ou assistido por ferramentas de IA;
- não está introduzindo material incompatível com a licença do projeto;
- aceita que a contribuição seja distribuída sob `AGPL-3.0-only`, conforme
  aplicável.

Assine seus commits com `Signed-off-by`:

```text
Signed-off-by: Nome do Colaborador <email@example.com>
```

Use:

```bash
git commit -s
```

O signatário deve ser realmente a pessoa que está confirmando a contribuição.
Não assine commits antigos retroativamente. Não crie commits apenas para
“consertar” sign-off sem revisão.

## Declaração de origem

No PR, informe:

- se o código é autoral, derivado ou de terceiro;
- a licença de qualquer arquivo de terceiro;
- se houve uso de IA e em qual etapa;
- os testes executados;
- se há dados sensíveis ou segredos (não deve haver).

## Código e materiais de terceiros

Não envie código de terceiros sem licença compatível. Preserve copyright,
licença e avisos originais. Registre o componente em
`THIRD_PARTY_LICENSES.md` ou no inventário indicado pelo mantenedor.

Se a licença for desconhecida ou incompatível, a contribuição deve ser
bloqueada até avaliação.

## Contribuições assistidas por IA

Declare se houve uso de IA e em qual etapa (código, teste, documentação). Você
continua responsável por revisar o resultado, verificar licenças e garantir que
tem direito de submeter o material. A IA não é autora legal.

## Checklist do PR

- [ ] Issue/escopo descrito.
- [ ] Testes executados.
- [ ] `Signed-off-by` presente.
- [ ] Origem do código declarada.
- [ ] Terceiros/licenças identificados.
- [ ] Uso de IA declarado, se aplicável.
- [ ] Sem segredos, chaves privadas, dados pessoais ou binários grandes.
- [ ] Licença do projeto respeitada (`AGPL-3.0-only`).

## Conduta

Leia `CODE_OF_CONDUCT.md`.
