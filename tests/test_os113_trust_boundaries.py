# -*- coding: utf-8 -*-
"""Testes OS113 — fronteiras de confiança e integridade da autorização.

Cobrem as seis frentes da OS113:

- proveniência declarada de `policy_result`;
- contrato das primitivas públicas;
- integridade dos registros de decisão em memória;
- identidade/substituição do binário Rust;
- paridade Python/Rust com os mesmos vetores;
- caminhos de contorno conhecidos.

Todos os mecanismos externos são falsos ou locais. Nenhuma ação CRUD, modelo
real, rede, API paga, GPU ou SV-01 é usada. Os testes de binário substituto
executam apenas scripts temporários criados pelo próprio teste.
"""
from __future__ import annotations

import asyncio
import atexit
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
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
    AUTHORIZATION_INFRASTRUCTURE_FAILURE,
    AUTHORIZATION_INPUT_INVALID,
    AUTHORIZATION_PARTIAL,
    EXECUTION_CORTEX_ONLY,
    EXECUTION_NOT_EXECUTED,
    build_authorization_record,
    build_identity_context,
)
from core.motor_sistema import MotorEmocional  # noqa: E402
from core.policy_engine import PolicyEngine20  # noqa: E402


_TEMP_MANIFEST_DIR = tempfile.mkdtemp(prefix="os113_manifest_")
atexit.register(shutil.rmtree, _TEMP_MANIFEST_DIR, ignore_errors=True)
_DUMMY_MANIFEST = os.path.join(_TEMP_MANIFEST_DIR, "binary_sha256.txt")
with open(_DUMMY_MANIFEST, "w", encoding="utf-8") as _handle:
    _handle.write("release " + "0" * 64 + "\n")


def _real_guard_available() -> bool:
    return os.path.isfile(g._BINARY_RELEASE) and os.path.isfile(g._BINARY_MANIFEST)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hard_allow():
    return {
        "allowed": True,
        "blocked_by": None,
        "guard_status": "GUARD_OK",
        "effective_threshold": 95.0,
        "stress_level": 0.0,
        "reasoning": "fake hard block allow",
    }


