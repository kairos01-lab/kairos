# -*- coding: utf-8 -*-
"""Proveniência e vinculação contextual de `policy_result` — OS115.

Este módulo responde a uma pergunta limitada:

    este dicionário foi emitido pelo fluxo do Policy Engine para *esta*
    solicitação?

A resposta é dada por um registro de emissão mantido no processo, não por um
campo textual como ``"source": "PolicyEngine"`` e não por uma assinatura. O
registro guarda a identidade do objeto emitido, o vínculo contextual
(``request_id``, ``user_id``, ``subject_id`` e ``action``) e o digest canônico
do payload. Um dicionário fabricado, copiado, reutilizado ou alterado não
corresponde à entrada emitida e é rejeitado.

Limites explícitos (OS115, cenário 3):

- o registro vive no mesmo processo Python que o Policy Engine;
- código que já controla o processo pode importar este módulo, chamar funções
  internas, substituir o Policy Engine ou ignorar a decisão;
- portanto isto **não** é uma fronteira criptográfica contra controle
  arbitrário do processo. É proteção contra erro de integração, fabricação
  ingênua de dicionários e reutilização/cópia por chamadores internos dentro
  do modelo de ameaça documentado.

O digest SHA-256 detecta alteração do payload dentro do registro. Ele não
autentica a origem para um observador externo e não substitui isolamento entre
processos.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import threading
import time
import uuid
from collections import OrderedDict

from .authorization_contract import validate_identifier

POLICY_PROVENANCE_CONTRACT_VERSION = 1
PROVENANCE_KEY = "provenance"
PROVENANCE_ISSUER = "PolicyEngine20"

PROVENANCE_ISSUED = "ISSUED"
PROVENANCE_UNBOUND = "UNBOUND"

PROVENANCE_VALID = "VALID"
PROVENANCE_ABSENT = "ABSENT"
PROVENANCE_MALFORMED = "MALFORMED"
PROVENANCE_UNBOUND_STATUS = "UNBOUND"
PROVENANCE_ERROR = "ERROR"
PROVENANCE_UNKNOWN = "UNKNOWN"
PROVENANCE_COPY = "COPY"
PROVENANCE_REUSED = "REUSED"
PROVENANCE_MUTATED = "MUTATED"
PROVENANCE_VERSION_UNKNOWN = "VERSION_UNKNOWN"
PROVENANCE_REQUEST_MISMATCH = "REQUEST_MISMATCH"
PROVENANCE_USER_MISMATCH = "USER_MISMATCH"
PROVENANCE_SUBJECT_MISMATCH = "SUBJECT_MISMATCH"
PROVENANCE_ACTION_MISMATCH = "ACTION_MISMATCH"
PROVENANCE_ENGINE_MISMATCH = "ENGINE_MISMATCH"
PROVENANCE_INCONSISTENT = "INCONSISTENT"

_VALID_ACTIONS = frozenset({"create", "read", "update", "delete"})
_MAX_EVALUATIONS = 4096
_HEX_DIGEST_CHARS = 64

_BLOCKED_BY = {
    PROVENANCE_ABSENT: "policy_provenance_missing",
    PROVENANCE_MALFORMED: "policy_provenance_invalid",
    PROVENANCE_UNBOUND_STATUS: "policy_provenance_unbound",
    PROVENANCE_UNKNOWN: "policy_provenance_unknown",
    PROVENANCE_COPY: "policy_provenance_copy",
    PROVENANCE_REUSED: "policy_provenance_reused",
    PROVENANCE_MUTATED: "policy_provenance_mutated",
    PROVENANCE_VERSION_UNKNOWN: "policy_contract_version_unknown",
    PROVENANCE_REQUEST_MISMATCH: "policy_request_mismatch",
    PROVENANCE_USER_MISMATCH: "policy_user_mismatch",
    PROVENANCE_SUBJECT_MISMATCH: "policy_subject_mismatch",
    PROVENANCE_ACTION_MISMATCH: "policy_action_mismatch",
    PROVENANCE_ENGINE_MISMATCH: "policy_engine_mismatch",
    PROVENANCE_INCONSISTENT: "policy_provenance_inconsistent",
}

# Registro de emissão do processo. É estado global deliberado: `authorize_action`
# é uma função de módulo e precisa verificar resultados emitidos por qualquer
# instância de PolicyEngine20 do processo. O tamanho é limitado para não crescer
# indefinidamente; uma entrada evictada falha fechado como UNKNOWN.
_ledger = OrderedDict()
_ledger_lock = threading.RLock()


class PolicyPayloadError(ValueError):
    """Payload de política não serializável de forma canônica."""


def _canonical_payload(policy_result: dict) -> bytes:
    payload = {
        key: value
        for key, value in policy_result.items()
        if key != PROVENANCE_KEY
    }
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PolicyPayloadError(
            f"payload de política não canônico: {type(error).__name__}"
        ) from error


def _payload_digest(policy_result: dict) -> str:
    return hashlib.sha256(_canonical_payload(policy_result)).hexdigest()


def _valid_digest(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _HEX_DIGEST_CHARS
        and all(char in "0123456789abcdef" for char in value)
    )


def _result(
    status: str,
    reason: str,
    *,
    evaluation_id=None,
    engine_id=None,
    contract_version=None,
    binding=None,
) -> dict:
    return {
        "status": status,
        "valid": status == PROVENANCE_VALID,
        "blocked_by": _BLOCKED_BY.get(status),
        "reason": reason,
        "evaluation_id": evaluation_id if isinstance(evaluation_id, str) else None,
        "engine_id": engine_id if isinstance(engine_id, str) else None,
        "contract_version": (
            contract_version if type(contract_version) is int else None
        ),
        "binding": binding if isinstance(binding, dict) else None,
    }


def _normalize_subject(user_id, subject_id):
    return user_id if subject_id is None else subject_id


def _issue_policy_result(
    *,
    engine_id: str,
    payload: dict,
    request_id=None,
    user_id=None,
    subject_id=None,
    action=None,
    bound: bool,
) -> dict:
    """Emitir um resultado de política com proveniência registrada.

    Quando ``bound`` é verdadeiro, o resultado só poderá ser consumido por uma
    chamada a ``authorize_action`` com o mesmo ``request_id``, ``user_id``,
    ``subject_id``, ``action`` e (quando verificada) a mesma instância do
    Policy Engine.

    Quando ``bound`` é falso, o resultado é marcado ``UNBOUND`` e **nunca**
    autoriza: ele serve apenas para inspeção/auditoria, como no caminho de
    Break Glass, que não usa política para liberar operação.
    """
    if not isinstance(payload, dict):
        raise PolicyPayloadError("payload de política deve ser objeto")
    if PROVENANCE_KEY in payload:
        raise PolicyPayloadError("payload já contém proveniência")
    engine_error = validate_identifier("engine_id", engine_id)
    if engine_error is not None:
        raise ValueError(engine_error)

    frozen = copy.deepcopy(payload)
    digest = _payload_digest(frozen)

    normalized_subject = _normalize_subject(user_id, subject_id)
    evaluation_id = f"eval_{uuid.uuid4().hex}"
    issued_at = int(time.time() * 1000)

    if bound:
        request_error = validate_identifier("request_id", request_id)
        if request_error is not None:
            raise ValueError(request_error)
        user_error = validate_identifier("user_id", user_id)
        if user_error is not None:
            raise ValueError(user_error)
        subject_error = validate_identifier("subject_id", normalized_subject)
        if subject_error is not None:
            raise ValueError(subject_error)
        if action not in _VALID_ACTIONS:
            raise ValueError("action de política inválida para vinculação")

    provenance = {
        "contract_version": POLICY_PROVENANCE_CONTRACT_VERSION,
        "issuer": PROVENANCE_ISSUER,
        "engine_id": engine_id,
        "evaluation_id": evaluation_id,
        "status": PROVENANCE_ISSUED if bound else PROVENANCE_UNBOUND,
        "request_id": request_id if bound else None,
        "user_id": user_id,
        "subject_id": normalized_subject,
        "action": action if bound else None,
        "payload_sha256": digest,
        # Timestamp é apenas auditoria; não é unicidade nem prazo de validade.
        "issued_at_unix_ms": issued_at,
    }

    result = copy.deepcopy(frozen)
    result[PROVENANCE_KEY] = provenance

    if bound:
        entry = {
            "object": result,
            "engine_id": engine_id,
            "evaluation_id": evaluation_id,
            "binding": {
                "request_id": request_id,
                "user_id": user_id,
                "subject_id": normalized_subject,
                "action": action,
            },
            "payload_sha256": digest,
            "issued_at_unix_ms": issued_at,
            "consumed": False,
            "consumed_at_unix_ms": None,
        }
        with _ledger_lock:
            _ledger[evaluation_id] = entry
            while len(_ledger) > _MAX_EVALUATIONS:
                _ledger.popitem(last=False)

    return result


def verify_policy_result(
    policy_result,
    *,
    request_id,
    user_id,
    subject_id,
    action,
    expected_engine_id=None,
    consume: bool = True,
) -> dict:
    """Verificar proveniência e vínculo contextual antes da autorização.

    Retorna um dicionário com ``status``, ``valid``, ``blocked_by`` e
    ``reason``. Em caso de sucesso, marca a avaliação como consumida (uso
    único) antes de retornar. Uma rejeição **não** consome a avaliação.
    """
    if policy_result is None:
        return _result(PROVENANCE_ABSENT, "policy_result ausente")
    if not isinstance(policy_result, dict):
        return _result(
            PROVENANCE_MALFORMED, "policy_result não é objeto"
        )

    provenance = policy_result.get(PROVENANCE_KEY)
    if provenance is None:
        return _result(
            PROVENANCE_ABSENT,
            "policy_result sem bloco de proveniência; campo textual de origem "
            "não é prova",
        )
    if not isinstance(provenance, dict):
        return _result(
            PROVENANCE_MALFORMED, "bloco de proveniência não é objeto"
        )

    if "contract_version" not in provenance:
        return _result(
            PROVENANCE_MALFORMED, "contract_version ausente na proveniência"
        )
    version = provenance.get("contract_version")
    if type(version) is not int or version != POLICY_PROVENANCE_CONTRACT_VERSION:
        return _result(
            PROVENANCE_VERSION_UNKNOWN,
            f"versão de contrato desconhecida: {version!r}",
            contract_version=version if type(version) is int else None,
        )

    issuer = provenance.get("issuer")
    if issuer != PROVENANCE_ISSUER:
        return _result(
            PROVENANCE_MALFORMED,
            f"emissor de proveniência inválido: {issuer!r}",
            contract_version=version,
        )

    status = provenance.get("status")
    if status == PROVENANCE_UNBOUND:
        return _result(
            PROVENANCE_UNBOUND_STATUS,
            "policy_result emitido sem vínculo contextual; não autoriza",
            contract_version=version,
            engine_id=provenance.get("engine_id"),
            evaluation_id=provenance.get("evaluation_id"),
        )
    if status != PROVENANCE_ISSUED:
        return _result(
            PROVENANCE_MALFORMED,
            f"status de proveniência inválido: {status!r}",
            contract_version=version,
        )

    evaluation_id = provenance.get("evaluation_id")
    evaluation_error = validate_identifier("evaluation_id", evaluation_id)
    if evaluation_error is not None:
        return _result(
            PROVENANCE_MALFORMED, evaluation_error, contract_version=version
        )

    engine_id = provenance.get("engine_id")
    engine_error = validate_identifier("engine_id", engine_id)
    if engine_error is not None:
        return _result(
            PROVENANCE_MALFORMED, engine_error, contract_version=version
        )

    bound_request = provenance.get("request_id")
    bound_user = provenance.get("user_id")
    bound_subject = provenance.get("subject_id")
    bound_action = provenance.get("action")
    for field, value in (
        ("request_id", bound_request),
        ("user_id", bound_user),
        ("subject_id", bound_subject),
    ):
        error = validate_identifier(field, value)
        if error is not None:
            return _result(
                PROVENANCE_MALFORMED,
                f"vínculo inválido na proveniência: {error}",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )
    if bound_action not in _VALID_ACTIONS:
        return _result(
            PROVENANCE_INCONSISTENT,
            f"action de proveniência inválida: {bound_action!r}",
            contract_version=version,
            evaluation_id=evaluation_id,
            engine_id=engine_id,
        )

    bound_digest = provenance.get("payload_sha256")
    if not _valid_digest(bound_digest):
        return _result(
            PROVENANCE_MALFORMED,
            "payload_sha256 inválido na proveniência",
            contract_version=version,
            evaluation_id=evaluation_id,
            engine_id=engine_id,
        )

    try:
        actual_digest = _payload_digest(policy_result)
    except PolicyPayloadError as error:
        return _result(
            PROVENANCE_MALFORMED,
            str(error),
            contract_version=version,
            evaluation_id=evaluation_id,
            engine_id=engine_id,
        )

    if not hmac.compare_digest(actual_digest, bound_digest):
        return _result(
            PROVENANCE_MUTATED,
            "payload de política divergiu do digest emitido",
            contract_version=version,
            evaluation_id=evaluation_id,
            engine_id=engine_id,
        )

    normalized_subject = _normalize_subject(user_id, subject_id)

    with _ledger_lock:
        entry = _ledger.get(evaluation_id)
        if entry is None:
            return _result(
                PROVENANCE_UNKNOWN,
                "avaliação não registrada neste processo (fabricada ou "
                "evictada do registro)",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )
        if entry["object"] is not policy_result:
            return _result(
                PROVENANCE_COPY,
                "objeto apresentado não é o objeto emitido (cópia ou "
                "reconstrução)",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )
        if entry["consumed"]:
            return _result(
                PROVENANCE_REUSED,
                "avaliação já consumida por outra autorização",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )

        ledger_binding = entry["binding"]
        provenance_binding = {
            "request_id": bound_request,
            "user_id": bound_user,
            "subject_id": bound_subject,
            "action": bound_action,
        }
        if (
            entry["engine_id"] != engine_id
            or entry["payload_sha256"] != bound_digest
            or ledger_binding != provenance_binding
        ):
            return _result(
                PROVENANCE_INCONSISTENT,
                "bloco de proveniência diverge do registro de emissão",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )

        if expected_engine_id is not None and entry["engine_id"] != expected_engine_id:
            return _result(
                PROVENANCE_ENGINE_MISMATCH,
                "avaliação emitida por outra instância do Policy Engine",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )
        if ledger_binding["request_id"] != request_id:
            return _result(
                PROVENANCE_REQUEST_MISMATCH,
                "avaliação vinculada a outro request_id",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )
        if ledger_binding["user_id"] != user_id:
            return _result(
                PROVENANCE_USER_MISMATCH,
                "avaliação vinculada a outro user_id",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )
        if ledger_binding["subject_id"] != normalized_subject:
            return _result(
                PROVENANCE_SUBJECT_MISMATCH,
                "avaliação vinculada a outro subject_id",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )
        if ledger_binding["action"] != action:
            return _result(
                PROVENANCE_ACTION_MISMATCH,
                "avaliação vinculada a outra action",
                contract_version=version,
                evaluation_id=evaluation_id,
                engine_id=engine_id,
            )

        if consume:
            entry["consumed"] = True
            entry["consumed_at_unix_ms"] = int(time.time() * 1000)

        return _result(
            PROVENANCE_VALID,
            "avaliação emitida pelo Policy Engine e vinculada à solicitação",
            contract_version=version,
            evaluation_id=evaluation_id,
            engine_id=engine_id,
            binding=dict(ledger_binding),
        )


def ledger_size() -> int:
    """Tamanho atual do registro de emissão; diagnóstico, não autoridade."""
    with _ledger_lock:
        return len(_ledger)
