# OS165 — Contrato e implementação da persistência histórica F3

**Data:** 2026-11-22
**Status:** especificação consolidada da implementação mínima.
**Base:** decisões das OS157–OS162; implementação da OS163.
**Natureza:** documentação técnica. Não é certificação de segurança nem parecer jurídico.

---

## 1. Objetivo

Registrar o contrato da persistência durável do histórico de interações do
Kairós e a implementação mínima entregue na OS163:

- interface independente;
- implementação em memória para testes;
- implementação SQLite com a biblioteca padrão;
- banco próprio, separado de ChromaDB e de qualquer memória cognitiva.

O armazenamento não decide autorização, não autentica identidade e não executa
ações externas.

---

## 2. Componentes

```text
MotorEmocional
  → InteractionHistoryStore (Protocol)
      ├─ InMemoryInteractionHistoryStore
      └─ SqliteInteractionHistoryStore
           └─ interaction_history.db
                ├─ interaction_events
                └─ store_meta
```

`MotorEmocional` recebe um `history_store` opcional. A fábrica
`init_motor_emocional()` cria o store SQLite padrão. A construção direta da
classe permanece opt-in para testes e usos controlados.

---

## 3. Interface

A interface `InteractionHistoryStore` oferece:

- `append(event, idempotency_key=None)`;
- `get(request_id)`;
- `get_record(record_id)`;
- `list_recent(limit, before_unix_ms, before_record_id)`;
- `list_for_subject(subject_id, from_unix_ms, to_unix_ms, limit)`;
- `health()`;
- `verify_integrity(full=False)`;
- `close()`.

Modelos:

- `HistoryEvent`: conteúdo lógico fornecido pelo chamador;
- `StoredHistoryRecord`: registro persistido completo, com `record_id`,
  `sequence`, timestamps, hashes e elo anterior;
- `AppendResult`: resultado da gravação, com `stored_record` quando aplicável;
- `StoreHealth` e `IntegrityReport`.

---

## 4. Schema versionado

O schema físico usa `PRAGMA user_version = 1`. Cada evento tem
`event_schema_version` próprio.

A tabela `interaction_events` contém:

- identificação: `record_id`, `request_id`, `correlation_id`,
  `parent_record_id`, `idempotency_key`;
- classificação: `event_type`, `sequence`, timestamps;
- identidade declarada: `requester_id`, `subject_id`,
  `authentication_status`, `identity_status`, `authority_basis`;
- ação: `threat_type`, `action`, hashes de alvo/intenção e tamanhos;
- decisão: `authorization_status`, `execution_status`, `cortex_status`,
  `system_state`;
- payload JSON validado em `payload_json`: objeto com chaves string,
  tipos JSON permitidos e limites da seção 6; chaves reservadas no
  nível superior são rejeitadas. O store não aplica allowlist de chaves
  de negócio; a integração atual do motor envia apenas `policy`,
  `authorization`, `execution`, `cortex`, `memory`, `state`,
  `processing_time_ms` e `user_input_chars`;
- integridade: `event_hash_sha256`, `record_hash_sha256`,
  `prev_record_hash_sha256`;
- campos reservados para HMAC futuro (`record_hmac`, `hmac_key_version`).

Constraints:

```text
UNIQUE(request_id, sequence)
UNIQUE INDEX (request_id, idempotency_key) WHERE idempotency_key IS NOT NULL
FOREIGN KEY parent_record_id REFERENCES interaction_events(record_id)
  ON DELETE RESTRICT
```

`PRAGMA foreign_keys = ON` é aplicado e verificado em cada conexão.
`journal_mode=WAL`, `synchronous=FULL` e `busy_timeout` configurável são usados.

---

## 5. Idempotência

A chave é única por `(request_id, idempotency_key)`.

- mesma chave e mesmo hash lógico → `DUPLICATE`, retornando o registro original;
- mesma chave e hash diferente → `IDEMPOTENCY_CONFLICT`, sem gravação;
- a mesma chave em outra requisição é permitida;
- a mesma chave para tipos de evento diferentes na mesma requisição é conflito;
  usar chaves distintas por evento.

O hash de idempotência cobre o envelope lógico completo: versão do evento,
requisição, correlação, vínculo lógico, tipo, identidade, ação, política,
autorização, execução, Córtex, estado e payload. Campos atribuídos pelo store
(`record_id`, `sequence`, `occurred_at`, `recorded_at`, chave e hashes) ficam
fora.

