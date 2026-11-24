# -*- coding: utf-8 -*-
"""Testes OS112 — identidade, autoridade e integridade da autorização.

Todos os mecanismos externos são falsos (Hard Block, Kernel, Break Glass e
Córtex). Nenhuma ação CRUD, modelo real, rede, API paga ou SV-01 é usada.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402
from core import web_server  # noqa: E402
from core.authorization_contract import (  # noqa: E402
    AUTHORIZATION_AUTHORIZED,
    AUTHORIZATION_DENIED,
    AUTHORIZATION_INCONCLUSIVE,
    AUTHORIZATION_INFRASTRUCTURE_FAILURE,
    AUTHORIZATION_INPUT_INVALID,
    AUTHORIZATION_PARTIAL,
    IDENTITY_UNAUTHENTICATED,
)
from core.motor_sistema import MotorEmocional  # noqa: E402
from core.policy_engine import PolicyEngine20  # noqa: E402


def _hard_allow(effective_threshold=95.0):
    return {
        "allowed": True,
        "blocked_by": None,
        "guard_status": "GUARD_OK",
        "effective_threshold": effective_threshold,
        "stress_level": 0.0,
        "reasoning": "fake hard block allow",
    }


def _hard_deny(blocked_by="hard_block_rust", status="GUARD_OK"):
    return {
        "allowed": False,
        "blocked_by": blocked_by,
        "guard_status": status,
        "effective_threshold": 95.0,
        "stress_level": 99.0,
        "reasoning": "fake hard block deny",
    }


def _kernel_allow():
    return {
        "allowed": True,
        "kernel_status": "KERNEL_ALLOW",
        "blocked_by": None,
        "matched_rule": "fake_allow",
        "reasoning": "fake kernel allow",
    }


def _kernel_deny():
    return {
        "allowed": False,
        "kernel_status": "KERNEL_DENY",
        "blocked_by": "kernel_constitucional",
        "matched_rule": "fake_deny",
        "reasoning": "fake kernel deny",
    }


def _kernel_review():
    return {
        "allowed": False,
        "kernel_status": "KERNEL_REVIEW",
        "blocked_by": "kernel_review",
        "matched_rule": "fake_review",
        "reasoning": "fake kernel review",
    }


def _kernel_unavailable():
    return {
        "allowed": False,
        "kernel_status": "KERNEL_UNAVAILABLE",
        "blocked_by": "kernel_unavailable",
        "matched_rule": None,
        "reasoning": "fake kernel unavailable",
    }


def _raw_policy(
    *,
    level=0,
    read_only=False,
    adjusted=None,
    connection_cut=None,
    max_words=None,
    latency_ms=None,
    judicial_alibi=None,
    action="teste",
):
    """Payload estrutural para testes isolados de `build_policy_controls`.

    Este dicionário NÃO tem proveniência e por isso não pode autorizar.
    """
    modifiers = {"read_only": read_only}
    if connection_cut is not None:
        modifiers["connection_cut"] = connection_cut
    if max_words is not None:
        modifiers["max_words"] = max_words
    if latency_ms is not None:
        modifiers["latency_ms"] = latency_ms
    if judicial_alibi is not None:
        modifiers["judicial_alibi"] = judicial_alibi
    result = {
        "policy_level": level,
        "stress_percent": 50.0,
        "action": action,
        "is_reincident": False,
        "modifiers": modifiers,
        "history_status": "MEMORY_NOT_FOUND",
        "history_error": None,
        "history_similarity": None,
        "reincidence_unknown": False,
    }
    if adjusted is not None:
        result["adjusted_threshold"] = adjusted
    return result


class _MutableLiver:
    def __init__(self, stress=0.0):
        self.stress = stress

    def get_stress_level(self):
        return self.stress


class _FakeMemory:
    def retrieve_with_status(self, **kwargs):
        return {"status": "MEMORY_NOT_FOUND", "records": [], "error": None}


class _ReincidentMemory:
    def retrieve_with_status(self, **kwargs):
        return {
            "status": "MEMORY_FOUND",
            "records": [
                {
                    "similarity": 0.9,
                    "distance": 0.1,
                    "memory": {
                        "integrity_status": "verified",
                        "schema_version": 2,
                    },
                }
            ],
            "error": None,
        }


_LEVEL_STRESS = {0: 0.0, 1: 70.0, 2: 80.0, 3: 99.0}
_DIRECT_LIVER = _MutableLiver()
_DIRECT_ENGINE = PolicyEngine20(_DIRECT_LIVER, _FakeMemory())
_DIRECT_ENGINE_ID = _DIRECT_ENGINE.engine_id
_REQ = "req_os112_direct"


def _policy(
    *,
    level=0,
    action="read",
    user_id="u1",
    subject_id=None,
    request_id=_REQ,
    read_only=None,
    adjusted=None,
    connection_cut=None,
    max_words=None,
    latency_ms=None,
    judicial_alibi=None,
):
    """Emitir um resultado genuíno do Policy Engine para a ação indicada.

    Os parâmetros de modificadores existem apenas por compatibilidade de
    chamada; valores inválidos são testados em `build_policy_controls`
    diretamente, porque o Policy Engine real não os produz.
    """
    _DIRECT_LIVER.stress = _LEVEL_STRESS[level]
    return _DIRECT_ENGINE.evaluate(
        user_id,
        "teste",
        request_id=request_id,
        subject_id=subject_id,
        action=action,
    )


def _authorize(*args, **kwargs):
    """Chamada direta com o request_id vinculado usado por `_policy`."""
    kwargs.setdefault("request_id", _REQ)
    kwargs.setdefault("expected_policy_engine_id", _DIRECT_ENGINE_ID)
    return g.authorize_action(*args, **kwargs)


class CapturingCortex:
    def __init__(self):
        self.calls = 0

    async def generate_response_result(self, **kwargs):
        self.calls += 1
        return {
            "status": "CORTEX_OK",
            "response": "ok",
            "requested_mode": "api",
            "effective_mode": "api",
            "provider": "fake",
            "model": "fake",
            "model_served": "fake",
            "attempt": 1,
            "failover_used": False,
            "fallback_used": False,
            "error": None,
            "http_status": None,
        }


def _real_guard_available() -> bool:
    return os.path.isfile(g._BINARY_RELEASE) and os.path.isfile(g._BINARY_MANIFEST)


def _motor():
    root = tempfile.mkdtemp(prefix="os112_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os112-key",
        policy_mem_path=os.path.join(root, "policy"),
        context_mem_path=os.path.join(root, "context"),
        dashboard_history=5,
    )
    motor.cortex = CapturingCortex()
    return motor, root


class DirectAuthorizationContractTests(unittest.TestCase):
    def test_direct_write_without_policy_context_is_partial_fail_closed(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = _authorize(
                "delete", 0.0, False, "u1",
                target="alvo", intent="moderacao",
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_context_required")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)
        self.assertIs(result["policy_evaluated"], False)
        self.assertEqual(result["authority_scope"], "HARD_BLOCK_KERNEL_ONLY")
        self.assertIn("partial_reason", result)
        self.assertEqual(result["execution"]["status"], "NOT_EXECUTED")
        self.assertIs(result["execution"]["action_executed"], False)

    def test_direct_read_without_policy_is_not_complete(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = _authorize("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["authority_scope"], "HARD_BLOCK_KERNEL_ONLY")
        self.assertEqual(result["execution"]["status"], "NOT_EXECUTED")

    def test_direct_read_with_policy_is_complete_but_unauthenticated(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=0, read_only=False),
            )
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_AUTHORIZED)
        self.assertIs(result["authorization_complete"], True)
        self.assertEqual(result["authority_scope"], "HARD_BLOCK_KERNEL_POLICY")
        self.assertEqual(
            result["requester"]["authentication_status"], IDENTITY_UNAUTHENTICATED
        )
        self.assertEqual(result["requester"]["authority_basis"], "DECLARED_IDENTITY_ONLY")
        self.assertEqual(result["mechanisms"]["policy"]["status"], "EVALUATED")

    def test_identity_missing_is_input_invalid(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = _authorize("read", 0.0, False, None)
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "guard_invalid_input")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_INPUT_INVALID)
        self.assertEqual(result["requester"]["identity_status"], "IDENTITY_MISSING")
        self.assertIs(result["authorization_complete"], False)

    def test_identity_invalid_is_rejected(self):
        for value in ("", " u1", "u1 ", "u\x00", "u\u202e1", 123):
            with self.subTest(value=repr(value)):
                with patch.object(
                    g, "hard_block", return_value=_hard_allow()
                ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
                    result = _authorize("read", 0.0, False, value)
                self.assertIs(result["allowed"], False)
                self.assertEqual(
                    result["authorization_status"], AUTHORIZATION_INPUT_INVALID
                )
                self.assertIn(
                    result["requester"]["identity_status"],
                    ("IDENTITY_INVALID", "IDENTITY_MISSING"),
                )

    def test_requester_and_subject_are_distinct_fields(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = _authorize(
                "read", 0.0, False, "requester-1",
                subject_id="subject-2",
                policy_result=_policy(
                    level=0,
                    action="read",
                    user_id="requester-1",
                    subject_id="subject-2",
                ),
            )
        self.assertEqual(result["requester"]["declared_id"], "requester-1")
        self.assertEqual(result["subject"]["declared_id"], "subject-2")
        self.assertIs(result["subject"]["is_requester"], False)
        self.assertEqual(
            result["requester"]["authentication_status"], IDENTITY_UNAUTHENTICATED
        )

    def test_policy_cannot_be_bypassed_on_direct_write(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            no_policy = _authorize(
                "create", 0.0, False, "u1",
                target="alvo", intent="moderacao",
            )
            with_policy = _authorize(
                "create", 0.0, False, "u1",
                target="alvo", intent="moderacao",
                policy_result=_policy(level=2, action="create"),
            )
        self.assertIs(no_policy["allowed"], False)
        self.assertEqual(no_policy["blocked_by"], "policy_context_required")
        self.assertIs(with_policy["allowed"], False)
        self.assertEqual(with_policy["blocked_by"], "policy_read_only")
        self.assertEqual(with_policy["authorization_status"], AUTHORIZATION_DENIED)
        self.assertEqual(with_policy["mechanisms"]["policy"]["status"], "DENIED")

    def test_hard_block_cannot_be_bypassed_by_policy(self):
        with patch.object(
            g, "hard_block", return_value=_hard_deny()
        ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
            result = _authorize(
                "delete", 99.0, False, "u1",
                target="alvo", intent="moderacao",
                policy_result=_policy(level=0, action="delete"),
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "hard_block_rust")
        self.assertEqual(result["kernel_status"], "KERNEL_NOT_EVALUATED")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)

    def test_kernel_cannot_be_bypassed_by_policy(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_deny()
        ):
            result = _authorize(
                "delete", 0.0, False, "u1",
                target="minoria", intent="perseguicao",
                policy_result=_policy(level=0, action="delete"),
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "kernel_constitucional")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)

    def test_order_is_identity_hard_block_kernel_policy(self):
        order = []

        def hard(*args, **kwargs):
            order.append("hard_block")
            return _hard_allow()

        def kernel(*args, **kwargs):
            order.append("kernel")
            return _kernel_allow()

        original_controls = g.build_policy_controls

        def controls(*args, **kwargs):
            order.append("policy")
            return original_controls(*args, **kwargs)

        with patch.object(g, "hard_block", side_effect=hard), patch.object(
            g, "kernel_check", side_effect=kernel
        ), patch.object(g, "build_policy_controls", side_effect=controls):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=0, read_only=False),
            )
        self.assertIs(result["allowed"], True)
        self.assertEqual(order, ["hard_block", "kernel", "policy"])


class MechanismFailureTests(unittest.TestCase):
    def test_hard_block_unavailable_is_infrastructure_failure(self):
        with patch.object(
            g,
            "hard_block",
            return_value=_hard_deny("guard_unavailable", "GUARD_UNAVAILABLE"),
        ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=0, read_only=False),
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(
            result["authorization_status"], AUTHORIZATION_INFRASTRUCTURE_FAILURE
        )
        self.assertEqual(result["mechanisms"]["hard_block"]["guard_status"], "GUARD_UNAVAILABLE")

    def test_kernel_unavailable_is_infrastructure_failure(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_unavailable()
        ):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=0, read_only=False),
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(
            result["authorization_status"], AUTHORIZATION_INFRASTRUCTURE_FAILURE
        )

    def test_kernel_review_is_inconclusive_not_denied_or_allowed(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_review()
        ):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=0, read_only=False),
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_INCONCLUSIVE)

    def test_policy_engine_exception_is_infrastructure_failure(self):
        motor, root = _motor()
        try:
            with patch.object(
                motor.policy_engine,
                "evaluate",
                side_effect=RuntimeError("falha simulada"),
            ):
                result = motor.process_interaction("u1", "teste", "texto")
            self.assertIs(result["blocked"], True)
            self.assertEqual(result["system_state"], "POLICY_INDISPONIVEL")
            self.assertEqual(
                result["authorization"]["authorization_status"],
                AUTHORIZATION_INFRASTRUCTURE_FAILURE,
            )
            self.assertEqual(
                result["authorization"]["execution"]["status"], "NOT_EXECUTED"
            )
            self.assertIs(
                result["authorization"]["execution"]["action_executed"], False
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_exception_during_authorization_never_allows(self):
        motor, root = _motor()
        try:
            with patch.object(
                g, "hard_block", side_effect=RuntimeError("falha simulada")
            ):
                result = motor.process_interaction(
                    "u1", "teste", "texto", action="read"
                )
            self.assertIs(result["blocked"], True)
            self.assertEqual(result["blocked_by"], "guard_internal_error")
            self.assertEqual(
                result["authorization"]["authorization_status"],
                AUTHORIZATION_INFRASTRUCTURE_FAILURE,
            )
            self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_direct_hard_block_exception_is_explicit_failure(self):
        with patch.object(
            g, "hard_block", side_effect=RuntimeError("falha simulada")
        ):
            result = _authorize("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "guard_internal_error")
        self.assertEqual(
            result["authorization_status"], AUTHORIZATION_INFRASTRUCTURE_FAILURE
        )
        self.assertEqual(result["execution"]["status"], "NOT_EXECUTED")

    def test_policy_controls_exception_is_explicit_failure(self):
        with patch.object(
            g, "hard_block", return_value=_hard_allow()
        ), patch.object(g, "kernel_check", return_value=_kernel_allow()), patch.object(
            g, "build_policy_controls", side_effect=RuntimeError("falha simulada")
        ):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=0, read_only=False),
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_internal_error")
        self.assertEqual(
            result["authorization_status"], AUTHORIZATION_INFRASTRUCTURE_FAILURE
        )
        self.assertEqual(result["policy_controls"]["status"], "POLICY_INTERNAL_ERROR")


class PolicyControlTests(unittest.TestCase):
    @unittest.skipUnless(
        _real_guard_available(), "binário release e manifesto ausentes no worktree"
    )
    def test_read_only_blocks_all_write_actions_in_motor(self):
        motor, root = _motor()
        try:
            def set_level_2_stress():
                # OS116: isolar o teste da acumulação que pode levar o
                # delete ao limiar do Hard Block (95%). Cada interação
                # adiciona 5%; 80 + 5 = 85, bem abaixo do limiar e ainda
                # no nível 2 (read_only=True).
                motor.virtual_liver.reset()
                motor.virtual_liver.add_stress(80.0)

            for action in ("create", "update", "delete"):
                with self.subTest(action=action):
                    set_level_2_stress()
                    result = motor.process_interaction(
                        "u1", "teste", "texto", action=action,
                        target="alvo", intent="moderacao",
                    )
                    self.assertIs(result["blocked"], True)
                    self.assertEqual(result["blocked_by"], "policy_read_only")
                    self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
                    authorization = result["authorization"]
                    self.assertEqual(
                        authorization["authorization_status"],
                        AUTHORIZATION_DENIED,
                    )
                    # O bloqueio veio da política, não do Hard Block/Kernel.
                    self.assertIs(result["guarda_costas"]["allowed"], True)
                    self.assertEqual(
                        result["kernel"]["kernel_status"], "KERNEL_ALLOW"
                    )
                    self.assertEqual(
                        authorization["mechanisms"]["hard_block"]["allowed"],
                        True,
                    )
                    self.assertEqual(
                        authorization["mechanisms"]["kernel"]["kernel_status"],
                        "KERNEL_ALLOW",
                    )
                    self.assertIs(authorization["policy_evaluated"], True)
                    self.assertEqual(
                        authorization["mechanisms"]["policy"]["status"],
                        "DENIED",
                    )
                    self.assertEqual(
                        authorization["mechanisms"]["policy"]["blocked_by"],
                        "policy_read_only",
                    )
                    self.assertIs(
                        result["policy_controls"]["read_only"]["blocked"], True
                    )

            set_level_2_stress()
            read = motor.process_interaction(
                "u1", "teste", "texto", action="read",
                target="alvo", intent="moderacao",
            )
            self.assertNotIn("blocked", read)
            self.assertEqual(
                read["authorization"]["authorization_status"],
                AUTHORIZATION_AUTHORIZED,
            )
            self.assertIs(read["authorization"]["policy_evaluated"], True)
            self.assertIs(read["policy_controls"]["read_only"]["blocked"], False)
            self.assertEqual(
                read["authorization"]["mechanisms"]["policy"]["status"],
                "EVALUATED",
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_adjusted_threshold_is_applied_and_never_weakens_hard_block(self):
        def reincident_policy():
            engine = PolicyEngine20(_MutableLiver(99.0), _ReincidentMemory())
            policy = engine.evaluate(
                "u1", "teste", request_id=_REQ, action="delete"
            )
            return engine, policy

        with patch.object(
            g, "hard_block", return_value=_hard_allow(95.0)
        ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
            engine, policy = reincident_policy()
            stricter = _authorize(
                "delete", 0.0, False, "u1",
                target="alvo", intent="moderacao",
                policy_result=policy,
                expected_policy_engine_id=engine.engine_id,
            )

        with patch.object(
            g, "hard_block", return_value=_hard_allow(66.5)
        ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
            engine, policy = reincident_policy()
            match = _authorize(
                "delete", 0.0, False, "u1",
                target="alvo", intent="moderacao",
                policy_result=policy,
                expected_policy_engine_id=engine.engine_id,
            )

        with patch.object(
            g, "hard_block", return_value=_hard_allow(60.0)
        ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
            engine, policy = reincident_policy()
            weaker = _authorize(
                "delete", 0.0, False, "u1",
                target="alvo", intent="moderacao",
                policy_result=policy,
                expected_policy_engine_id=engine.engine_id,
            )

        self.assertIs(stricter["allowed"], False)
        self.assertEqual(stricter["blocked_by"], "policy_threshold_not_applied")
        self.assertEqual(
            stricter["policy_controls"]["adjusted_threshold"]["status"],
            "POLICY_STRICTER_NOT_APPLIED",
        )
        self.assertIs(match["allowed"], True)
        self.assertEqual(
            match["policy_controls"]["adjusted_threshold"]["status"], "MATCH"
        )
        self.assertIs(weaker["allowed"], True)
        self.assertEqual(
            weaker["policy_controls"]["adjusted_threshold"]["status"],
            "HARD_BLOCK_STRICTER",
        )

        # Valor inválido não pode ser emitido pelo Policy Engine real; o
        # controle isolado continua fail-closed para payloads estruturais.
        invalid_controls = g.build_policy_controls(
            _raw_policy(level=0, adjusted=float("nan")),
            "delete",
            _hard_allow(),
            enforced=True,
        )
        self.assertEqual(
            invalid_controls["blocked_by_policy"], "policy_threshold_invalid"
        )

    def test_connection_cut_remains_contract_incomplete(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=3, connection_cut=True),
            )
        self.assertIs(result["allowed"], True)
        control = result["policy_controls"]["connection_cut"]
        self.assertIs(control["calculated"], True)
        self.assertIs(control["enforced"], False)
        self.assertEqual(control["status"], "CONTRACT_INCOMPLETE")
        self.assertEqual(control["applies_to"], "UNDEFINED")
        self.assertEqual(control["reversal"], "UNDEFINED")

    def test_max_words_valid_and_invalid_are_not_silently_enforced(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            valid = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=1),
            )
        self.assertIs(valid["allowed"], True)
        self.assertEqual(
            valid["policy_controls"]["max_words"]["status"], "CALCULATED_ONLY"
        )
        self.assertIs(valid["policy_controls"]["max_words"]["enforced"], False)
        self.assertEqual(
            valid["policy_controls"]["max_words"]["unit"], "UNDEFINED"
        )

        invalid = g.build_policy_controls(
            _raw_policy(level=1, max_words=-1),
            "read",
            _hard_allow(),
            enforced=True,
        )
        self.assertIs(invalid["max_words"]["valid"], False)
        self.assertEqual(invalid["max_words"]["status"], "INVALID")

    def test_latency_ms_has_no_invented_timeout_semantics(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            valid = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=1),
            )
        self.assertIs(valid["allowed"], True)
        self.assertEqual(
            valid["policy_controls"]["latency_ms"]["status"], "CALCULATED_ONLY"
        )
        self.assertIs(valid["policy_controls"]["latency_ms"]["enforced"], False)
        self.assertEqual(
            valid["policy_controls"]["latency_ms"]["semantics"],
            "UNDEFINED_DELAY_OR_TIMEOUT_OR_DEADLINE",
        )

        invalid = g.build_policy_controls(
            _raw_policy(level=1, latency_ms=-1),
            "read",
            _hard_allow(),
            enforced=True,
        )
        self.assertIs(invalid["latency_ms"]["valid"], False)
        self.assertEqual(invalid["latency_ms"]["status"], "INVALID")

    def test_judicial_alibi_has_no_release_authority(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=3, judicial_alibi=True),
            )
        control = result["policy_controls"]["judicial_alibi"]
        self.assertIs(control["calculated"], True)
        self.assertIs(control["enforced"], False)
        self.assertEqual(control["authority"], "NONE")

        with patch.object(
            g, "hard_block", return_value=_hard_deny()
        ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
            denied = _authorize(
                "delete", 99.0, False, "u1",
                target="alvo", intent="moderacao",
                policy_result=_policy(level=3, action="delete"),
            )
        self.assertIs(denied["allowed"], False)
        self.assertEqual(denied["blocked_by"], "hard_block_rust")


class MotorAuthorizationTests(unittest.TestCase):
    def test_identity_missing_in_main_flow_is_input_invalid(self):
        motor, root = _motor()
        try:
            result = motor.process_interaction(None, "teste", "texto")
            self.assertIs(result["blocked"], True)
            self.assertEqual(result["blocked_by"], "guard_invalid_input")
            self.assertEqual(
                result["authorization"]["authorization_status"],
                AUTHORIZATION_INPUT_INVALID,
            )
            self.assertEqual(
                result["authorization"]["requester"]["identity_status"],
                "IDENTITY_MISSING",
            )
            self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_subject_is_recorded_separately_in_main_flow(self):
        motor, root = _motor()
        try:
            with patch.object(
                g, "hard_block", return_value=_hard_allow()
            ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
                result = motor.process_interaction(
                    "requester-1", "teste", "texto", action="read",
                    subject_id="subject-2",
                )
            auth = result["authorization"]
            self.assertEqual(auth["requester"]["declared_id"], "requester-1")
            self.assertEqual(auth["subject"]["declared_id"], "subject-2")
            self.assertIs(auth["subject"]["is_requester"], False)
            self.assertEqual(
                auth["requester"]["authentication_status"],
                IDENTITY_UNAUTHENTICATED,
            )
            self.assertEqual(auth["authorization_status"], AUTHORIZATION_AUTHORIZED)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_no_result_presents_unauthenticated_as_authenticated(self):
        motor, root = _motor()
        try:
            with patch.object(
                g, "hard_block", return_value=_hard_allow()
            ), patch.object(g, "kernel_check", return_value=_kernel_allow()):
                read = motor.process_interaction(
                    "u1", "teste", "texto", action="read",
                    target="alvo", intent="moderacao",
                )
                write = motor.process_interaction(
                    "u1", "teste", "texto", action="create",
                    target="alvo", intent="moderacao",
                )
            direct = _authorize(
                "read", 0.0, False, "u1",
                policy_result=_policy(level=0, read_only=False),
            )
            for payload in (read["authorization"], write["authorization"], direct):
                self.assertEqual(
                    payload["requester"]["authentication_status"],
                    IDENTITY_UNAUTHENTICATED,
                )
                self.assertNotEqual(
                    payload["requester"]["authentication_status"],
                    "IDENTITY_AUTHENTICATED",
                )
                self.assertEqual(
                    payload["requester"]["authority_basis"],
                    "DECLARED_IDENTITY_ONLY",
                )
        finally:
            shutil.rmtree(root, ignore_errors=True)


class BreakGlassAuthorizationTests(unittest.TestCase):
    def test_break_glass_evidence_does_not_authorize_operation(self):
        motor, root = _motor()
        try:
            fake = {
                "autorizado": True,
                "break_glass_status": "BREAK_GLASS_AUTHORIZED",
                "motivo_recusa": None,
            }
            with patch.object(g, "break_glass", return_value=fake):
                result = motor.trigger_break_glass("u1")
            self.assertIs(result["authorized"], True)
            self.assertIs(result["evidence_authorized"], True)
            self.assertIs(result["operation_authorized"], False)
            self.assertIs(result["authorization_complete"], False)
            self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)
            self.assertEqual(
                result["authorization"]["execution"]["status"], "NOT_EXECUTED"
            )
            self.assertIs(
                result["authorization"]["execution"]["action_executed"], False
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_break_glass_without_evidence_is_denied_and_does_not_touch_guard(self):
        motor, root = _motor()
        try:
            with patch.object(
                g, "hard_block", side_effect=AssertionError("não deve chamar")
            ), patch.object(
                g, "kernel_check", side_effect=AssertionError("não deve chamar")
            ):
                result = motor.trigger_break_glass("u1")
            self.assertIs(result["authorized"], False)
            self.assertIs(result["evidence_authorized"], False)
            self.assertIs(result["operation_authorized"], False)
            self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
            self.assertEqual(result["authorization"]["operation_authorized"], False)
            self.assertEqual(
                result["authorization"]["execution"]["status"], "NOT_EXECUTED"
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_break_glass_invalid_identity_is_input_invalid(self):
        motor, root = _motor()
        try:
            result = motor.trigger_break_glass(" u1")
            self.assertIs(result["authorized"], False)
            self.assertEqual(
                result["authorization_status"], AUTHORIZATION_INPUT_INVALID
            )
            self.assertEqual(
                result["authorization"]["requester"]["identity_status"],
                "IDENTITY_INVALID",
            )
            self.assertEqual(result["authorization"]["execution"]["status"], "NOT_EXECUTED")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class HttpAuthorizationBoundaryTests(unittest.TestCase):
    class JsonRequest:
        def __init__(self, payload):
            self.payload = payload
            self.headers = {}

        async def json(self):
            return self.payload

        async def stream(self):
            yield json.dumps(self.payload).encode("utf-8")

    def test_interact_forwards_subject_and_request_ids(self):
        captured = {}

        class FakeMotor:
            def process_interaction(self, **kwargs):
                captured.update(kwargs)
                return {"authorization_status": "AUTHORIZED", "response": "ok"}

        with patch.object(web_server, "motor", FakeMotor()):
            response = asyncio.run(
                web_server.api_interact(
                    self.JsonRequest(
                        {
                            "user_id": "u1",
                            "subject_id": "u2",
                            "request_id": "req_http_1",
                        }
                    )
                )
            )
        self.assertEqual(response["response"], "ok")
        self.assertEqual(captured["subject_id"], "u2")
        self.assertEqual(captured["request_id"], "req_http_1")

    def test_interact_input_invalid_identity_returns_400(self):
        class FakeMotor:
            def process_interaction(self, **kwargs):
                return {
                    "blocked": True,
                    "blocked_by": "guard_invalid_input",
                    "authorization_status": "INPUT_INVALID",
                }

        with patch.object(web_server, "motor", FakeMotor()):
            response = asyncio.run(
                web_server.api_interact(
                    self.JsonRequest({"user_id": None})
                )
            )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