def _hard_deny(blocked_by="hard_block_rust"):
    return {
        "allowed": False,
        "blocked_by": blocked_by,
        "guard_status": "GUARD_OK",
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


def _policy(
    *,
    level=0,
    read_only=False,
    adjusted=None,
    request_id=None,
    user_id=None,
    subject_id=None,
    action="teste",
):
    modifiers = {"read_only": read_only}
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
    if request_id is not None:
        result["request_id"] = request_id
    if user_id is not None:
        result["user_id"] = user_id
    if subject_id is not None:
        result["subject_id"] = subject_id
    return result


class _FakeLiver:
    def __init__(self, stress=0.0):
        self.stress = stress

    def get_stress_level(self):
        return self.stress


class _FakeMemory:
    def retrieve_with_status(self, **kwargs):
        return {"status": "MEMORY_NOT_FOUND", "records": [], "error": None}


def _new_policy_engine(stress=0.0):
    return PolicyEngine20(_FakeLiver(stress), _FakeMemory())


def _issued_policy(
    *,
    action="read",
    stress=0.0,
    request_id="req_policy",
    user_id="u1",
    subject_id=None,
    engine=None,
):
    engine = engine or _new_policy_engine(stress)
    policy = engine.evaluate(
        user_id,
        "teste",
        request_id=request_id,
        subject_id=subject_id,
        action=action,
    )
    return engine, policy


def _kernel_payload(**overrides):
    payload = {
        "status": "ok",
        "kernel_status": "KERNEL_ALLOW",
        "allowed": True,
        "kernel_panic": False,
        "ring": 3,
        "action": "read",
        "operation_class": "observation_read",
        "target_category": "unclassified",
        "intent_category": "operations",
        "from_majority_vote": False,
        "requires_review": False,
        "matched_rule": "no_ring0_trigger",
        "reasoning": "KERNEL ALLOW",
    }
    payload.update(overrides)
    return payload


def _hard_payload(**overrides):
    payload = {
        "status": "ok",
        "allowed": True,
        "blocked_by": None,
        "effective_threshold": 95.0,
        "stress_level": 0.0,
        "reasoning": "fake hard block",
    }
    payload.update(overrides)
    return payload


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


class MotorTestCase(unittest.TestCase):
    def make_motor(self, history=5):
        root = tempfile.mkdtemp(prefix="os113_motor_")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        motor = MotorEmocional(
            cortex_api_key="fake-os113-key",
            policy_mem_path=os.path.join(root, "policy"),
            context_mem_path=os.path.join(root, "context"),
            dashboard_history=history,
        )
        motor.cortex = CapturingCortex()
        return motor


def _binary_available():
    try:
        g._binary_path()
    except g.GuardError:
        return False
    return True


BINARIO = _binary_available()


def _raw_cli(envelope, binary=None):
    return subprocess.run(
        [binary or g._binary_path()],
        input=json.dumps(envelope, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=10,
    )


def _make_executable(directory, body, name="guarda_costas"):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(body))
    os.chmod(path, 0o755)
    return path


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(directory, entries, name="binary_sha256.txt"):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# manifesto de teste OS114\n")
        for label, digest in entries.items():
            handle.write(f"{label} {digest}\n")
    return path


# ---------------------------------------------------------------------------
# Frente A — proveniência de policy_result
# ---------------------------------------------------------------------------


class PolicyResultProvenanceTests(MotorTestCase):
    """OS115: proveniência registrada e vínculo contextual.

    Os testes negativos usam dicionários fabricados/copiados de propósito.
    Eles não representam chamadas legítimas ao Policy Engine.
    """

    def _authorize(
        self,
        action="read",
        policy_result=None,
        user_id="u1",
        subject_id=None,
        request_id="req_policy",
        expected_engine_id=None,
        hard=None,
        kernel=None,
    ):
        with patch.object(
            g, "hard_block", return_value=hard or _hard_allow()
        ), patch.object(g, "kernel_check", return_value=kernel or _kernel_allow()):
            return g.authorize_action(
                action,
                0.0,
                False,
                user_id,
                target="alvo" if action != "read" else None,
                intent="moderacao" if action != "read" else None,
                policy_result=policy_result,
                subject_id=subject_id,
                request_id=request_id,
                expected_policy_engine_id=expected_engine_id,
            )

    def _read(self, motor, request_id="req_os113"):
        return motor.process_interaction(
            "u1", "teste", "texto", action="read", request_id=request_id
        )

    # -- ausência e estrutura ------------------------------------------------

    def test_absent_policy_write_is_denied(self):
        result = self._authorize("delete")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_context_required")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)

    def test_absent_policy_read_is_partial(self):
        result = self._authorize("read")
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["authority_scope"], "HARD_BLOCK_KERNEL_ONLY")
        self.assertEqual(
            result["mechanisms"]["policy"]["provenance"], "ABSENT"
        )

    def test_empty_policy_result_is_rejected_for_read(self):
        result = self._authorize("read", policy_result={})
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_state_invalid")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["mechanisms"]["policy"]["status"], "DENIED")

    def test_policy_result_without_modifiers_is_rejected(self):
        result = self._authorize("read", policy_result={"policy_level": 0})
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_state_invalid")

    def test_policy_result_without_read_only_is_rejected(self):
        result = self._authorize(
            "read", policy_result={"policy_level": 0, "modifiers": {}}
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_state_invalid")

    def test_policy_result_with_invalid_level_is_rejected(self):
        result = self._authorize(
            "read",
            policy_result={
                "policy_level": "0",
                "modifiers": {"read_only": False},
            },
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_state_invalid")

    def test_non_dict_policy_result_is_rejected(self):
        for value in ([], "policy", 1, None):
            with self.subTest(value=repr(value)):
                if value is None:
                    result = self._authorize("read", policy_result=None)
                    self.assertEqual(
                        result["authorization_status"], AUTHORIZATION_PARTIAL
                    )
                else:
                    result = self._authorize("read", policy_result=value)
                    self.assertIs(result["allowed"], False)
                    self.assertEqual(
                        result["blocked_by"], "policy_state_invalid"
                    )

    # -- resultado legítimo --------------------------------------------------

    def test_genuine_policy_is_authorized_and_bound(self):
        engine, policy = _issued_policy(action="delete")
        result = self._authorize(
            "delete",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_AUTHORIZED)
        self.assertIs(result["authorization_complete"], True)
        self.assertEqual(result["authority_scope"], "HARD_BLOCK_KERNEL_POLICY")
        mechanism = result["mechanisms"]["policy"]
        self.assertEqual(
            mechanism["provenance"], "ISSUED_BY_POLICY_ENGINE_IN_PROCESS"
        )
        self.assertEqual(mechanism["provenance_status"], "VALID")
        self.assertEqual(mechanism["contract_version"], 1)
        self.assertIsInstance(mechanism["evaluation_id"], str)
        self.assertEqual(result["policy_provenance"]["status"], "VALID")

    # -- campos textuais não são proveniência --------------------------------

    def test_legacy_complete_dict_is_rejected(self):
        """OS113 aceitava isto; OS115 passou a rejeitar sem proveniência."""
        result = self._authorize(
            "delete", policy_result=_policy(level=0, read_only=False)
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_missing")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(
            result["policy_provenance"]["status"], "ABSENT"
        )

    def test_textual_source_field_is_not_provenance(self):
        fabricated = _policy(level=0, read_only=False)
        fabricated["source"] = "PolicyEngine"
        fabricated["issuer"] = "PolicyEngine20"
        result = self._authorize("delete", policy_result=fabricated)
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_missing")

    # -- vinculação ----------------------------------------------------------

    def test_missing_request_id_cannot_authorize_genuine_policy(self):
        engine, policy = _issued_policy(action="read", request_id="req_policy")
        result = self._authorize(
            "read",
            policy_result=policy,
            request_id=None,
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_request_mismatch")

    def test_other_request_id_is_rejected(self):
        engine, policy = _issued_policy(action="read", request_id="req_policy")
        result = self._authorize(
            "read",
            policy_result=policy,
            request_id="req_outra",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_request_mismatch")

    def test_other_user_id_is_rejected(self):
        engine, policy = _issued_policy(
            action="read", request_id="req_policy", user_id="u1"
        )
        result = self._authorize(
            "read",
            policy_result=policy,
            user_id="u2",
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_user_mismatch")

    def test_other_subject_id_is_rejected(self):
        engine, policy = _issued_policy(
            action="read",
            request_id="req_policy",
            user_id="u1",
            subject_id="subject_1",
        )
        result = self._authorize(
            "read",
            policy_result=policy,
            user_id="u1",
            subject_id="subject_2",
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_subject_mismatch")

    def test_other_action_is_rejected(self):
        engine, policy = _issued_policy(action="read", request_id="req_policy")
        result = self._authorize(
            "delete",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_action_mismatch")

    def test_other_engine_instance_is_rejected(self):
        engine, policy = _issued_policy(action="read", request_id="req_policy")
        other_engine = _new_policy_engine()
        result = self._authorize(
            "read",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=other_engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_engine_mismatch")

    # -- reutilização, cópia e alteração ------------------------------------

    def test_policy_cannot_be_reused(self):
        engine, policy = _issued_policy(action="delete")
        first = self._authorize(
            "delete",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        second = self._authorize(
            "delete",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(first["allowed"], True)
        self.assertIs(second["allowed"], False)
        self.assertEqual(second["blocked_by"], "policy_provenance_reused")

    def test_policy_copy_is_rejected(self):
        engine, policy = _issued_policy(action="read")
        copied = dict(policy)
        result = self._authorize(
            "read",
            policy_result=copied,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_copy")

    def test_policy_deepcopy_is_rejected(self):
        engine, policy = _issued_policy(action="read")
        copied = copy.deepcopy(policy)
        result = self._authorize(
            "read",
            policy_result=copied,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_copy")

    def test_policy_mutation_is_rejected(self):
        engine, policy = _issued_policy(action="delete", stress=80.0)
        # Nível 2 emitido com read_only=True; alterar depois da emissão
        # tenta transformar a política em permissiva.
        policy["modifiers"]["read_only"] = False
        policy["policy_level"] = 0
        result = self._authorize(
            "delete",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_mutated")

    def test_unknown_contract_version_is_rejected(self):
        engine, policy = _issued_policy(action="read")
        policy["provenance"]["contract_version"] = 999
        result = self._authorize(
            "read",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_contract_version_unknown")

    def test_inconsistent_binding_fields_are_rejected(self):
        engine, policy = _issued_policy(action="read", request_id="req_policy")
        policy["provenance"]["request_id"] = "req_forjado"
        result = self._authorize(
            "read",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(
            result["blocked_by"], "policy_provenance_inconsistent"
        )

    def test_unknown_evaluation_id_is_rejected(self):
        engine, policy = _issued_policy(action="read")
        policy["provenance"]["evaluation_id"] = "eval_forjada"
        result = self._authorize(
            "read",
            policy_result=policy,
            request_id="req_policy",
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_unknown")

    # -- integração com o motor ---------------------------------------------

    def test_main_flow_blocks_read_when_policy_context_is_incomplete(self):
        motor = self.make_motor()
        incomplete = {
            "stress_percent": 50.0,
            "policy_level": 0,
            "action": "Resposta normal",
        }
        with patch.object(
            motor.policy_engine, "evaluate", return_value=incomplete
        ), patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = motor.process_interaction(
                "u1", "teste", "texto", action="read"
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_state_invalid")
        self.assertEqual(
            result["authorization_status"], AUTHORIZATION_DENIED
        )
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(motor.cortex.calls, 0)

    def test_main_flow_rejects_fabricated_policy(self):
        motor = self.make_motor()
        with patch.object(
            motor.policy_engine,
            "evaluate",
            return_value=_policy(level=0, read_only=False),
        ), patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id="req_fab"
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_provenance_missing")
        self.assertEqual(
            result["authorization_status"], AUTHORIZATION_DENIED
        )
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(motor.cortex.calls, 0)

    def test_main_flow_rejects_policy_from_other_engine(self):
        motor = self.make_motor()
        other_engine, other_policy = _issued_policy(
            action="read", request_id="req_cross"
        )
        with patch.object(
            motor.policy_engine, "evaluate", return_value=other_policy
        ), patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id="req_cross"
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_engine_mismatch")
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")

    def test_policy_engine_failure_is_distinct_from_provenance_failure(self):
        motor = self.make_motor()
        with patch.object(
            motor.policy_engine,
            "evaluate",
            side_effect=RuntimeError("falha simulada"),
        ):
            result = motor.process_interaction("u1", "teste", "texto")
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_internal_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")

    @unittest.skipUnless(
        _real_guard_available(), "binário release e manifesto ausentes no worktree"
    )
    def test_audit_record_declares_verified_provenance(self):
        motor = self.make_motor()
        self._read(motor)
        stored = motor.authorization_history[-1]
        mechanism = stored["mechanisms"]["policy"]
        self.assertEqual(
            mechanism["provenance"], "ISSUED_BY_POLICY_ENGINE_IN_PROCESS"
        )
        self.assertEqual(mechanism["provenance_status"], "VALID")
        self.assertIsInstance(mechanism["evaluation_id"], str)
        self.assertNotIn("policy_result", stored)

    def test_provenance_verification_exception_never_allows(self):
        engine, policy = _issued_policy(action="read")
        with patch.object(
            g, "verify_policy_result", side_effect=RuntimeError("falha simulada")
        ):
            result = self._authorize(
                "read",
                policy_result=policy,
                request_id="req_policy",
                expected_engine_id=engine.engine_id,
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )

    def test_policy_controls_exception_after_valid_provenance_never_allows(self):
        engine, policy = _issued_policy(action="read")
        with patch.object(
            g, "build_policy_controls", side_effect=RuntimeError("falha simulada")
        ):
            result = self._authorize(
                "read",
                policy_result=policy,
                request_id="req_policy",
                expected_engine_id=engine.engine_id,
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_internal_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )


# ---------------------------------------------------------------------------
# Frente B — primitivas públicas
# ---------------------------------------------------------------------------


class PublicPrimitiveContractTests(unittest.TestCase):
    def test_hard_block_allow_is_only_an_isolated_evaluation(self):
        with patch.object(g, "_run_rust", return_value=_hard_payload()):
            result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertNotIn("authorization_status", result)
        self.assertNotIn("authorization_complete", result)
        self.assertNotIn("execution", result)

    def test_kernel_check_allow_is_only_an_isolated_evaluation(self):
        with patch.object(g, "_run_rust", return_value=_kernel_payload()):
            result = g.kernel_check("read", "u1", "leitura")
        self.assertIs(result["allowed"], True)
        self.assertNotIn("authorization_status", result)
        self.assertNotIn("authorization_complete", result)
        self.assertNotIn("execution", result)

    def test_authorize_read_without_policy_is_partial_and_not_executed(self):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = g.authorize_action("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)
        self.assertEqual(result["execution"]["status"], EXECUTION_NOT_EXECUTED)
        self.assertIs(result["execution"]["action_executed"], False)

    def test_authorize_with_policy_is_authorized_but_not_executed(self):
        engine, policy = _issued_policy(action="read")
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = g.authorize_action(
                "read",
                0.0,
                False,
                "u1",
                policy_result=policy,
                request_id="req_policy",
                expected_policy_engine_id=engine.engine_id,
            )
        self.assertEqual(result["authorization_status"], AUTHORIZATION_AUTHORIZED)
        self.assertEqual(result["execution"]["status"], EXECUTION_NOT_EXECUTED)
        self.assertIs(result["execution"]["action_executed"], False)

    def test_policy_controls_helper_has_no_authority(self):
        controls = g.build_policy_controls(
            _policy(level=2, read_only=True), "create", _hard_allow(), enforced=False
        )
        self.assertIsNone(controls["blocked_by_policy"])
        self.assertNotIn("allowed", controls)
        self.assertNotIn("authorization_status", controls)
        self.assertNotIn("execution", controls)

    def test_http_interact_does_not_forward_policy_result(self):
        captured = {}

        class FakeMotor:
            def process_interaction(self, **kwargs):
                captured.update(kwargs)
                return {"response": "ok", "authorization_status": "AUTHORIZED"}

        class Request:
            headers = {}

            async def json(self):
                return {
                    "user_id": "u1",
                    "policy_result": _policy(level=0, read_only=False),
                    "authorization": {"decision": "AUTHORIZED"},
                    "hard_block": _hard_allow(),
                }

            async def stream(self):
                yield json.dumps(self.payload).encode("utf-8")

        request = Request()
        request.payload = {
            "user_id": "u1",
            "policy_result": _policy(level=0, read_only=False),
            "authorization": {"decision": "AUTHORIZED"},
            "hard_block": _hard_allow(),
        }
        with patch.object(web_server, "motor", FakeMotor()):
            response = asyncio.run(web_server.api_interact(request))
        self.assertEqual(response["response"], "ok")
        self.assertNotIn("policy_result", captured)
        self.assertNotIn("authorization", captured)
        self.assertNotIn("hard_block", captured)

    def test_http_interact_action_is_caller_chosen_but_not_executed(self):
        captured = {}

        class FakeMotor:
            def process_interaction(self, **kwargs):
                captured.update(kwargs)
                return {"response": "ok", "authorization_status": "PARTIAL"}

        class Request:
            headers = {}

            async def stream(self):
                yield json.dumps({"user_id": "u1", "action": "read"}).encode()

        with patch.object(web_server, "motor", FakeMotor()):
            result = asyncio.run(web_server.api_interact(Request()))
        self.assertEqual(result["response"], "ok")
        self.assertEqual(captured["action"], "read")
        self.assertNotIn("execution", result)

    def test_break_glass_endpoint_never_authorizes_operation(self):
        class FakeMotor:
            def trigger_break_glass(self, **kwargs):
                return {
                    "authorized": True,
                    "evidence_authorized": True,
                    "operation_authorized": False,
                    "authorization_status": "PARTIAL",
                }

        class Request:
            headers = {}

            async def stream(self):
                yield json.dumps({"user_id": "u1"}).encode()

        with patch.object(web_server, "motor", FakeMotor()):
            result = asyncio.run(web_server.api_break_glass(Request()))
        self.assertIs(result["authorized"], True)
        self.assertIs(result["operation_authorized"], False)

    def test_authorization_record_builder_is_not_authority(self):
        identity = build_identity_context("u1")
        record = build_authorization_record(
            request_id="req_fabricado",
            identity=identity,
            action="delete",
            target="alvo",
            intent="moderacao",
            hard_block=_hard_allow(),
            kernel=_kernel_allow(),
            policy_controls=None,
            decision=AUTHORIZATION_AUTHORIZED,
            decision_reason="fabricado pelo chamador",
            policy_evaluated=True,
            complete=True,
            execution_status=EXECUTION_CORTEX_ONLY,
            execution_detail="nenhum executor foi acionado",
        )
        self.assertEqual(record["decision"], AUTHORIZATION_AUTHORIZED)
        self.assertIs(record["execution"]["action_executed"], False)
        self.assertNotIn("signature", record)
        self.assertNotIn("digest", record)

    def test_no_crud_executor_is_exposed_by_motor_or_guard(self):
        for name in (
            "execute_action",
            "execute_crud",
            "run_crud",
            "apply_crud",
        ):
            self.assertFalse(hasattr(MotorEmocional, name))
            self.assertFalse(hasattr(g, name))


# ---------------------------------------------------------------------------
# Frente C — integridade dos registros de decisão
# ---------------------------------------------------------------------------


class AuthorizationRecordIntegrityTests(MotorTestCase):
    def _read(self, motor, request_id="req_os113"):
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            return motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id=request_id
            )

    def test_authorized_record_has_request_id_and_execution_separation(self):
        motor = self.make_motor()
        result = self._read(motor)
        stored = motor.authorization_history[-1]
        self.assertEqual(stored["request_id"], "req_os113")
        self.assertEqual(stored["decision"], AUTHORIZATION_AUTHORIZED)
        self.assertEqual(stored["execution"]["status"], EXECUTION_CORTEX_ONLY)
        self.assertIs(stored["execution"]["action_executed"], False)
        self.assertEqual(stored["mechanisms"]["policy"]["level"], 0)
        self.assertEqual(
            stored["mechanisms"]["policy"]["provenance"],
            "ISSUED_BY_POLICY_ENGINE_IN_PROCESS",
        )
        self.assertEqual(
            stored["mechanisms"]["policy"]["provenance_status"], "VALID"
        )
        self.assertEqual(result["authorization"]["decision"], AUTHORIZATION_AUTHORIZED)

    def test_blocked_record_is_also_stored(self):
        motor = self.make_motor()
        with patch.object(g, "hard_block", return_value=_hard_deny()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id="req_block"
            )
        stored = motor.authorization_history[-1]
        self.assertIs(result["blocked"], True)
        self.assertEqual(stored["decision"], AUTHORIZATION_DENIED)
        self.assertEqual(stored["execution"]["status"], EXECUTION_NOT_EXECUTED)
        self.assertEqual(stored["mechanisms"]["hard_block"]["blocked_by"],
                         "hard_block_rust")

    def test_duplicate_request_id_is_accepted_without_detection(self):
        motor = self.make_motor()
        self._read(motor, request_id="req_duplicado")
        self._read(motor, request_id="req_duplicado")
        ids = [record["request_id"] for record in motor.authorization_history]
        self.assertEqual(ids.count("req_duplicado"), 2)
        self.assertFalse(any("duplicate" in record for record in motor.authorization_history))
        self.assertFalse(any("record_id" in record for record in motor.authorization_history))

    def test_history_entry_can_be_mutated_without_detection(self):
        motor = self.make_motor()
        self._read(motor)
        stored = motor.authorization_history[-1]
        self.assertEqual(stored["decision"], AUTHORIZATION_AUTHORIZED)
        stored["decision"] = AUTHORIZATION_DENIED
        stored["execution"]["status"] = EXECUTION_CORTEX_ONLY
        self.assertEqual(motor.authorization_history[-1]["decision"], AUTHORIZATION_DENIED)
        self.assertNotIn("hash", stored)
        self.assertNotIn("digest", stored)
        self.assertNotIn("previous_hash", stored)
        self.assertNotIn("signature", stored)

    def test_history_entry_can_be_removed(self):
        motor = self.make_motor()
        self._read(motor)
        self.assertEqual(len(motor.authorization_history), 1)
        motor.authorization_history.clear()
        self.assertEqual(len(motor.authorization_history), 0)

    def test_returned_record_mutation_does_not_rewrite_stored_copy(self):
        motor = self.make_motor()
        result = self._read(motor)
        stored_before = json.loads(json.dumps(motor.authorization_history[-1]))
        result["authorization"]["decision"] = AUTHORIZATION_DENIED
        result["authorization"]["mechanisms"]["hard_block"]["allowed"] = False
        self.assertEqual(
            motor.authorization_history[-1]["decision"],
            stored_before["decision"],
        )
        self.assertEqual(
            motor.authorization_history[-1]["mechanisms"]["hard_block"]["allowed"],
            stored_before["mechanisms"]["hard_block"]["allowed"],
        )

    def test_logging_failure_is_explicit_and_does_not_change_decision(self):
        motor = self.make_motor()
        with patch.object(
            motor,
            "_record_authorization_audit",
            return_value={
                "status": "LOGGING_FAILED",
                "entries": None,
                "error": "FalhaSimulada",
            },
        ), patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id="req_log"
            )
        self.assertEqual(result["authorization"]["audit"]["status"], "LOGGING_FAILED")
        self.assertEqual(result["authorization"]["decision"], AUTHORIZATION_AUTHORIZED)
        self.assertEqual(len(motor.authorization_history), 0)

    def test_history_is_bounded_and_old_records_are_dropped(self):
        motor = self.make_motor(history=2)
        for index in range(3):
            self._read(motor, request_id=f"req_{index}")
        ids = [record["request_id"] for record in motor.authorization_history]
        self.assertEqual(ids, ["req_1", "req_2"])

    def test_audit_record_does_not_store_raw_policy_result(self):
        motor = self.make_motor()
        self._read(motor)
        stored = motor.authorization_history[-1]
        self.assertNotIn("policy_result", stored)
        self.assertNotIn("policy_modifiers", stored)
        self.assertEqual(stored["mechanisms"]["policy"]["level"], 0)
        self.assertEqual(
            stored["mechanisms"]["policy"]["adjusted_threshold_status"],
            "NOT_APPLICABLE",
        )

    def test_wall_clock_timestamp_is_not_a_trusted_sequence(self):
        motor = self.make_motor()
        self._read(motor, request_id="req_t1")
        self._read(motor, request_id="req_t2")
        first, second = list(motor.authorization_history)
        self.assertIsInstance(first["timestamp_unix_ms"], int)
        self.assertIsInstance(second["timestamp_unix_ms"], int)
        self.assertGreaterEqual(second["timestamp_unix_ms"], first["timestamp_unix_ms"])
        self.assertNotIn("sequence", first)
        self.assertNotIn("monotonic", first)


# ---------------------------------------------------------------------------
# Frente D — identidade e integridade do binário Rust
# ---------------------------------------------------------------------------


class RustBinaryIdentityTests(unittest.TestCase):
    def _with_binary(self, path):
        return (
            patch.object(g, "_BINARY_RELEASE", path),
            patch.object(g, "_BINARY_DEBUG", os.path.join(path, "nao_existe")),
        )

    def test_missing_binary_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "guarda_costas")
            first, second = self._with_binary(missing)
            with first, second:
                result = g.hard_block("delete", 99.0, True, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(result["blocked_by"], "guard_unavailable")

    def test_non_executable_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "guarda_costas")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(path, 0o644)
            first, second = self._with_binary(path)
            with first, second:
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")

    def test_invalid_executable_output_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _make_executable(
                directory,
                """\
                #!/bin/sh
                cat >/dev/null
                exit 0
                """,
            )
            manifest = _write_manifest(
                directory, {"release": _sha256_file(path)}
            )
            first, second = self._with_binary(path)
            with first, second, patch.object(g, "_BINARY_MANIFEST", manifest):
                result = g.hard_block("delete", 99.0, True, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_PROTOCOL_ERROR")
        self.assertEqual(
            result["binary_integrity"]["status"], "BINARY_VERIFIED"
        )

    def test_substituted_executable_is_rejected_by_hash(self):
        forged = _hard_payload(
            allowed=True,
            blocked_by=None,
            effective_threshold=95.0,
            stress_level=0.0,
            reasoning="binário substituto aceito",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = _make_executable(
                directory,
                f"""\
                #!/bin/sh
                cat >/dev/null
                printf '%s\\n' '{json.dumps(forged)}'
                """,
            )
            first, second = self._with_binary(path)
            with first, second, patch.object(
                g, "_BINARY_MANIFEST", _DUMMY_MANIFEST
            ):
                result = g.hard_block("delete", 99.0, True, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(
            result["binary_integrity"]["status"], "BINARY_HASH_MISMATCH"
        )

    def test_symlink_to_substituted_executable_is_rejected(self):
        forged = _hard_payload(reasoning="symlink aceito")
        with tempfile.TemporaryDirectory() as directory:
            target = _make_executable(
                directory,
                f"""\
                #!/bin/sh
                cat >/dev/null
                printf '%s\\n' '{json.dumps(forged)}'
                """,
                name="real_binary",
            )
            link = os.path.join(directory, "guarda_costas")
            os.symlink(target, link)
            first, second = self._with_binary(link)
            with first, second, patch.object(
                g, "_BINARY_MANIFEST", _DUMMY_MANIFEST
            ):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(
            result["binary_integrity"]["status"], "BINARY_INVALID"
        )

    def test_incompatible_kernel_binary_fails_closed(self):
        contradictory = _kernel_payload(
            allowed=False,
            kernel_status="KERNEL_ALLOW",
            ring=3,
            requires_review=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = _make_executable(
                directory,
                f"""\
                #!/bin/sh
                cat >/dev/null
                printf '%s\\n' '{json.dumps(contradictory)}'
                """,
            )
            manifest = _write_manifest(
                directory, {"release": _sha256_file(path)}
            )
            first, second = self._with_binary(path)
            with first, second, patch.object(g, "_BINARY_MANIFEST", manifest):
                result = g.kernel_check("read", "u1", "leitura")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["kernel_status"], "KERNEL_ERROR")
        self.assertIs(result["requires_review"], True)
        self.assertEqual(
            result["binary_integrity"]["status"], "BINARY_VERIFIED"
        )

    def test_binary_path_requires_sha256_manifest(self):
        import inspect

        source = inspect.getsource(g._binary_path).lower()
        self.assertIn("manifest", source)
        self.assertIn("sha256", inspect.getsource(g._stage_verified_binary).lower())
        self.assertIn("symlink", inspect.getsource(g._lstat_no_symlink).lower())


# ---------------------------------------------------------------------------
# Frente E — paridade Python/Rust
# ---------------------------------------------------------------------------


@unittest.skipUnless(BINARIO, "binário Rust não compilado")
class PythonRustParityTests(unittest.TestCase):
    def test_hard_block_valid_vectors_match(self):
        vectors = [
            ("read", 100.0, True),
            ("create", 100.0, True),
            ("update", 100.0, True),
            ("delete", 0.0, False),
            ("delete", 94.9, False),
            ("delete", 95.0, False),
            ("delete", 66.5, True),
            ("delete", 66.4, True),
            ("delete", 100.0, True),
        ]
        for action, stress, reincident in vectors:
            with self.subTest(action=action, stress=stress, reincident=reincident):
                python_result = g.hard_block(action, stress, reincident, "josé")
                raw = _raw_cli(
                    {
                        "op": "hard_block",
                        "data": {
                            "action": action,
                            "stress_level": stress,
                            "is_reincident": reincident,
                            "user_id": "josé",
                        },
                    }
                )
                self.assertEqual(raw.returncode, 0, raw.stdout)
                rust_result = json.loads(raw.stdout)
                self.assertEqual(python_result["allowed"], rust_result["allowed"])
                self.assertEqual(
                    python_result["blocked_by"], rust_result["blocked_by"]
                )
                self.assertAlmostEqual(
                    python_result["effective_threshold"],
                    rust_result["effective_threshold"],
                )
                self.assertAlmostEqual(
                    python_result["stress_level"], rust_result["stress_level"]
                )

    def test_hard_block_invalid_vectors_fail_closed_in_both_layers(self):
        invalid = [
            {
                "action": "delete",
                "stress_level": 50.0,
                "is_reincident": False,
            },
            {
                "action": "delete",
                "stress_level": 50.0,
                "is_reincident": False,
                "user_id": "u1",
                "extra": 1,
            },
            {
                "action": "DELETE",
                "stress_level": 50.0,
                "is_reincident": False,
                "user_id": "u1",
            },
            {
                "action": "delete",
                "stress_level": 50.0,
                "is_reincident": "false",
                "user_id": "u1",
            },
            {
                "action": "delete",
                "stress_level": True,
                "is_reincident": False,
                "user_id": "u1",
            },
            {
                "action": "delete",
                "stress_level": 101.0,
                "is_reincident": False,
                "user_id": "u1",
            },
            {
                "action": "delete",
                "stress_level": 50.0,
                "is_reincident": False,
                "user_id": "",
            },
            {
                "action": "delete",
                "stress_level": 50.0,
                "is_reincident": False,
                "user_id": " u1",
            },
        ]
        for data in invalid:
            with self.subTest(data=data):
                with self.assertRaises(g.GuardInvalidInput):
                    g._run_rust("hard_block", data)
                raw = _raw_cli({"op": "hard_block", "data": data})
                self.assertEqual(raw.returncode, 2, raw.stdout)
                self.assertEqual(json.loads(raw.stdout)["status"], "error")

    def test_hard_block_nan_and_infinity_do_not_authorize(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                python_result = g.hard_block("delete", value, False, "u1")
                self.assertIs(python_result["allowed"], False)
                self.assertEqual(
                    python_result["guard_status"], "GUARD_INVALID_INPUT"
                )
                raw = subprocess.run(
                    [g._binary_path()],
                    input=json.dumps(
                        {
                            "op": "hard_block",
                            "data": {
                                "action": "delete",
                                "stress_level": value,
                                "is_reincident": False,
                                "user_id": "u1",
                            },
                        }
                    ),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertNotEqual(raw.returncode, 0)

    def test_unicode_and_invisible_characters(self):
        accepted = ["josé", "u😀", "u\u200bx", "u\u202ex"]
        for user_id in accepted:
            with self.subTest(user_id=repr(user_id)):
                python_result = g.hard_block("read", 0.0, False, user_id)
                raw = _raw_cli(
                    {
                        "op": "hard_block",
                        "data": {
                            "action": "read",
                            "stress_level": 0.0,
                            "is_reincident": False,
                            "user_id": user_id,
                        },
                    }
                )
                self.assertEqual(raw.returncode, 0)
                rust_result = json.loads(raw.stdout)
                self.assertIs(python_result["allowed"], rust_result["allowed"])
                self.assertIs(rust_result["allowed"], True)

        for user_id in ("u\x85x", "u\x00x"):
            with self.subTest(user_id=repr(user_id)):
                python_result = g.hard_block("read", 0.0, False, user_id)
                raw = _raw_cli(
                    {
                        "op": "hard_block",
                        "data": {
                            "action": "read",
                            "stress_level": 0.0,
                            "is_reincident": False,
                            "user_id": user_id,
                        },
                    }
                )
                self.assertEqual(raw.returncode, 2, raw.stdout)
                self.assertIs(python_result["allowed"], False)
                self.assertEqual(python_result["guard_status"], "GUARD_INVALID_INPUT")

    def test_c1_control_is_rejected_by_rust_not_by_python_prevalidation(self):
        # Divergência de camada: a validação Python do Hard Block não rejeita
        # C1 (U+0085); o Rust rejeita. O resultado final é fail-closed.
        user_id = "u\x85x"
        self.assertEqual(
            g._validate_hard_block_inputs("read", 0.0, False, user_id), 0.0
        )
        raw = _raw_cli(
            {
                "op": "hard_block",
                "data": {
                    "action": "read",
                    "stress_level": 0.0,
                    "is_reincident": False,
                    "user_id": user_id,
                },
            }
        )
        self.assertEqual(raw.returncode, 2)
        result = g.hard_block("read", 0.0, False, user_id)
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_INVALID_INPUT")

    def test_identity_layer_rejects_invisible_identifier_before_guard(self):
        for user_id in ("u\u200bx", "u\u202ex"):
            with self.subTest(user_id=repr(user_id)):
                with patch.object(
                    g, "hard_block", side_effect=AssertionError("não deve chamar")
                ), patch.object(
                    g, "kernel_check", side_effect=AssertionError("não deve chamar")
                ):
                    result = g.authorize_action("read", 0.0, False, user_id)
                self.assertIs(result["allowed"], False)
                self.assertEqual(result["blocked_by"], "guard_invalid_input")
                self.assertEqual(
                    result["authorization_status"], AUTHORIZATION_INPUT_INVALID
                )

    def test_kernel_valid_vectors_match(self):
        vectors = [
            ("read", "usuario", "moderacao", False),
            ("delete", "minoria", "perseguicao", False),
            ("delete", "minoria", "perseguicao", True),
            ("delete", "pesquisa sobre minoria", "moderacao", False),
            ("delete", "m1n0r1a", "perseguicao", False),
            ("delete", "минорити", "perseguicao", False),
            ("delete", "usuário", "moderação", False),
        ]
        for action, target, intent, majority in vectors:
            with self.subTest(action=action, target=target, intent=intent):
                python_result = g.kernel_check(
                    action, target, intent, majority
                )
                raw = _raw_cli(
                    {
                        "op": "kernel",
                        "data": {
                            "action": action,
                            "target": target,
                            "intent": intent,
                            "from_majority_vote": majority,
                        },
                    }
                )
                self.assertEqual(raw.returncode, 0, raw.stdout)
                rust_result = json.loads(raw.stdout)
                for field in (
                    "kernel_status",
                    "allowed",
                    "kernel_panic",
                    "ring",
                    "requires_review",
                    "matched_rule",
                    "operation_class",
                    "target_category",
                    "intent_category",
                ):
                    self.assertEqual(
                        python_result[field], rust_result[field], field
                    )

    def test_kernel_invalid_vectors_fail_closed_in_both_layers(self):
        invalid = [
            {
                "action": "read",
                "target": "",
                "intent": "leitura",
                "from_majority_vote": False,
            },
            {
                "action": "read",
                "target": " u1",
                "intent": "leitura",
                "from_majority_vote": False,
            },
            {
                "action": "read",
                "target": "u\u200b1",
                "intent": "leitura",
                "from_majority_vote": False,
            },
            {
                "action": "read",
                "target": "u1",
                "intent": "leitura",
                "from_majority_vote": "false",
            },
            {
                "action": "read",
                "target": "u1",
                "intent": "leitura",
                "from_majority_vote": False,
                "extra": 1,
            },
            {
                "action": "read",
                "target": 1,
                "intent": "leitura",
                "from_majority_vote": False,
            },
        ]
        for data in invalid:
            with self.subTest(data=data):
                with self.assertRaises(g.GuardInvalidInput):
                    g._run_rust("kernel", data)
                raw = _raw_cli({"op": "kernel", "data": data})
                self.assertEqual(raw.returncode, 2, raw.stdout)

    def test_kernel_c1_control_is_rejected_by_rust_but_not_prevalidation(self):
        target = "u\x85x"
        self.assertIsNone(
            g._validate_kernel_inputs("read", target, "leitura", False)
        )
        result = g.kernel_check("read", target, "leitura")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["kernel_status"], "KERNEL_INVALID_INPUT")
        raw = _raw_cli(
            {
                "op": "kernel",
                "data": {
                    "action": "read",
                    "target": target,
                    "intent": "leitura",
                    "from_majority_vote": False,
                },
            }
        )
        self.assertEqual(raw.returncode, 2)

    def test_crud_aliases_and_case_are_a_separate_contract(self):
        for action, expected in (
            ("DELETE", "delete"),
            ("d", "delete"),
            ("r", "read"),
            ("Create", "create"),
        ):
            with self.subTest(action=action):
                python_result = g.classify_crud(action)
                raw = _raw_cli({"op": "crud", "data": {"action": action}})
                self.assertEqual(raw.returncode, 0)
                rust_result = json.loads(raw.stdout)
                self.assertEqual(python_result["action"], expected)
                self.assertEqual(rust_result["action"], expected)
                self.assertEqual(
                    python_result["is_blockable"], rust_result["is_blockable"]
                )

        # O Hard Block não aceita aliases/maiúsculas, mesmo que o classificador
        # CRUD aceite. Isso é intencional: a decisão usa o tipo tipado.
        self.assertEqual(
            g.hard_block("d", 99.0, True, "u1")["guard_status"],
            "GUARD_INVALID_INPUT",
        )
        raw = _raw_cli(
            {
                "op": "hard_block",
                "data": {
                    "action": "d",
                    "stress_level": 99.0,
                    "is_reincident": True,
                    "user_id": "u1",
                },
            }
        )
        self.assertEqual(raw.returncode, 2)


# ---------------------------------------------------------------------------
# Frente F — caminhos de contorno
# ---------------------------------------------------------------------------


class BypassPathTests(unittest.TestCase):
    def test_in_process_binary_path_replacement_is_rejected_by_manifest(self):
        """Trocar `_BINARY_RELEASE` por script próprio não contorna o manifesto."""
        with tempfile.TemporaryDirectory() as directory:
            forged = _hard_payload(reasoning="mock em processo")
            path = _make_executable(
                directory,
                f"""\
                #!/bin/sh
                cat >/dev/null
                printf '%s\\n' '{json.dumps(forged)}'
                """,
            )
            with patch.object(g, "_BINARY_RELEASE", path), patch.object(
                g, "_BINARY_DEBUG", os.path.join(directory, "nao_existe")
            ), patch.object(g, "_BINARY_MANIFEST", _DUMMY_MANIFEST):
                result = g.hard_block("delete", 100.0, True, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(
            result["binary_integrity"]["status"], "BINARY_HASH_MISMATCH"
        )
        # O caminho não passa por authorize_action; não há executor CRUD.
        self.assertNotIn("authorization_status", result)
        self.assertNotIn("authorization", result)

    def test_policy_gate_can_be_called_with_enforcement_disabled(self):
        controls = g.build_policy_controls(
            _policy(level=2, read_only=True),
            "delete",
            _hard_allow(),
            enforced=False,
        )
        self.assertIsNone(controls["blocked_by_policy"])
        self.assertIs(controls["read_only"]["enforced"], False)

    def test_http_only_exposes_whitelisted_motor_arguments(self):
        captured = {}

        class FakeMotor:
            def process_interaction(self, **kwargs):
                captured.update(kwargs)
                return {"response": "ok"}

        class Request:
            headers = {}

            async def stream(self):
                yield json.dumps(
                    {
                        "user_id": "u1",
                        "action": "create",
                        "target": "alvo",
                        "intent": "moderacao",
                        "subject_id": "u2",
                        "request_id": "req_http",
                        "policy_result": _policy(level=0, read_only=False),
                        "from_majority_vote": True,
                    }
                ).encode()

        with patch.object(web_server, "motor", FakeMotor()):
            asyncio.run(web_server.api_interact(Request()))
        self.assertEqual(
            set(captured),
            {
                "user_id",
                "threat_type",
                "user_input",
                "system_prompt",
                "action",
                "target",
                "intent",
                "from_majority_vote",
                "subject_id",
                "request_id",
            },
        )
        self.assertNotIn("policy_result", captured)

    def test_break_glass_evidence_cannot_release_hard_block(self):
        motor_root = tempfile.mkdtemp(prefix="os113_bg_")
        self.addCleanup(shutil.rmtree, motor_root, ignore_errors=True)
        motor = MotorEmocional(
            cortex_api_key="fake-os113-key",
            policy_mem_path=os.path.join(motor_root, "policy"),
            context_mem_path=os.path.join(motor_root, "context"),
            dashboard_history=3,
        )
        with patch.object(
            g,
            "break_glass",
            return_value={
                "autorizado": True,
                "break_glass_status": "BREAK_GLASS_AUTHORIZED",
                "motivo_recusa": None,
            },
        ):
            result = motor.trigger_break_glass("u1")
        self.assertIs(result["authorized"], True)
        self.assertIs(result["operation_authorized"], False)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)

    def test_direct_authorize_cannot_execute_even_when_authorized(self):
        engine, policy = _issued_policy(action="delete")
        with patch.object(g, "hard_block", return_value=_hard_allow()), patch.object(
            g, "kernel_check", return_value=_kernel_allow()
        ):
            result = g.authorize_action(
                "delete",
                0.0,
                False,
                "u1",
                target="alvo",
                intent="moderacao",
                policy_result=policy,
                request_id="req_policy",
                expected_policy_engine_id=engine.engine_id,
            )
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_AUTHORIZED)
        self.assertIs(result["execution"]["action_executed"], False)
        self.assertEqual(result["execution"]["status"], EXECUTION_NOT_EXECUTED)


if __name__ == "__main__":
    unittest.main()
