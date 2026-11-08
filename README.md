# Kairós

**Kairós** é uma camada de controle afetivo auditável para agentes: estado interno,
estresse, política de degradação, memória e guardrails. É uma **simulação** de
controle — não é consciência, não é AGI e não é “emoção real”.

O projeto nasceu com o codinome de pesquisa **Maktub**. O código e os protocolos
históricos preservam esse nome; o framework público chama-se **Kairós**.

**Status:** alpha de pesquisa. Não é pronto para produção.
**Licença:** GNU AGPL v3.0 (`LICENSE`).

---

## O que tem aqui

| Camada | O que faz |
|---|---|
| Matriz emocional | Estado de 3 eixos: valência, energia e previsibilidade. |
| Fígado virtual | Acumula estresse com decaimento exponencial e gatilhos. |
| Policy Engine 2.0 | Traduz estresse em níveis 0–3, com ação e modificadores. |
| Memória | ChromaDB com embeddings 3D determinísticos e ponte de contexto. |
| Córtex | Monta o prompt e chama um LLM (API ou local); no demo, é falso. |
| Guarda-Costas | Ponte Python → Rust para hard block, kernel check e break glass. |
| Dashboard | Painel matplotlib e servidor FastAPI/WebSocket (opcional). |
| SV-01 | Protocolo de pesquisa com manifesto, hashes e instrumentação. |

## Demo em 2 minutos (sem GPU e sem modelo)

Requisitos: Python 3.11+ e terminal.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python examples/demo_fake_cortex.py
```

O demo usa um córtex falso e um Guarda-Costas falso. Ele mostra o fluxo:

```text
estado emocional -> estresse -> política -> prompt -> resposta -> registro
```

Nenhum modelo, GPU, rede ou API é chamado.

## Testes

```bash
python -m unittest discover -s tests -v
```

## Estrutura

```text
projetos/motor_emocional/
  core/                       matriz, fígado, política, memória, córtex, dashboard
  os028/sv01/                 protocolo e runner do SV-01
  guarda_costas/              código-fonte Rust do Guarda-Costas
os040/instrumentation/        manifesto, prompt_order, hash, state_record, guard
os041/integration/            RunSpec, tokenizer real e doubles de teste
research/sv01/                hashes esperados da paridade
examples/                     demo sem modelo
tests/                        testes offline
docs/                         arquitetura, pesquisa, FAQ, roadmap
run_packaged.py               launcher do pacote de pesquisa
```

O layout de `os040`/`os041`/`projetos` foi preservado para manter a
reprodutibilidade dos caminhos relativos do experimento. O demo genérico não
depende desses caminhos.

## Pesquisa SV-01

O SV-01 compara decisões sob dois níveis de estresse no prompt (C77 e C85) em
quatro ordens de alternativas, com manifesto de 64 linhas, hash do prompt
renderizado e registro completo. O piloto **não está autorizado** e os 64 runs
**não foram executados**. Leia `docs/RESEARCH_SV01.md` antes de usar qualquer
resultado.

O ambiente de paridade usa `transformers 5.22.1`, `tokenizers 0.23.1` e o
tokenizer Qwen3-8B na revisão
`b968826d9c46dd6066d109eabc6255188de91218`. Os arquivos do tokenizer e os pesos
do modelo **não** estão neste repositório; veja `docs/RESEARCH_SV01.md`.

## Licença

O código original está sob **AGPL-3.0**. Em resumo: se você modificar e
disponibilizar o software como serviço de rede, precisa oferecer o código-fonte
correspondente aos usuários. Para uso comercial em produto fechado, é possível
negociar uma **licença comercial separada** com o autor.

Arquivos de terceiros (dependências Python, crates Rust, tokenizer/modelo Qwen)
mantêm suas próprias licenças. Veja `THIRD_PARTY_LICENSES.md`.

A marca **Kairós** não é licenciada pelo AGPL; o nome e a identidade visual são
reservados.

## Segurança

Este é um alpha de pesquisa. Não use em produção, não aponte o Guarda-Costas
para processos reais sem revisão e não rode o piloto sem autorização humana
explícita. Veja `SECURITY.md`.

## Contribuindo

Veja `CONTRIBUTING.md` e `CODE_OF_CONDUCT.md`. Issues e discussões são bem-vindas.
