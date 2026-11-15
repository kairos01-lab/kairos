# Status do alpha

**Data:** 2026-11-15
**Versão:** 0.1.0-alpha
**Licença:** AGPL-3.0-only (SPDX)

## Onde o projeto está

- **Repositório público:** <https://github.com/kairos01-lab/kairos>
- **Branch pública:** `main`
- **HEAD público de referência (início desta preparação):**
  `a564417136f8706962d7bf8bd2df40627f91e0c9` (2026-11-08)
- **Tags/releases oficiais:** nenhuma
- **Working tree local:** pode conter alterações posteriores ao commit de
  referência. O GitHub exibe o commit publicado, não o working tree.

O código publicado e o working tree podem não ser idênticos. As melhorias de
licenciamento, autoria, segurança e testes descritas abaixo estão no working
tree local e dependem de revisão e autorização para publicação.

## Código

- Demo `examples/demo_fake_cortex.py`: córtex falso, guarda falso, sem modelo,
  GPU ou rede.
- Guarda-Costas real em Rust: código-fonte em
  `projetos/motor_emocional/guarda_costas/`; o binário não é incluído.
- Núcleo Python em `projetos/motor_emocional/core/`.
- Piloto SV-01: protocolo e instrumentação presentes; **não executado**.

## Testes

- **Suíte local registrada:** 646/646 testes Python e 64/64 testes Rust,
  executados durante a preparação local.
- **Não reexecutados nesta etapa de preparação documental.** A reexecução é
  obrigatória antes de publicar o código.
- Teste básico público: `tests/test_basic.py`.
- O número de testes do working tree é maior que o do baseline público; não
  tratar a suíte local como já publicada.

## SV-01

- Status: `PREPARADO_NAO_EXECUTADO`.
- Runs executados: **0/64**.
- Nenhum resultado comportamental foi produzido.
- O `AUTHORIZATION_TOKEN` do guard permanece `None`.
- O piloto não está autorizado.

## Publicação

- O repositório público está no commit de referência indicado acima.
- Alterações locais posteriores a esse commit não integram o HEAD público até
  revisão e autorização do mantenedor.
- A composição de um eventual release continua `NAO_DEFINIDA`.
- A oferta de licenciamento comercial existente em `README.md`, `docs/FAQ.md` e
  `ARCHITECTURE.md` não é alterada por este documento; decisões sobre ela
  dependem do titular e de avaliação jurídica.
- A publicação de qualquer lote depende de autorização explícita.

## Pendências principais

- Revisar e publicar o primeiro lote documental.
- Corrigir avisos de terceiros e decidir o escopo do arquivo de licenças.
- Reexecutar as suítes Python e Rust antes de publicar código.
- Decidir o destino dos seis textos de licença de modelo ignorados.
- Definir a política de uso do nome/marca Kairós.
- Avaliar juridicamente MPL/LGPL/CNRI, modelos e versões antigas dos assets.

## Observações

- O codinome histórico **Maktub** aparece nos artefatos congelados do SV-01.
- O framework público chama-se **Kairós**.
- Nenhum resultado científico é declarado.
- Este documento não declara conformidade jurídica integral.
