# Licenças de terceiros

**Projeto:** Kairós
**Licença do projeto:** `AGPL-3.0-only` (ver `LICENSE`)
**Copyright do projeto:** Copyright (C) 2026 Diego Melo Rodrigues Ferraz
**Autoria:** `AUTHORS.md`
**Aviso do projeto:** `NOTICE`

**Escopo deste documento:** aviso público autocontido sobre componentes de
terceiros. Os relatórios internos de auditoria não são necessários para
compreendê-lo.

**Acervo de licenças:** `third_party/licenses/` contém o acervo de textos e
avisos preparado em etapa separada. Esse diretório **não integra esta
atualização documental**; os textos serão tratados em etapa separada. Este aviso
é autocontido e foi escrito para ser compreendido sem o acervo.

**Escopo desta atualização:** este arquivo integra a atualização documental
pública e não constitui um pacote completo de distribuição. A distribuição de
software, binários ou ambientes deve ser acompanhada dos avisos aplicáveis ao
conteúdo efetivamente distribuído.

**Composição de release:** `NAO_DEFINIDA`. Este documento não autoriza
distribuição, release ou empacotamento.

> Este arquivo distingue a licença do projeto das licenças de terceiros.
> **Nenhum componente de terceiro é relicenciado sob AGPL-3.0-only.**
> A presença de uma licença permissiva não elimina avisos e obrigações de
> distribuição.

---

## 1. Licença do projeto

O código original do Kairós é distribuído sob **GNU Affero General Public
License v3, SPDX `AGPL-3.0-only`** (`LICENSE`). O texto oficial da licença
permanece integral e não foi alterado.

A AGPL-3.0-only se aplica aos componentes próprios do projeto, respeitando os
direitos e as licenças dos materiais de terceiros.

---

## 2. Dependências Python

Arquivos de declaração:

- `requirements.txt` — base/demo;
- `requirements-sv01.txt` — stack SV-01/modelo.

Não há `pyproject.toml`, `setup.py`, `setup.cfg` ou lockfile Python.

### 2.1 Pacotes diretos e de modelo

| Pacote | Versão pinada | Licença declarada | Situação |
|---|---:|---|---|
| `numpy` | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | verificada |
| `chromadb` | 1.5.9 | Apache (classifier) | verificada com ressalva |
| `matplotlib` | 3.11.2 | PSF-based | verificada |
| `fastapi` | 0.141.1 | MIT | verificada |
| `uvicorn` | 0.52.4 | BSD-3-Clause | verificada |
| `aiohttp` | 3.13.5 | Apache-2.0 AND MIT | verificada |
| `pydantic` | 2.13.4 | MIT | verificada |
| `requests` | 2.34.2 | Apache-2.0 | verificada |
| `jinja2` | 3.1.6 | BSD (classifier) | verificada com ressalva |
| `tokenizers` | 0.23.1 | Apache (classifier) | verificada com ressalva |
| `huggingface_hub` | 1.33.0 | Apache-2.0 | verificada; versão local 1.16.1 |
| `packaging` | 26.3 | Apache/BSD (classifier) | verificada; versão local 25.0 |
| `PyYAML` | 6.0.3 | MIT | verificada |
| `tqdm` | 4.70.1 | MPL-2.0 AND MIT | verificada; versão local 4.67.3; revisar MPL |
| `typer` | 0.25.1 | MIT | verificada |
| `transformers` | 5.22.1 | Apache-2.0 | verificada (PyPI + sdist) |
| `safetensors` | 0.8.0 | Apache-2.0 | verificada (PyPI + sdist) |
| `regex` | 2026.9.29 | Apache-2.0 AND CNRI-Python | verificada (PyPI + sdist) |

### 2.2 Transitivas pinadas

`requirements-sv01.txt` fixa também: `click`, `filelock`, `fsspec`,
`hf-xet`, `httpx`, `httpcore`, `h11`, `idna`, `certifi`, `anyio`, `rich`,
`shellingham`, `markdown-it-py`, `mdurl`, `Pygments`, `annotated-doc`,
`typing_extensions`.

