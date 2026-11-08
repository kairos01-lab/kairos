# COMECE AQUI (versão simples)

Este diretório é a vitrine pública do **Kairós**. Ele já está montado e testado
localmente. Nada foi publicado na internet.

## O que você precisa fazer para ver funcionando

Abra o terminal nesta pasta e rode, uma linha por vez:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python examples/demo_fake_cortex.py
```

Se aparecer um JSON com `resposta`, `estado_emocional`, `estresse`,
`policy_level` e `prompt`, funcionou. O demo não usa modelo, GPU, rede ou API.

Para rodar os testes:

```bash
python -m unittest discover -s tests -v
```

## O que é cada coisa (sem technês)

- **README.md**: o cartão de visita do projeto.
- **LICENSE**: as regras de uso. Você escolheu AGPLv3.
- **examples/demo_fake_cortex.py**: um exemplo que roda na hora, com um “córtex
  falso”, só para mostrar o fluxo.
- **tests/**: testes automáticos para garantir que o básico não quebrou.
- **docs/**: explicações maiores.
- **projetos/motor_emocional/core/**: o motor emocional em si.
- **projetos/motor_emocional/guarda_costas/**: a parte de segurança escrita em Rust.

## O que NÃO fazer agora

- Não publique esta pasta ainda.
- Não copie `.groq_key`, `.secret/`, `.kaggle/`, `.maktub-kaggle/`, resultados,
  backups, modelos ou logs para dentro dela.
- Não rode o piloto SV-01 nem os 64 runs.
- Não use em produção.

## Quando você quiser publicar no GitHub

Só depois de revisar. O fluxo é:

1. criar uma conta no GitHub (grátis);
2. criar um repositório vazio chamado `kairos` (sem README, sem licença);
3. no terminal, dentro desta pasta:

```bash
git init
git add .
git commit -m "Kairós alpha"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/kairos.git
git push -u origin main
```

Eu não tenho acesso à sua conta e não vou pedir sua senha. Se você quiser, eu
te acompanho passo a passo na hora de rodar esses comandos.

## Próximo passo recomendado

1. Rodar o demo e os testes.
2. Ler o `README.md`.
3. Me dizer o que você quer ajustar no texto, no nome ou no escopo.
4. Só então pensar em publicar e convidar pessoas.
