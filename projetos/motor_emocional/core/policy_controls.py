# -*- coding: utf-8 -*-
"""Controles do Policy Engine e sua aplicação efetiva — OS112.

Este módulo é a fonte única para transformar `policy_result` em controles
auditáveis e para decidir se um controle bloqueia a operação. Ele é usado pelo
motor e por `guarda_costas.authorize_action()` para evitar duas lógicas
divergentes de política.

Regras preservadas das OS105/OS106:
- `read_only` bloqueia create/update/delete no nível 2;
- `adjusted_threshold` é verificado para `delete`;
- `connection_cut`, `max_words`, `latency_ms` e `judicial_alibi` permanecem
  calculados/informativos quando o contrato é insuficiente;
- nenhum controle de política pode liberar uma negação de Hard Block/Kernel.
"""
from __future__ import annotations

import math

_POLICY_WRITE_ACTIONS = frozenset({"create", "update", "delete"})


def validate_policy_result(policy_result):
    """Validar a estrutura mínima de um resultado declarado de política.

    Isto **não** prova que o resultado foi produzido pelo Policy Engine nem o
    vincula a uma requisição, ação ou identidade. Ele apenas impede que um
    objeto vazio ou sem os campos indispensáveis seja tratado como política
    avaliada.

    Desde a OS115, `authorize_action()` complementa esta checagem com
    `policy_provenance.verify_policy_result()`. Um dicionário que passa aqui
    mas não tem proveniência registrada **não** autoriza; ele é rejeitado com
    `policy_provenance_missing`. Esta função continua sendo útil para
    validação estrutural isolada e para `build_policy_controls()`.

    Retorna `None` quando a estrutura mínima existe ou uma mensagem textual
    quando ela falta.
    """
    if not isinstance(policy_result, dict):
        return "policy_result deve ser objeto"
    level = policy_result.get("policy_level")
    if type(level) is not int or not 0 <= level <= 3:
        return "policy_level ausente ou fora de 0..3"
    modifiers = policy_result.get("modifiers")
    if not isinstance(modifiers, dict):
        return "modifiers ausente ou não é objeto"
    if "read_only" not in modifiers:
        return "modifiers.read_only ausente"
    return None


def _valid_threshold_percent(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 100.0
    )


