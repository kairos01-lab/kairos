# Contribuindo com o Kairós

Obrigado pelo interesse. Este é um alpha de pesquisa; contribuições pequenas e
bem explicadas são mais úteis do que grandes refatorações sem contexto.

## Antes de abrir um PR

1. Abra uma issue descrevendo o problema ou a ideia.
2. Rode os testes:

```bash
python -m unittest discover -s tests -v
```

3. Verifique se você não incluiu segredos, dados pessoais, resultados brutos,
   modelos ou binários grandes.
4. Mantenha o escopo: uma mudança por PR.

## Estilo

- Python 3.11+; siga o estilo do arquivo que está editando.
- Não altere a lógica experimental do SV-01 sem uma issue e revisão.
- Não renomeie campos do `state_record` ou do manifesto sem discussão.
- Prefira mensagens claras em português ou inglês; o código atual usa português.

## Licença

Ao contribuir, você concorda que sua contribuição será licenciada sob a
**AGPL-3.0**, salvo acordo separado. Não envie código de terceiros sem licença
compatível.

## Conduta

Leia `CODE_OF_CONDUCT.md`.