---

## 6. Canonicalização

Aceita exclusivamente:

```text
dict com chaves string, list, string, int, float finito, bool, None
```

Rejeita `tuple`, `bytes`, `datetime`, `Decimal`, `UUID`, `set`, objetos, chaves
não string, `NaN`, infinitos e surrogates isolados.

A canonicalização usa JSON com chaves ordenadas, separadores compactos,
UTF-8 estrito, `ensure_ascii=False` e `allow_nan=False`. O payload é copiado
para uma representação independente antes do hash e da gravação.

Limites atuais: profundidade 16, 64 KiB serializados, 128 chaves, 256 itens e
8192 caracteres por string.

---

## 7. Hashes e cadeia

### `event_hash_sha256`

Cobre os campos lógicos do evento. Exclui os campos atribuídos pelo store e
serve à idempotência.

### `record_hash_sha256`

Cobre todos os campos persistidos, incluindo `record_id`, `sequence`,
timestamps, `event_hash_sha256` e `prev_record_hash_sha256`. Exclui apenas o
próprio `record_hash_sha256` e `record_hmac`.

### Cadeia

- a cadeia é **por `request_id`**;
- o primeiro evento tem `prev_record_hash_sha256 = NULL`;
- os seguintes apontam para o `record_hash_sha256` do anterior da mesma
  requisição;
- sequência e elo anterior são atribuídos na mesma transação `BEGIN IMMEDIATE`;
- `verify_integrity()` agrupa por requisição, ordena por `sequence ASC`, recalcula
  os hashes e confere os elos; não repara automaticamente.

`parent_record_id` é a relação lógica (por exemplo, `OUTCOME` → `INTENT`) e
**não** se confunde com `prev_record_hash_sha256`, que é a cadeia de integridade.

---

## 8. Transação e tempo

O append:

1. inicia `BEGIN IMMEDIATE`;
2. verifica idempotência;
3. valida o pai lógico;
4. calcula a próxima `sequence` da requisição e o hash anterior;
5. atribui `occurred_at_unix_ms` e `recorded_at_unix_ms` no store;
6. calcula hashes, insere e confirma o commit;
7. só retorna `RECORDED` após o commit.

`occurred_at_unix_ms` não é fornecido pelo chamador. Repetições idempotentes
preservam o horário original.

---

## 9. Política de falha

Estados de gravação: `RECORDED`, `DUPLICATE`, `IDEMPOTENCY_CONFLICT`,
`SEQUENCE_CONFLICT`, `INVALID_RECORD`, `UNAVAILABLE`, `TIMEOUT`, `WRITE_FAILED`
e `CORRUPT`.

- `RECORDED` só após commit;
- falha em operação best-effort é exposta como
  `audit_completeness="INCOMPLETE"` no resultado do motor;
- nenhum fallback em RAM é apresentado como persistência durável;
- operações futuras que exijam auditoria obrigatória devem bloquear sem
  `INTENT` durável;
- mutações futuras devem registrar `INTENT` e `OUTCOME`, com reconciliação de
  `EXECUTION_UNCONFIRMED`;
- corrupção é sinalizada e não sobrescrita.

A integração atual registra `INTERACTION`, `VALIDATION_REJECTED`,
`AUTHORIZATION_DENIED`, `INFRASTRUCTURE_FAILURE`, `CORTEX_FAILURE` e
`BREAK_GLASS`. `INTENT`/`OUTCOME` existem no store e nos testes, mas não há
execução externa de operações CRUD nesta etapa.

---

## 10. Limitações conhecidas

- HMAC e rotação de chaves não implementados; `record_hmac` é nulo;
- não há exportação assinada;
- não há retenção, exclusão, anonimização ou legal hold;
- não há endpoint HTTP de consulta/exportação nem autenticação;
- não há PostgreSQL;
- não há vínculo com execução externa nem garantia de exactly-once;
- a cadeia SHA-256 detecta alteração, mas não protege contra um agente que
  controle o banco e recalcule os hashes;
- o banco não é compartilhado com ChromaDB ou `maktub_cognitive.db`.

A implementação é mínima e verificável; não é uma declaração de segurança
absoluta, conformidade jurídica ou prontidão de release.
