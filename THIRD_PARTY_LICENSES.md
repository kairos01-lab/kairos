# Licenças de terceiros

O código original deste repositório está sob **AGPL-3.0** (ver `LICENSE`).

## Dependências Python

As bibliotecas usadas (por exemplo `numpy`, `chromadb`, `matplotlib`,
`fastapi`, `uvicorn`, `aiohttp`, `pydantic`, `requests`, `jinja2`,
`tokenizers`, `transformers`) mantêm suas próprias licenças. Consulte os
pacotes instalados e seus metadados antes de redistribuir.

## Rust / Guarda-Costas

O crate em `projetos/motor_emocional/guarda_costas/` usa dependências listadas
em `Cargo.toml`/`Cargo.lock`. Cada crate mantém sua licença. O código original
do Guarda-Costas está sob AGPL-3.0, salvo indicação em contrário.

## Qwen3-8B

O modelo e o tokenizer **não** estão incluídos neste repositório. Se você
obtiver o `Qwen/Qwen3-8B` (revisão
`b968826d9c46dd6066d109eabc6255188de91218`), siga a licença do modelo no
Hugging Face (Apache-2.0 na revisão usada na pesquisa; confirme na fonte).
Os arquivos de tokenizer não são relicenciados pela AGPL deste projeto.

## Marca

A marca **Kairós** e a identidade visual não são licenciadas pela AGPL. O nome
“Maktub” aparece em artefatos históricos de pesquisa e também não é relicenciado
para uso de marca.
