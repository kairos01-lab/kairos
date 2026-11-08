# Status do alpha

**Data:** 2026-11-08
**Versão:** 0.1.0-alpha
**Licença:** AGPL-3.0

## Validado localmente

| Item | Resultado |
|---|---|
| Demo `examples/demo_fake_cortex.py` | OK, sem modelo/GPU/rede |
| Testes básicos | 12/12 OK |
| Guard sem autorização | bloqueado |
| Guard com token antigo | bloqueado |
| Guard com argumento legado | bloqueado |
| Flags antigas (`--model/--experiment`) | rejeitadas |
| Varredura simples de segredos | nenhum segredo óbvio |
| Fonte do guarda-costas Rust | incluída (binário não) |

O demo mostra o fluxo completo: estado emocional -> estresse -> política ->
prompt -> resposta -> registro. Ele usa córtex e guarda falsos, então não há
inferência nem controle de processos reais.

## Não validado / pendente

- Publicação no GitHub (nenhum remoto criado).
- Paridade do tokenizer no Kaggle (procedimento preparado, não executado).
- Piloto SV-01 e os 64 runs (não autorizados).
- Modelo real, pesos e tokenizer (não incluídos).
- Binário Rust do Guarda-Costas (compilar com `cargo build --release`).
- Revisão jurídica da licença/marca.
- CI em GitHub Actions.

## Observações

- O codinome histórico **Maktub** aparece nos artefatos congelados do SV-01.
- O framework público é **Kairós**.
- O `AUTHORIZATION_TOKEN` do guard continua `None`.
- Nenhum resultado científico é declarado.
