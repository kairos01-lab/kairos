# Licença dos assets visuais do Kairós

**Aplica-se a:**

- `assets/banner.svg`
- `assets/banner.png`
- `assets/logo.svg`
- `assets/logo.png`

**Licença:** Creative Commons Attribution 4.0 International (**CC BY 4.0**).

**Texto oficial da licença:**
<https://creativecommons.org/licenses/by/4.0/legalcode>

**Resumo legível (não substitui o texto oficial):**
<https://creativecommons.org/licenses/by/4.0/>

**Copyright (C) 2026 Diego Melo Rodrigues Ferraz.**

**Data da declaração:** 2026-11-14.

---

## 1. Escopo e separação da licença do software

Esta declaração cobre **somente** os quatro arquivos visuais listados acima.

O código-fonte do Kairós continua sob **AGPL-3.0-only**, conforme `LICENSE`.
A licença CC BY 4.0 **não** se aplica ao software, e a AGPL **não** se aplica
automaticamente a estes assets. As duas licenças são independentes.

Os arquivos visuais não são considerados “código” para fins desta declaração,
embora o SVG seja um formato textual e o PNG seja gerado por um script.

---

## 2. Atribuição exigida pela CC BY 4.0

Ao reutilizar, reproduzir, adaptar ou redistribuir os assets, atribua:

> Kairós visual identity — Copyright (C) 2026 Diego Melo Rodrigues Ferraz —
> licenciado sob CC BY 4.0.
> <https://creativecommons.org/licenses/by/4.0/>

Inclua um link para a licença. Se o material for modificado, indique
claramente que houve modificação. Não sugira que o licenciante endossa o uso
ou o produto derivado.

---

## 3. Autoria, método e originalidade

| Campo | Registro |
|---|---|
| Titular/licenciante | Diego Melo Rodrigues Ferraz |
| Execução | agente de IA local, sob direção e autorização do titular |
| Método | script `docs/os125/gerar_assets.py` |
| Ferramenta de rasterização | Python 3 + Pillow 11.1.0 |
| Fonte vetorial | `assets/banner.svg`, `assets/logo.svg` |
| Raster | `assets/banner.png` (1280×640), `assets/logo.png` (512×512) |
| Data de criação | 2026-11-14 |
| Modelo de geração de imagem | **não utilizado** |

### 3.1 O que foi criado

- fundo em gradiente discreto;
- círculos, linhas e uma insígnia circular;
- letras maiúsculas desenhadas como **polilinhas geométricas originais**;
- marca “K” e ponto teal;
- composição e paleta definidas no script gerador.

### 3.2 O que não foi usado

Não foram incorporados:

- fotografias, ilustrações, ícones ou clipart de terceiros;
- imagens obtidas na internet ou em bancos de imagens;
- fontes tipográficas externas;
- arquivos de fonte embutidos ou convertidos em curvas;
- modelos de geração de imagem;
- recursos remotos, marcas d'água ou elementos de terceiros.

As letras do banner são desenhadas pelo próprio script como segmentos de reta.
Não há glifos de nenhuma fonte de terceiros nos SVGs ou PNGs.

### 3.3 Limite desta declaração

Esta é uma declaração de licenciamento do projeto, não um parecer jurídico.
Ela se baseia na criação original registrada neste projeto e na autorização do
titular. Dúvidas sobre titularidade em jurisdições específicas devem ser
tratadas em revisão jurídica própria.

---

## 4. Versões antigas não são relicenciadas

As versões anteriores de `assets/banner.png` e `assets/logo.png`, preservadas
no histórico Git, **não** estão cobertas pela CC BY 4.0. Seus hashes eram:

```text
cfd4b60cafcf61626ce82c22d1c36ab2220d1564b14fba1a86e1da539bb59aab  banner.png (versão antiga)
ebc05b6622ee94f2cc481bbaddc4063484fa6e1416c210398be6837e01599704  logo.png (versão antiga)
```

A licença dessas versões antigas permanece **não declarada**. Elas não devem
ser redistribuídas como se estivessem sob CC BY 4.0. A substituição dos
arquivos não apaga o histórico nem reescreve commits.

---

## 5. Marca e identidade

A CC BY 4.0 licencia direitos autorais sobre os arquivos visuais. Ela **não**
concede direitos de marca, nome comercial ou endosso. O nome **Kairós** e o uso
da identidade visual como marca do projeto continuam sujeitos à decisão do
responsável, conforme o README.

---

## 6. Verificação

- Os quatro arquivos existem e abrem corretamente.
- Dimensões: banner 1280×640; logo 512×512.
- Formatos: SVG (fonte vetorial) e PNG (RGBA, compatível com transparência).
- Nenhum recurso de terceiros foi incorporado.
- A licença do software (`LICENSE`, AGPL-3.0-only) não foi alterada.

### 6.1 Hashes SHA-256 dos assets

```text
a5ceb9299e0afd30d59e36cb25cd5ef08e3b903c390d5b253ca5e9c51a744740  assets/banner.png
f4f749955286da89e12d4c3bf9279b58c5773970b2da7feeb7a643f2ea9cca5f  assets/logo.png
3881c66e8284b1c8ab8b45c3bad5fe6cf461a31a58e97e063b017435c932ac71  assets/banner.svg
9766d7df9cb3bf8eec3e4305bbda8c1f63064ec9d956548abfba7854fd316ca9  assets/logo.svg
```

Esses hashes são a referência direta deste documento. Não é necessário acessar
manifestos internos de OS para verificá-los.

---

## 7. Resumo

| Item | Licença |
|---|---|
| Software Kairós | AGPL-3.0-only |
| Assets visuais novos | **CC BY 4.0** |
| Versões antigas dos assets | não declarada; não relicenciadas |
| Nome/marca Kairós | não licenciado pela CC BY |
