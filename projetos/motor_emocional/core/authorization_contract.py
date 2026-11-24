# -*- coding: utf-8 -*-
"""Contrato de identidade, autoridade e decisão de autorização — OS112.

Este módulo não autentica ninguém. Ele classifica a identidade **declarada** e
registra explicitamente que o sistema não possui credenciais, sessão ou prova
de autoria. `user_id`/`subject_id` são valores fornecidos pelo chamador; não
são prova de identidade.

Estados de identidade:
- `IDENTITY_MISSING`: solicitante ausente;
- `IDENTITY_INVALID`: identificador sintaticamente inválido;
- `IDENTITY_UNAUTHENTICATED`: identificador válido, sem autenticação;
- `IDENTITY_AUTHENTICATED`: reservado; não há caminho que o produza;
- `IDENTITY_UNAUTHORIZED`: reservado para autorização explícita de identidade.

Estados de decisão:
- `AUTHORIZED`: Hard Block, Kernel e Policy permitiram a operação;
- `DENIED`: um mecanismo negou;
- `PARTIAL`: decisão incompleta (ex.: `authorize_action` sem política);
- `INFRASTRUCTURE_FAILURE`: falha/indisponibilidade de mecanismo;
- `INCONCLUSIVE`: mecanismo não decidiu (ex.: revisão do Kernel);
- `INPUT_INVALID`: entrada/identidade inválida.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

IDENTITY_MISSING = "IDENTITY_MISSING"
IDENTITY_INVALID = "IDENTITY_INVALID"
IDENTITY_UNAUTHENTICATED = "IDENTITY_UNAUTHENTICATED"
IDENTITY_AUTHENTICATED = "IDENTITY_AUTHENTICATED"
IDENTITY_UNAUTHORIZED = "IDENTITY_UNAUTHORIZED"

AUTHORIZATION_AUTHORIZED = "AUTHORIZED"
AUTHORIZATION_DENIED = "DENIED"
AUTHORIZATION_PARTIAL = "PARTIAL"
AUTHORIZATION_INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
AUTHORIZATION_INCONCLUSIVE = "INCONCLUSIVE"
AUTHORIZATION_INPUT_INVALID = "INPUT_INVALID"

EXECUTION_NOT_EXECUTED = "NOT_EXECUTED"
EXECUTION_CORTEX_ONLY = "CORTEX_ONLY"
EXECUTION_EXECUTED = "EXECUTED"

IDENTITY_VALID_STATES = frozenset({
    IDENTITY_UNAUTHENTICATED,
    IDENTITY_AUTHENTICATED,
})
IDENTITY_STATES = frozenset({
    IDENTITY_MISSING,
    IDENTITY_INVALID,
    IDENTITY_UNAUTHENTICATED,
    IDENTITY_AUTHENTICATED,
    IDENTITY_UNAUTHORIZED,
})
AUTHORIZATION_STATUSES = frozenset({
    AUTHORIZATION_AUTHORIZED,
    AUTHORIZATION_DENIED,
    AUTHORIZATION_PARTIAL,
    AUTHORIZATION_INFRASTRUCTURE_FAILURE,
    AUTHORIZATION_INCONCLUSIVE,
    AUTHORIZATION_INPUT_INVALID,
})

_MAX_IDENTIFIER_CHARS = 256
_MAX_REQUEST_ID_CHARS = 128


def _has_control_or_format(value: str) -> bool:
    for char in value:
        code = ord(char)
        if code < 32 or code == 127:
            return True
        if (
            0x200B <= code <= 0x200F
            or 0x202A <= code <= 0x202E
            or 0x2060 <= code <= 0x206F
            or code == 0xFEFF
        ):
            return True
    return False


def validate_identifier(field: str, value, max_chars: int = _MAX_IDENTIFIER_CHARS):
    """Validar sintaticamente um identificador declarado.

    Isto **não** é autenticação. Retorna uma mensagem de erro ou `None`.
    """
    if value is None:
        return f"{field} ausente"
    if not isinstance(value, str):
        return f"{field} deve ser string; recebido: {type(value).__name__}"
    if not value.strip():
        return f"{field} vazio"
    if value != value.strip():
        return f"{field} com espaço no início ou no fim"
    if len(value) > max_chars:
        return f"{field} excede {max_chars} caracteres"
    if _has_control_or_format(value):
        return f"{field} contém caractere de controle/formatação"
    return None


def new_request_id() -> str:
    """Identificador de correlação; não é credencial nem prova de identidade."""
    return f"req_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class IdentityContext:
    """Identidade declarada e seu estado de autenticação."""

    requester_id: str | None
    subject_id: str | None
    authentication_status: str
    identity_status: str
    subject_status: str
    authority_basis: str
    subject_is_requester: bool
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.identity_status in IDENTITY_VALID_STATES

    def to_dict(self) -> dict:
        return {
            "requester": {
                "declared_id": self.requester_id,
                "authentication_status": self.authentication_status,
                "identity_status": self.identity_status,
                "authority_basis": self.authority_basis,
            },
            "subject": {
                "declared_id": self.subject_id,
                "is_requester": self.subject_is_requester,
                "authentication_status": self.authentication_status,
                "identity_status": self.subject_status,
            },
            "error": self.error,
        }


def build_identity_context(requester_id, subject_id=None) -> IdentityContext:
    """Classificar a identidade declarada sem inventar autenticação.

    - identidade válida é sempre `IDENTITY_UNAUTHENTICATED` neste sistema;
    - `subject_id` ausente significa que o sujeito é o próprio solicitante;
    - sujeito inválido invalida a solicitação.
    """
    requester_error = validate_identifier("user_id", requester_id)
    if requester_id is None:
        requester_status = IDENTITY_MISSING
    elif requester_error is not None and not isinstance(requester_id, str):
        requester_status = IDENTITY_INVALID
    elif requester_error is not None:
        requester_status = IDENTITY_INVALID
    else:
        requester_status = IDENTITY_UNAUTHENTICATED

    subject_value = requester_id if subject_id is None else subject_id
    subject_error = validate_identifier("subject_id", subject_value)
    if subject_id is None:
        subject_status = requester_status
        subject_error = requester_error if requester_status != IDENTITY_UNAUTHENTICATED else None
    elif subject_error is not None:
        subject_status = IDENTITY_INVALID
    else:
        subject_status = IDENTITY_UNAUTHENTICATED

    identity_status = requester_status
    error = requester_error
    if identity_status in IDENTITY_VALID_STATES and subject_status not in IDENTITY_VALID_STATES:
        identity_status = IDENTITY_INVALID
        error = subject_error or "sujeito afetado inválido"

    authority_basis = (
        "DECLARED_IDENTITY_ONLY"
        if identity_status in IDENTITY_VALID_STATES
        else "NONE"
    )
    return IdentityContext(
        requester_id=requester_id if isinstance(requester_id, str) else None,
        subject_id=subject_value if isinstance(subject_value, str) else None,
        authentication_status=IDENTITY_UNAUTHENTICATED,
        identity_status=identity_status,
        subject_status=subject_status,
        authority_basis=authority_basis,
        subject_is_requester=(subject_id is None),
        error=error,
    )


def derive_authorization_status(
    *,
    identity: IdentityContext,
    hard_block,
    kernel,
    policy_controls=None,
    policy_evaluated: bool = False,
):
    """Classificar a decisão final a partir dos mecanismos avaliados.

    A ordem de precedência é identidade -> Hard Block -> Kernel -> Policy.
    Uma negação anterior não é reavaliada por um mecanismo posterior. Falha,
    ausência ou resposta inconclusiva nunca resultam em `AUTHORIZED`.
    """
    if identity is None or not identity.is_valid:
        return (
            AUTHORIZATION_INPUT_INVALID,
            (identity.error if identity is not None else "identidade ausente")
            or "identidade inválida",
        )

    if not isinstance(hard_block, dict) or not hard_block:
        return (
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
            "Hard Block não produziu veredicto",
        )
    guard_status = hard_block.get("guard_status")
    if guard_status != "GUARD_OK":
        if guard_status == "GUARD_INVALID_INPUT":
            return AUTHORIZATION_INPUT_INVALID, "Hard Block rejeitou a entrada"
        return (
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
            f"Hard Block indisponível/falhou: {guard_status or 'sem status'}",
        )
    if hard_block.get("allowed") is not True:
        return (
            AUTHORIZATION_DENIED,
            f"Hard Block negou: {hard_block.get('blocked_by') or 'sem motivo'}",
        )

    if not isinstance(kernel, dict) or not kernel:
        return (
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
            "Kernel não produziu veredicto",
        )
    kernel_status = kernel.get("kernel_status")
    if kernel_status == "KERNEL_INVALID_INPUT":
        return AUTHORIZATION_INPUT_INVALID, "Kernel rejeitou a entrada"
    if kernel_status in (
        "KERNEL_UNAVAILABLE",
        "KERNEL_ERROR",
        "KERNEL_NOT_EVALUATED",
        None,
    ):
        return (
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
            f"Kernel indisponível/falhou: {kernel_status or 'sem status'}",
        )
    if kernel.get("allowed") is not True:
        if kernel_status == "KERNEL_REVIEW":
            return (
                AUTHORIZATION_INCONCLUSIVE,
                "Kernel exige revisão; não há autorização",
            )
        return (
            AUTHORIZATION_DENIED,
            f"Kernel negou: {kernel.get('blocked_by') or kernel_status}",
        )
    if kernel_status != "KERNEL_ALLOW":
        return (
            AUTHORIZATION_INCONCLUSIVE,
            f"Kernel não autorizou: {kernel_status}",
        )

    if isinstance(policy_controls, dict):
        blocked_by = policy_controls.get("blocked_by_policy")
        if blocked_by:
            return AUTHORIZATION_DENIED, f"Policy negou: {blocked_by}"

    if not policy_evaluated:
        return (
            AUTHORIZATION_PARTIAL,
            "Policy Engine não avaliado; decisão não é completa",
        )

    return (
        AUTHORIZATION_AUTHORIZED,
        "Hard Block, Kernel e Policy permitiram a operação",
    )


def build_authorization_record(
    *,
    request_id: str,
    identity: IdentityContext,
    action: str,
    target=None,
    intent=None,
    threat_type=None,
    hard_block=None,
    kernel=None,
    policy_controls=None,
    decision: str,
    decision_reason: str,
    policy_evaluated: bool,
    complete: bool,
    execution_status: str,
    execution_detail: str,
    reincidence_basis=None,
    timestamp_unix_ms=None,
    policy_provenance=None,
) -> dict:
    """Registro auditável e sem segredos de uma decisão de autorização.

    `policy_provenance` é o resultado da verificação OS115. O campo textual
    `mechanisms.policy.provenance` registra o que foi verificado; ele não é,
    por si só, prova de origem. A autoridade é o registro de emissão do
    Policy Engine consultado antes da decisão.
    """
    identity_dict = identity.to_dict() if identity is not None else {}
    hard = hard_block if isinstance(hard_block, dict) else {}
    kern = kernel if isinstance(kernel, dict) else {}
    controls = policy_controls if isinstance(policy_controls, dict) else {}
    read_only_control = controls.get("read_only")
    if not isinstance(read_only_control, dict):
        read_only_control = {}
    threshold_control = controls.get("adjusted_threshold")
    if not isinstance(threshold_control, dict):
        threshold_control = {}
    timestamp = timestamp_unix_ms if timestamp_unix_ms is not None else int(
        time.time() * 1000
    )
    policy_blocked_by = controls.get("blocked_by_policy")
    if policy_blocked_by:
        policy_status = "DENIED"
    elif not policy_evaluated:
        policy_status = "NOT_EVALUATED"
    else:
        policy_status = "EVALUATED"

    provenance = (
        policy_provenance if isinstance(policy_provenance, dict) else {}
    )
    provenance_status = provenance.get("status")
    if provenance_status is None:
        provenance_status = "ABSENT" if not policy_evaluated else "UNKNOWN"
    if provenance_status == "VALID":
        provenance_label = "ISSUED_BY_POLICY_ENGINE_IN_PROCESS"
    elif provenance_status == "ABSENT":
        provenance_label = "ABSENT"
    elif provenance_status == "UNKNOWN":
        provenance_label = "CALLER_DECLARED_UNVERIFIED"
    else:
        provenance_label = "REJECTED"
    return {
        "contract_version": 1,
        "request_id": request_id,
        "requester": identity_dict.get("requester", {}),
        "subject": identity_dict.get("subject", {}),
        "action": action,
        "target_declared": target if isinstance(target, str) else None,
        "intent_declared": intent if isinstance(intent, str) else None,
        "threat_type": threat_type if isinstance(threat_type, str) else None,
        "decision": decision,
        "decision_reason": decision_reason,
        "policy_evaluated": bool(policy_evaluated),
        "authorization_complete": bool(complete),
        "mechanisms": {
            "identity": {
                "status": identity.identity_status if identity else IDENTITY_MISSING,
                "authentication_status": (
                    identity.authentication_status
                    if identity
                    else IDENTITY_UNAUTHENTICATED
                ),
            },
            "hard_block": {
                "allowed": hard.get("allowed"),
                "guard_status": hard.get("guard_status"),
                "blocked_by": hard.get("blocked_by"),
            },
            "kernel": {
                "allowed": kern.get("allowed"),
                "kernel_status": kern.get("kernel_status"),
                "matched_rule": kern.get("matched_rule"),
            },
            "policy": {
                "evaluated": bool(policy_evaluated),
                "blocked_by": policy_blocked_by,
                "status": policy_status,
                "level": controls.get("policy_level"),
                "read_only_calculated": read_only_control.get("calculated"),
                "read_only_valid": read_only_control.get("valid"),
                "adjusted_threshold_status": threshold_control.get("status"),
                # OS115: o rótulo registra o resultado da verificação feita
                # contra o registro de emissão. Texto não é a autoridade.
                "provenance": provenance_label,
                "provenance_status": provenance_status,
                "evaluation_id": provenance.get("evaluation_id"),
                "engine_id": provenance.get("engine_id"),
                "contract_version": provenance.get("contract_version"),
            },
        },
        "execution": {
            "status": execution_status,
            "action_executed": False,
            "detail": execution_detail,
        },
        "reincidence_basis": reincidence_basis,
        "timestamp_unix_ms": timestamp,
    }


def build_evidence_record(
    *,
    request_id: str,
    identity: IdentityContext,
    event_id=None,
    emitter_id=None,
    subject_id=None,
    evidence_status: str,
    evidence_authorized: bool,
    reason=None,
    timestamp_unix_ms=None,
) -> dict:
    """Registro de evidência do Break Glass; não autoriza operação."""
    timestamp = timestamp_unix_ms if timestamp_unix_ms is not None else int(
        time.time() * 1000
    )
    return {
        "contract_version": 1,
        "request_id": request_id,
        "requester": {
            "declared_id": identity.requester_id if identity else None,
            "authentication_status": (
                identity.authentication_status
                if identity
                else IDENTITY_UNAUTHENTICATED
            ),
            "identity_status": (
                identity.identity_status if identity else IDENTITY_MISSING
            ),
            "authority_basis": (
                identity.authority_basis if identity else "NONE"
            ),
        },
        "subject": {
            "declared_id": subject_id,
            "is_requester": (
                identity.subject_is_requester if identity else False
            ),
        },
        "event_id": event_id if isinstance(event_id, str) else None,
        "emitter_id": emitter_id if isinstance(emitter_id, str) else None,
        "evidence_status": evidence_status,
        "evidence_authorized": bool(evidence_authorized),
        "operation_authorized": False,
        "reason": reason,
        "execution": {
            "status": EXECUTION_NOT_EXECUTED,
            "action_executed": False,
            "detail": "Break Glass valida evidência; não libera Hard Block/Kernel",
        },
        "timestamp_unix_ms": timestamp,
    }
