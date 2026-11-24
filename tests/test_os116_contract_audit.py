# -*- coding: utf-8 -*-
"""Testes OS116 — auditoria transversal dos contratos OS098–OS115.

Foco:

- atribuição explícita do bloqueio `read_only` à política, não ao Hard Block;
- Hard Block continua bloqueando `delete` quando seu próprio limiar é atingido;
- consistência de estados de falha de proveniência e controles;
- leitura parcial vs. escrita fail-closed;
- Break Glass continua sem liberar operação;
- evicção do ledger de proveniência falha fechado;
- manifesto do binário Rust confere com os bytes executáveis.

Nenhum modelo real, API paga, GPU, Android ou SV-01 é usado.
"""
from __future__ import annotations

import hashlib
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
from core import policy_provenance as pp  # noqa: E402
from core.authorization_contract import (  # noqa: E402
    AUTHORIZATION_AUTHORIZED,
    AUTHORIZATION_DENIED,
    AUTHORIZATION_INFRASTRUCTURE_FAILURE,
    AUTHORIZATION_PARTIAL,
    EXECUTION_NOT_EXECUTED,
)
from core.motor_sistema import MotorEmocional  # noqa: E402
from core.policy_engine import PolicyEngine20  # noqa: E402

REQ = "req_os116"


class FakeLiver:
    def __init__(self, stress=0.0):
        self.stress = stress

    def get_stress_level(self):
        return self.stress


class FakeMemory:
    def retrieve_with_status(self, **kwargs):
        return {"status": "MEMORY_NOT_FOUND", "records": [], "error": None}


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


def hard_allow(effective_threshold=95.0):
    return {
        "allowed": True,
        "blocked_by": None,
        "guard_status": "GUARD_OK",
        "effective_threshold": effective_threshold,
        "stress_level": 0.0,
        "reasoning": "fake hard block allow",
    }


def hard_deny():
    return {
        "allowed": False,
        "blocked_by": "hard_block_rust",
        "guard_status": "GUARD_OK",
        "effective_threshold": 95.0,
        "stress_level": 99.0,
        "reasoning": "fake hard block deny",
    }


def kernel_allow():
    return {
        "allowed": True,
        "kernel_status": "KERNEL_ALLOW",
        "blocked_by": None,
        "matched_rule": "fake_allow",
        "reasoning": "fake kernel allow",
    }


def make_motor():
    root = tempfile.mkdtemp(prefix="os116_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os116-key",
        policy_mem_path=os.path.join(root, "policy"),
        context_mem_path=os.path.join(root, "context"),
        dashboard_history=5,
    )
    motor.cortex = CapturingCortex()
    return motor, root


def issue(action="read", stress=0.0, request_id=REQ, user_id="u1"):
    engine = PolicyEngine20(FakeLiver(stress), FakeMemory())
    policy = engine.evaluate(
        user_id,
        "teste",
        request_id=request_id,
        subject_id=None,
        action=action,
    )
    return engine, policy


def binary_available():
    try:
        g._binary_path()
    except g.GuardError:
        return False
    return True


@unittest.skipUnless(
    binary_available(), "binário release e manifesto ausentes no worktree"
)
class ReadOnlyAttributionTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = make_motor()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _level_2_result(self, action):
        self.motor.virtual_liver.reset()
        self.motor.virtual_liver.add_stress(80.0)
        return self.motor.process_interaction(
            "u1",
            "teste",
            "texto",
            action=action,
            target="alvo",
            intent="moderacao",
            request_id=REQ,
        )

    def test_write_block_is_attributed_to_policy_not_hard_block(self):
        for action in ("create", "update", "delete"):
            with self.subTest(action=action):
                result = self._level_2_result(action)
                authorization = result["authorization"]
                self.assertIs(result["blocked"], True)
                self.assertEqual(result["blocked_by"], "policy_read_only")
                self.assertIs(result["guarda_costas"]["allowed"], True)
                self.assertEqual(
                    result["kernel"]["kernel_status"], "KERNEL_ALLOW"
                )
                self.assertIs(authorization["policy_evaluated"], True)
                self.assertEqual(
                    authorization["mechanisms"]["policy"]["status"], "DENIED"
                )
                self.assertEqual(
                    authorization["mechanisms"]["policy"]["blocked_by"],
                    "policy_read_only",
                )
                self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
                self.assertEqual(self.motor.cortex.calls, 0)

    def test_read_at_level_2_is_allowed_by_policy(self):
        result = self._level_2_result("read")
        self.assertNotIn("blocked", result)
        self.assertEqual(
            result["authorization"]["authorization_status"],
            AUTHORIZATION_AUTHORIZED,
        )
        self.assertIs(result["authorization"]["policy_evaluated"], True)
        self.assertIs(result["policy_controls"]["read_only"]["blocked"], False)
        self.assertEqual(self.motor.cortex.calls, 1)


