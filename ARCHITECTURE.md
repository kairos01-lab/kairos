# Arquitetura do Kairós

## Visão geral

```text
entrada
  -> Fígado Virtual (estresse + gatilhos)
  -> Policy Engine 2.0 (nível 0-3, ação, modificadores)
  -> Guarda-Costas (Rust: hard block / kernel / break glass)
  -> Matriz Emocional (valência, energia, previsibilidade)
  -> Ponte de Memória (ChromaDB)
  -> Córtex (prompt + LLM)
  -> Dashboard / histórico / registro
  -> resposta
```

## Componentes

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Matriz Emocional | `projetos/motor_emocional/core/emotional_matrix.py` | Estado de 3 eixos. |
| Fígado Virtual | `.../core/virtual_liver.py` | Estresse com decaimento e gatilhos. |
| Memória | `.../core/triangulation_memory.py` | ChromaDB + embeddings 3D determinísticos. |
| Ponte de Memória | `.../core/memory_bridge.py` | Recupera e formata contexto elegível. |
| Policy Engine | `.../core/policy_engine.py` | Níveis 0–3, ações e modificadores. |
| Córtex | `.../core/cortex_prefrontal.py` | Prompt, API/local, fallback, metadados. |
| Dashboard | `.../core/dashboard.py` | Painel matplotlib. |
| Web | `.../core/web_server.py` | FastAPI + WebSocket. |
| API Router | `.../core/api_router.py` | Rotação/failover de chaves. |
| Guarda-Costas | `.../core/guarda_costas.py` + Rust | Hard block, kernel, break glass. |
| Motor | `.../core/motor_sistema.py` | Orquestra `process_interaction`. |

## Instrumentação de pesquisa

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Manifesto | `os040/manifesto_64.json` | 64 runs C77/C85 × O1–O4. |
| Prompt order | `os040/instrumentation/prompt_order.py` | Quatro ordens e `letter_to_option`. |
| Backend | `os040/instrumentation/backends_instrumented.py` | Tokenizer real e hash renderizado. |
| Adapter | `os040/instrumentation/model_adapter_instrumented.py` | Propaga/valida o hash. |
| Classificador | `os040/instrumentation/semantic_classifier.py` | Letra → opção semântica. |
| Registro | `os040/instrumentation/state_record.py` | Campos core/opcionais e ausentes. |
| Guard | `os040/instrumentation/execution_guard.py` | Autorização central. |
| Integração | `os041/integration/` | `RunSpec`, tokenizer real, doubles. |

## Decisões de design

1. **Estado explícito, não “emoção”**: valência, energia e previsibilidade são
   variáveis auditáveis.
2. **Política separada do LLM**: o LLM não decide o nível de estresse; ele recebe
   o estado e a política já calculados.
3. **Memória separada em duas coleções**: política e contexto não se misturam.
4. **Guarda-Costas fora do Python**: o hard block roda em Rust via subprocess.
5. **Pesquisa reprodutível**: manifesto, hash do prompt, state record e guard.
6. **Demo sem modelo**: o exemplo público usa córtex falso para não exigir GPU.

## Limites

- O demo usa guarda e córtex falsos; não é o modo de produção.
- O Guarda-Costas real precisa ser compilado (`cargo build --release`).
- O SV-01 não foi executado; o piloto está bloqueado.
- A memória usa hash 3D, não embedding semântico profundo.
- A licença é AGPL-3.0; uso comercial fechado exige licença separada.