Licenças verificadas: MIT, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0 e MPL-2.0
(`certifi`). Algumas versões do ambiente local divergem dos pins; a referência
deste documento é a versão declarada nos arquivos de requirements.

### 2.3 Transitivas não fixadas

O ambiente local tem **121 pacotes** no fechamento dos 32 instalados
declarados. Isso inclui dependências/extras de `chromadb` e não é um lockfile
do projeto.

Atenção especial:

| Pacote | Licença | Motivo |
|---|---|---|
| `certifi` | MPL-2.0 | licença verificada; weak copyleft, preservar avisos |
| `tqdm` | MPL-2.0 AND MIT | licença verificada; weak copyleft, preservar avisos |
| `orjson` | MPL-2.0 AND (Apache-2.0 OR MIT) | licença verificada; weak copyleft |
| `chardet` | LGPL-2.1-or-later (classifier LGPLv2+) | licença verificada; revisar obrigações |
| `pycairo` | LGPL-2.1-only OR MPL-1.1 | licença verificada; escolha e obrigações |

Vários pacotes têm campo `License` vazio e apenas classifier. Isso é
**PENDENTE_DE_ATRIBUICAO** para o texto integral.

**Lacunas de declaração:** `torch` é importado no caminho opcional SV-01 e
não está declarado; `httpx` é usado em testes e está apenas no stack SV-01.

**Situação da identificação:** os 35 nomes declarados têm licença identificada
em fonte oficial da versão. `torch` continua fora do inventário declarado e sem
versão definida. Restam obrigações de atribuição e revisão jurídica, não
pendências de identificação de licença dos 35.

**Textos arquivados:** os textos das 35 versões pinadas estão em
`third_party/licenses/python/`; as expressões compostas/alternativas foram
preservadas. O aviso consolidado de release ainda não foi montado.

---

## 3. Dependências Rust

Crate principal: `projetos/motor_emocional/guarda_costas/`.
O `Cargo.toml` declara `license = "AGPL-3.0-only"` para o crate do projeto.

### 3.1 Diretas

| Crate | Versão | Licença | Situação |
|---|---:|---|---|
| `serde` | 1.0.229 | MIT OR Apache-2.0 | verificada |
| `serde_json` | 1.0.151 | MIT OR Apache-2.0 | verificada |
| `sha2` | 0.10.9 | MIT OR Apache-2.0 | verificada |
| `chrono` | 0.4.45 | MIT OR Apache-2.0 | verificada |

### 3.2 Transitivas

- 52 terceiros do `Cargo.lock` verificados: 24 no cache local + 28 via
  crates.io/arquivo oficial, todos com checksum conferido.
- Licenças: MIT, Apache-2.0, MIT OR Apache-2.0, Apache-2.0 OR MIT,
  Unlicense OR MIT, `(MIT OR Apache-2.0) AND Unicode-3.0`.
- **0 terceiros pendentes de identificação de licença.**
- Textos e avisos dos 52 crates estão em `third_party/licenses/rust/`; são 103
  arquivos de licença, incluindo Unicode-3.0 e Unlicense.
- A obrigação de **atribuição final** (textos/avisos no release) permanece.
- O repositório não vendoriza crates.
- A distribuição do binário exige preservar avisos das licenças dos crates
  efetivamente linkados.

Os textos e metadados por versão estão em `third_party/licenses/rust/`.

---

## 4. Modelos, tokenizers e corpus

| Componente | Incluído? | Licença | Situação |
|---|---|---|---|
| Qwen3-8B | **não** | Apache-2.0 verificada (cardData + LICENSE na revisão) | **NAO_DISTRIBUIDO** |
| Mistral-7B-Instruct-v0.3 | **não** | Apache-2.0 verificada via cardData/README; texto LICENSE não está no repo do modelo | **NAO_DISTRIBUIDO** / **PENDENTE_DE_ATRIBUICAO** |
| Tokenizer Qwen/Mistral | **não** | licença do modelo; arquivos no repo do modelo | **NAO_DISTRIBUIDO** |
| Corpus bruto TCI | **não** | não aplicável | **NAO_DISTRIBUIDO** |