def build_policy_controls(policy_result, action, hard_block=None, enforced=True):
    """Separar política calculada de política efetivamente aplicada.

    `read_only` tem contrato suficiente: no nível 2, somente `read` passa.
    `connection_cut` é registrado como calculado, mas permanece não aplicado
    porque o contrato existente não define escopo/direção/exceções.
    `max_words`, `latency_ms` e `judicial_alibi` também são calculados e não
    aplicados; o status é `CALCULATED_ONLY` e nunca vira autorização.
    `adjusted_threshold` é confrontado com o limiar efetivo do Hard Block.
    """
    if not isinstance(policy_result, dict):
        policy_result = {}
    modifiers = policy_result.get("modifiers")
    if not isinstance(modifiers, dict):
        modifiers = {}

    raw_level = policy_result.get("policy_level")
    level_valid = type(raw_level) is int and 0 <= raw_level <= 3
    raw_read_only = modifiers.get("read_only")
    read_only_valid = type(raw_read_only) is bool
    read_only_calculated = raw_read_only if read_only_valid else None

    connection_cut_present = "connection_cut" in modifiers
    raw_connection_cut = modifiers.get("connection_cut")
    connection_cut_valid = (
        not connection_cut_present or type(raw_connection_cut) is bool
    )
    connection_cut_calculated = (
        raw_connection_cut if connection_cut_valid and connection_cut_present else None
    )

    def _optional_control(name, validator, contract_status):
        present = name in modifiers
        raw = modifiers.get(name)
        valid = (not present) or validator(raw)
        calculated = raw if present and valid else None
        if not present:
            status = "NOT_CALCULATED"
        elif not valid:
            status = "INVALID"
        else:
            status = "CALCULATED_ONLY"
        return {
            "calculated": calculated,
            "valid": valid,
            "enforced": False,
            "status": status,
            "contract_status": contract_status,
        }

    def _nonnegative_number(value):
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and float(value) >= 0.0
        )

    def _max_words_valid(value):
        return value is None or (type(value) is int and value >= 0)

    max_words_control = _optional_control(
        "max_words", _max_words_valid, "CONTRACT_INCOMPLETE"
    )
    max_words_control["unit"] = "UNDEFINED"
    max_words_control["application_point"] = "UNDEFINED"

    latency_control = _optional_control(
        "latency_ms", _nonnegative_number, "CONTRACT_INCOMPLETE"
    )
    latency_control["semantics"] = "UNDEFINED_DELAY_OR_TIMEOUT_OR_DEADLINE"

    alibi_control = _optional_control(
        "judicial_alibi", lambda value: type(value) is bool, "INFORMATIONAL_ONLY"
    )
    alibi_control["authority"] = "NONE"

    blocked_by = None
    if enforced and action in _POLICY_WRITE_ACTIONS:
        if read_only_calculated is True:
            blocked_by = "policy_read_only"
        elif read_only_calculated is not False:
            blocked_by = "policy_state_invalid"
        elif not level_valid:
            blocked_by = "policy_state_invalid"

    adjusted = policy_result.get("adjusted_threshold")
    adjusted_valid = adjusted is None or _valid_threshold_percent(adjusted)
    hard_value = None
    if isinstance(hard_block, dict):
        hard_value = hard_block.get("effective_threshold")
    hard_valid = hard_value is None or _valid_threshold_percent(hard_value)

    equals_hard = None
    hard_not_weaker = None
    if action != "delete":
        # O limiar ajustado é um limiar de delete no Hard Block. Para
        # read/create/update ele não é aplicável e não pode gerar bloqueio.
        threshold_status = "NOT_APPLICABLE"
    elif adjusted is None:
        threshold_status = "NOT_PROVIDED"
    elif not adjusted_valid:
        threshold_status = "POLICY_VALUE_INVALID"
        if enforced and blocked_by is None:
            blocked_by = "policy_threshold_invalid"
    elif hard_value is None:
        threshold_status = "HARD_BLOCK_VALUE_MISSING"
    elif not hard_valid:
        threshold_status = "HARD_BLOCK_VALUE_INVALID"
        if enforced and blocked_by is None:
            blocked_by = "policy_threshold_invalid"
    else:
        equals_hard = abs(float(hard_value) - float(adjusted)) <= 0.01
        hard_not_weaker = float(hard_value) <= float(adjusted) + 0.01
        if equals_hard:
            threshold_status = "MATCH"
        elif hard_not_weaker:
            threshold_status = "HARD_BLOCK_STRICTER"
        else:
            threshold_status = "POLICY_STRICTER_NOT_APPLIED"
            if enforced and blocked_by is None:
                blocked_by = "policy_threshold_not_applied"

    return {
        "policy_level": raw_level if level_valid else None,
        "policy_level_valid": level_valid,
        "action": action,
        "is_reincident": policy_result.get("is_reincident"),
        "read_only": {
            "calculated": read_only_calculated,
            "valid": read_only_valid,
            "enforced": bool(enforced),
            "blocked": blocked_by == "policy_read_only",
            "contract_status": "IMPLEMENTED",
        },
        "connection_cut": {
            "calculated": connection_cut_calculated,
            "valid": connection_cut_valid,
            "enforced": False,
            "status": (
                "INVALID"
                if connection_cut_present and not connection_cut_valid
                else "CONTRACT_INCOMPLETE"
                if connection_cut_present
                else "NOT_CALCULATED"
            ),
            "applies_to": "UNDEFINED",
            "reversal": "UNDEFINED",
        },
        "max_words": max_words_control,
        "latency_ms": latency_control,
        "judicial_alibi": alibi_control,
        "adjusted_threshold": {
            "policy_value": (
                float(adjusted) if adjusted_valid and adjusted is not None else None
            ),
            "hard_block_value": (
                float(hard_value) if hard_valid and hard_value is not None else None
            ),
            "equals_hard_block": equals_hard,
            "hard_block_not_weaker": hard_not_weaker,
            "enforced": bool(enforced),
            "status": threshold_status,
        },
        "blocked_by_policy": blocked_by,
    }
