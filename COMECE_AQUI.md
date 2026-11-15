# COMECE AQUI

Este repositório **já é público** em
<https://github.com/kairos01-lab/kairos>. Não é preciso criar um repositório
novo para ler, executar ou estudar o projeto.

## 1. Obter o código

Opção A — clonar com Git:

```bash
git clone https://github.com/kairos01-lab/kairos.git
cd kairos
```

Opção B — baixar um snapshot:

No GitHub, use o botão **Code → Download ZIP**. O snapshot contém os arquivos
rastreados do commit selecionado; não contém arquivos ignorados ou não
rastreados.

## 2. Rodar o demo

O demo não usa modelo, GPU, rede ou API.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python examples/demo_fake_cortex.py
```

Se aparecer um JSON com `resposta`, `estado_emocional`, `estresse`,
`policy_level` e `prompt`, funcionou.

## 3. Rodar os testes

```bash
python -m unittest discover -s tests -v
```

O teste básico público é `tests/test_basic.py`. O working tree local pode ter
uma suíte maior, ainda não publicada.

## 4. O que é cada coisa

- **README.md** — cartão de visita e visão geral.
- **LICENSE** — licença do software: `AGPL-3.0-only`.
- **ASSETS_LICENSE.md** — licença dos assets visuais: CC BY 4.0, separada da
  licença do software.
- **AUTHORS.md** e **NOTICE** — autoria, copyright e avisos.
- **CONTRIBUTING.md** — contribuição, DCO e declaração de origem.
- **THIRD_PARTY_LICENSES.md** — avisos de dependências e componentes externos.
- **examples/demo_fake_cortex.py** — demo com córtex e guarda falsos.
- **tests/** — testes automatizados.
- **docs/** — documentação, pesquisa e histórico.
- **projetos/motor_emocional/core/** — núcleo do motor emocional.
- **projetos/motor_emocional/guarda_costas/** — Guarda-Costas em Rust.

## 5. Estado público versus working tree

- O GitHub exibe o commit mais recente da branch pública.
- O working tree de desenvolvimento pode conter alterações posteriores ao
  commit publicado.
- Se um documento local mencionar algo que não aparece no GitHub, ele pode
  descrever o estado local, não o estado público.
- Consulte `docs/STATUS.md` para a situação resumida.

## 6. O que não fazer

- Não copie `.groq_key`, `.secret/`, `.kaggle/`, `.maktub-kaggle/`, logs,
  backups ou modelos para dentro do repositório.
- Não rode o piloto SV-01 nem os 64 runs; ele está bloqueado.
- Não use o Guarda-Costas com processos reais sem revisão e sandbox.
- Não presuma que todo o working tree já está público.

## 7. Se você quiser contribuir

1. Leia `CONTRIBUTING.md`.
2. Faça um fork ou clone do repositório existente; **não** rode `git init` para
   recriar o projeto.
3. Crie uma branch para sua mudança.
4. Rode os testes relevantes.
5. Abra um PR com escopo pequeno e `Signed-off-by`.

O projeto é um alpha de pesquisa. Não é pronto para produção.