@unittest.skipUnless(binary_available(), "binário do Guarda-Costas ausente")
class HardBlockIndependenceTests(unittest.TestCase):
    def test_delete_at_threshold_is_blocked_by_hard_block(self):
        result = g.hard_block("delete", 95.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "hard_block_rust")
        self.assertEqual(result["guard_status"], "GUARD_OK")
        self.assertEqual(result["effective_threshold"], 95.0)
        self.assertEqual(
            result["binary_integrity"]["status"], "BINARY_VERIFIED"
        )

    def test_create_at_max_stress_is_not_hard_blocked(self):
        result = g.hard_block("create", 100.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertIsNone(result["blocked_by"])
        self.assertEqual(result["guard_status"], "GUARD_OK")

    def test_motor_high_stress_delete_blocks_before_policy(self):
        motor, root = make_motor()
        try:
            motor.virtual_liver.add_stress(99.0)
            result = motor.process_interaction(
                "u1",
                "teste",
                "texto",
                action="delete",
                target="alvo",
                intent="moderacao",
                request_id=REQ,
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "hard_block_rust")
        self.assertEqual(result["kernel_status"], "KERNEL_NOT_EVALUATED")
        self.assertIs(result["authorization"]["policy_evaluated"], False)
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(motor.cortex.calls, 0)


class FailurePropagationTests(unittest.TestCase):
    def test_direct_partial_read_is_not_complete(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = g.authorize_action("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(
            result["authority_scope"], "HARD_BLOCK_KERNEL_ONLY"
        )
        self.assertEqual(result["execution"]["status"], EXECUTION_NOT_EXECUTED)

    def test_direct_write_without_policy_is_denied(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = g.authorize_action(
                "create",
                0.0,
                False,
                "u1",
                target="alvo",
                intent="moderacao",
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_context_required")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)

    def test_provenance_error_is_recorded_as_error_not_absent(self):
        engine, policy = issue()
        with patch.object(
            g, "verify_policy_result", side_effect=RuntimeError("falha")
        ), patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = g.authorize_action(
                "read",
                0.0,
                False,
                "u1",
                policy_result=policy,
                request_id=REQ,
                expected_policy_engine_id=engine.engine_id,
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )
        mechanism = result["mechanisms"]["policy"]
        self.assertEqual(mechanism["provenance"], "REJECTED")
        self.assertEqual(mechanism["provenance_status"], "ERROR")
        self.assertEqual(mechanism["status"], "NOT_EVALUATED")
        self.assertIsNone(result["policy_controls"]["blocked_by_policy"])

    def test_motor_provenance_error_sets_policy_unavailable(self):
        motor, root = make_motor()
        try:
            with patch.object(
                g, "verify_policy_result", side_effect=RuntimeError("falha")
            ), patch.object(
                g, "hard_block", return_value=hard_allow()
            ), patch.object(g, "kernel_check", return_value=kernel_allow()):
                result = motor.process_interaction(
                    "u1", "teste", "texto", action="read", request_id=REQ
                )
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_provenance_error")
        self.assertEqual(result["system_state"], "POLICY_INDISPONIVEL")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")

    def test_allowed_true_only_in_authorized_or_partial_decisions(self):
        cases = []
        with patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            cases.append(
                (
                    "read_partial",
                    g.authorize_action("read", 0.0, False, "u1"),
                )
            )
            engine, policy = issue("read")
            cases.append(
                (
                    "read_authorized",
                    g.authorize_action(
                        "read",
                        0.0,
                        False,
                        "u1",
                        policy_result=policy,
                        request_id=REQ,
                        expected_policy_engine_id=engine.engine_id,
                    ),
                )
            )
            cases.append(
                (
                    "write_no_policy",
                    g.authorize_action(
                        "create",
                        0.0,
                        False,
                        "u1",
                        target="alvo",
                        intent="moderacao",
                    ),
                )
            )
            engine_read_only, policy_read_only = issue(
                "create", stress=80.0
            )
            cases.append(
                (
                    "write_read_only",
                    g.authorize_action(
                        "create",
                        0.0,
                        False,
                        "u1",
                        target="alvo",
                        intent="moderacao",
                        policy_result=policy_read_only,
                        request_id=REQ,
                        expected_policy_engine_id=engine_read_only.engine_id,
                    ),
                )
            )

        engine_error, policy_error = issue("read")
        with patch.object(
            g, "verify_policy_result", side_effect=RuntimeError("falha")
        ), patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            cases.append(
                (
                    "provenance_error",
                    g.authorize_action(
                        "read",
                        0.0,
                        False,
                        "u1",
                        policy_result=policy_error,
                        request_id=REQ,
                        expected_policy_engine_id=engine_error.engine_id,
                    ),
                )
            )

        with patch.object(
            g, "hard_block", return_value=hard_deny()
        ), patch.object(g, "kernel_check", return_value=kernel_allow()):
            cases.append(
                (
                    "hard_block_deny",
                    g.authorize_action("read", 0.0, False, "u1"),
                )
            )

        for label, result in cases:
            with self.subTest(label=label):
                if result["allowed"] is True:
                    self.assertIsNone(result["blocked_by"])
                    self.assertIn(
                        result["authorization_status"],
                        (AUTHORIZATION_AUTHORIZED, AUTHORIZATION_PARTIAL),
                    )
                else:
                    self.assertIsNotNone(result["blocked_by"])
                self.assertEqual(
                    result["execution"]["status"], EXECUTION_NOT_EXECUTED
                )

    def test_motor_controls_error_sets_policy_unavailable(self):
        motor, root = make_motor()
        try:
            with patch.object(
                g, "build_policy_controls", side_effect=RuntimeError("falha")
            ), patch.object(
                g, "hard_block", return_value=hard_allow()
            ), patch.object(g, "kernel_check", return_value=kernel_allow()):
                result = motor.process_interaction(
                    "u1", "teste", "texto", action="read", request_id=REQ
                )
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_internal_error")
        self.assertEqual(result["system_state"], "POLICY_INDISPONIVEL")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")


class ProvenanceLifecycleAuditTests(unittest.TestCase):
    def test_evicted_evaluation_fails_closed(self):
        with patch.object(pp, "_MAX_EVALUATIONS", 1):
            engine = PolicyEngine20(FakeLiver(0.0), FakeMemory())
            first = engine.evaluate(
                "u1",
                "teste",
                request_id=REQ,
                subject_id=None,
                action="read",
            )
            second = engine.evaluate(
                "u1",
                "teste",
                request_id=REQ,
                subject_id=None,
                action="read",
            )
            verification = pp.verify_policy_result(
                first,
                request_id=REQ,
                user_id="u1",
                subject_id=None,
                action="read",
                expected_engine_id=engine.engine_id,
            )
        self.assertIsNotNone(second)
        self.assertEqual(verification["status"], "UNKNOWN")
        self.assertEqual(
            verification["blocked_by"], "policy_provenance_unknown"
        )
        self.assertIs(verification["valid"], False)

    def test_direct_call_without_expected_engine_is_documented_limitation(self):
        """Comportamento conhecido, não usado pelo fluxo principal.

        `process_interaction()` sempre passa `expected_policy_engine_id`.
        Uma chamada direta que o omita aceita um emissor do mesmo processo,
        desde que o vínculo contextual confira. Isto é uma limitação
        documentada, não uma autorização do fluxo principal.
        """
        engine, policy = issue(action="read")
        with patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = g.authorize_action(
                "read",
                0.0,
                False,
                "u1",
                policy_result=policy,
                request_id=REQ,
            )
        self.assertIs(result["allowed"], True)
        self.assertEqual(
            result["mechanisms"]["policy"]["provenance_status"], "VALID"
        )

    def test_break_glass_policy_result_is_unbound_and_cannot_authorize(self):
        motor, root = make_motor()
        try:
            fake = {
                "autorizado": True,
                "break_glass_status": "BREAK_GLASS_AUTHORIZED",
                "motivo_recusa": None,
            }
            with patch.object(g, "break_glass", return_value=fake):
                result = motor.trigger_break_glass("u1")
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertIs(result["authorized"], True)
        self.assertIs(result["operation_authorized"], False)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)
        self.assertEqual(
            result["policy_result"]["provenance"]["status"], "UNBOUND"
        )


@unittest.skipUnless(binary_available(), "binário do Guarda-Costas ausente")
class BinaryManifestAuditTests(unittest.TestCase):
    def test_release_binary_matches_manifest(self):
        manifest = g._load_binary_manifest()
        with open(g._BINARY_RELEASE, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(manifest.get("release"), digest)

    def test_verified_binary_reports_manifest_hash(self):
        binary = g._binary_path()
        manifest = g._load_binary_manifest()
        self.assertEqual(binary.sha256, manifest.get("release"))
        self.assertEqual(binary.label, "release")


if __name__ == "__main__":
    unittest.main()
