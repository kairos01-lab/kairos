# Segurança

## Status

Alpha de pesquisa. Não use em produção, em sistemas críticos ou com processos
reais sem revisão de segurança.

## O que o demo faz

O demo `examples/demo_fake_cortex.py` usa:

- córtex falso (nenhum LLM, GPU ou rede);
- Guarda-Costas falso (nenhum processo real é encerrado);
- memória local temporária.

Ele serve para mostrar o fluxo, não para operar o sistema.

## Guarda-Costas real

O Guarda-Costas real é um binário Rust em
`projetos/motor_emocional/guarda_costas/`. Para compilar:

```bash
cd projetos/motor_emocional/guarda_costas
cargo build --release
```

O binário fica em `target/release/guarda_costas` e é chamado pelo wrapper
Python. Antes de usar com processos reais:

- revise o contrato de ações (`read`, `create`, `update`, `delete`);
- teste em sandbox;
- mantenha o `action="read"` no demo;
- não conceda permissão de matar processos sem necessidade.

## Segredos

Nunca commite:

- `.groq_key`, `.secret/segredos.env`, `.kaggle/access_token`;
- `.maktub-kaggle/tunnel_url`;
- chaves de API, tokens, senhas;
- logs com credenciais;
- dados pessoais.

O `.gitignore` cobre os caminhos conhecidos, mas revise antes de publicar.

## Reportar vulnerabilidade

Abra uma issue privada ou descreva o problema sem publicar credenciais. Não
inclua chaves, tokens ou dados pessoais no relatório.

## Escopo

Este repositório não inclui pesos de modelo, dados brutos de pesquisa ou o
ambiente Kaggle. O piloto SV-01 não está autorizado.