O repositório não redistribui pesos, tokenizer ou corpus bruto. O usuário que
obtiver esses componentes deve cumprir as licenças de origem. Eles não são
relicenciados pela AGPL do Kairós.

Os textos de referência dos modelos foram levantados em auditoria local. Como
os modelos não são distribuídos, os seis textos em
`third_party/licenses/models/` não integram esta atualização documental por
regra do `.gitignore`. Isso não autoriza distribuir pesos, tokenizers ou os
modelos completos.

Nenhum NOTICE específico da Mistral foi inventado. O texto Apache-2.0 aplicável
continua sendo o texto oficial da licença.

---

## 5. Assets

| Arquivo | Origem | Licença | Situação |
|---|---|---|---|
| `assets/banner.svg` | identidade mínima original | **CC BY 4.0** | **VERIFICADO** |
| `assets/banner.png` | raster do SVG acima | **CC BY 4.0** | **VERIFICADO** |
| `assets/logo.svg` | identidade mínima original | **CC BY 4.0** | **VERIFICADO** |
| `assets/logo.png` | raster do SVG acima | **CC BY 4.0** | **VERIFICADO** |

A identidade visual foi refeita com formas geométricas originais, geradas por
`docs/os125/gerar_assets.py` com Python 3 + Pillow 11.1.0. Não foram usadas
imagens, ícones, fontes ou recursos de terceiros; as letras são polilinhas
desenhadas pelo próprio script.

A licença dos novos arquivos é **CC BY 4.0**, separada da AGPL do software.
Escopo, atribuição, hashes e limitações estão em `ASSETS_LICENSE.md`.

As versões antigas de `banner.png` e `logo.png`, preservadas no histórico Git,
**não** foram relicenciadas e continuam com licença não declarada. Elas não
devem ser redistribuídas como se estivessem sob CC BY 4.0.

Os assets novos permanecem fora de `third_party/licenses/` porque são criação
própria licenciada, não componentes de terceiros.

---

## 6. Componentes não verificados

Permanecem pendentes:

- declaração de `torch` (opcional SV-01) — sem versão/licença definida;
- versões divergentes entre pin e ambiente Python;
- montagem do `THIRD_PARTY_NOTICES` final do release;
- inclusão do texto Apache-2.0 da Mistral no aviso de release, se o modelo for
  distribuído;
- confirmação de quais crates Rust entram no binário distribuído;
- compatibilidade jurídica de MPL/LGPL/CNRI e de todos os componentes;
- definição sobre os seis textos de modelo que não integram esta atualização;
- licença das versões antigas dos assets, que não foram relicenciadas.

Os assets novos estão resolvidos como **CC BY 4.0** e não figuram mais como
pendência de autoria/licença. As versões antigas continuam sem licença
declarada.

**Não** classificar automaticamente esses itens como incompatíveis.
**Não** classificá-los como compatíveis sem evidência.

---

## 7. Distribuição

Antes de distribuir um release ou ambiente:

1. preservar `LICENSE`, `NOTICE`, `AUTHORS.md` e os avisos de terceiros;
2. usar `third_party/licenses/` como base dos textos, com
   `SHA256SUMS` para verificação;
3. montar o `THIRD_PARTY_NOTICES` final com os componentes efetivamente
   distribuídos;
4. revalidar as versões e licenças no ambiente de build;
5. verificar obrigações de MPL/LGPL, Apache NOTICE e Unicode-3.0;
6. não relicenciar componentes de terceiros sob AGPL;
7. não remover avisos de terceiros;
8. consultar avaliação jurídica para casos ambíguos.

**Escopo do `SHA256SUMS`:** o arquivo de referência cobre 263 textos, incluindo
seis textos de modelo que não integram esta atualização por regra do
`.gitignore`. Para o snapshot de código, os modelos são externos e não
distribuídos; a ausência desses seis textos não é falha de integridade do
código nem desta atualização. Se os textos forem incorporados, o `.gitignore`
e o manifesto devem ser atualizados na mesma OS.

Este arquivo não declara compatibilidade jurídica completa. Ele registra
evidências e pendências para orientar a distribuição.
