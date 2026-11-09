# Diário do repositório

Registro público e datado do que foi feito, do que foi verificado e do que ficou
pendente. Não é um changelog técnico: é o estado real do projeto, incluindo
erros e correções.

---

## 2026-11-08 — Publicação do Kairós

### Feito

- Repositório público criado: `github.com/kairos01-lab/kairos`.
- Licença **AGPL-3.0** adicionada.
- `README.md` com posicionamento, autoria, resultados, TCI e manifesto.
- Documentos publicados: `AUTORIA`, `TCI`, `RESULTS`, `MANIFESTO`, `STATUS`,
  `ROADMAP`, `RESEARCH_SV01`, `FAQ`, `SECURITY`, `ARCHITECTURE`,
  `CONTRIBUTING`, `CODE_OF_CONDUCT` e `CITATION`.
- `research/tci/` publicado com teoria, auditoria, protocolo, Fase B, scripts e
  registros.
- Demo com córtex falso e testes locais.
- Logo e banner gerados localmente e publicados em `assets/`.
- Banner configurado como **social preview** do repositório.
- Descrição e tópicos do repositório preenchidos.
- Issue **#1** criada e fixada no topo:
  "Call for collaborators: revisão da camada afetiva e da auditoria TCI".
- Publicação feita via chave SSH `kairos-pc`; nenhum token foi colocado no código.

### Verificado

- Autenticação SSH respondeu `Hi kairos01-lab! You've successfully authenticated`.
- README renderiza no GitHub.
- Seis tópicos públicos: `affective-computing`, `ai-agents`, `guardrails`,
  `policy-engine`, `reproducibility`, `tci`.
- Social preview servindo o banner de 1280×640.
- Corpo completo da issue #1 salvo com 1.177 caracteres.
- Nenhum segredo, peso de modelo ou corpus bruto foi enviado.

### Não feito / pendente

- Piloto **SV-01 continua bloqueado** por autorização humana.
- Os **64 runs não foram executados**.
- Paridade do tokenizer verificada apenas localmente; ainda não no Kaggle.
- Sem identidade visual definitiva (logo e banner são provisórios).
- Sem revisão externa ainda.
- **Pendente:** levar a ponte Maktub ↔ TCI para `docs/TCI.md` — a pergunta do
  vetor mínimo e do sistema topológico irredutível.

### Correções

- O primeiro envio da issue #1 cortou o corpo em 154 caracteres. O texto foi
  reaberto no editor do GitHub e salvo completo.

---

## Como este diário funciona

- Cada entrada é datada e separa **feito**, **verificado**, **pendente** e
  **correções**.
- Resultado negativo entra como resultado, não como falha escondida.
- Nada é marcado como validado sem verificação reproduzível.
