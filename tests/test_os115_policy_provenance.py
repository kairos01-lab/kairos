# -*- coding: utf-8 -*-
"""Testes OS115 — proveniência e vinculação contextual de `policy_result`.

Cobrem o contrato introduzido pela OS115:

- resultado genuíno emitido pelo Policy Engine;
- ausência, estrutura inválida e fabricação;
- vínculo com `request_id`, `user_id`, `subject_id` e `action`;
- outra instância do Policy Engine;
- reutilização, cópia, deepcopy e alteração depois da emissão;
- versão de contrato desconhecida e campos inconsistentes;
- efeito no contrato de autorização, no Córtex e no registro de auditoria.

Nenhum Hard Block/Kernel real é executado: os testes substituem esses
mecanismos por fakes locais. Não há rede, modelo, API paga, GPU, Android ou
SV-01.
"""
from __future__ import annotations

import concurrent.futures
import copy
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
from core.authorization_contract import (  # noqa: E402
    AUTHORIZATION_AUTHORIZED,
    AUTHORIZATION_DENIED,
    AUTHORIZATION_INFRASTRUCTURE_FAILURE,
    AUTHORIZATION_PARTIAL,
)
from core.motor_sistema import MotorEmocional  # noqa: E402
from core.policy_controls import validate_policy_result  # noqa: E402
from core.policy_engine import PolicyEngine20  # noqa: E402
from core.policy_provenance import (  # noqa: E402
    POLICY_PROVENANCE_CONTRACT_VERSION,
    PROVENANCE_ISSUER,
    verify_policy_result,
)

REQ = "req_os115"


# ---------------------------------------------------------------------------
# Fakes e helpers
# ---------------------------------------------------------------------------


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


def kernel_deny():
    return {
        "allowed": False,
        "kernel_status": "KERNEL_DENY",
        "blocked_by": "kernel_constitucional",
        "matched_rule": "fake_deny",
        "reasoning": "fake kernel deny",
    }


def new_engine(stress=0.0):
    return PolicyEngine20(FakeLiver(stress), FakeMemory())


def issue(
    *,
    action="read",
    stress=0.0,
    request_id=REQ,
    user_id="u1",
    subject_id=None,
    engine=None,
):
    engine = engine or new_engine(stress)
    policy = engine.evaluate(
        user_id,
        "teste",
        request_id=request_id,
        subject_id=subject_id,
        action=action,
    )
    return engine, policy


def raw_policy(*, level=0, read_only=False, action="teste"):
    """Payload sem proveniência, usado apenas como objeto fabricado."""
    return {
        "policy_level": level,
        "stress_percent": 0.0,
        "action": action,
        "is_reincident": False,
        "modifiers": {"read_only": read_only},
        "history_status": "MEMORY_NOT_FOUND",
        "history_error": None,
        "history_similarity": None,
        "reincidence_unknown": False,
    }


def authorize_direct(
    action="read",
    policy_result=None,
    *,
    request_id=REQ,
    user_id="u1",
    subject_id=None,
    expected_engine_id=None,
    hard=None,
    kernel=None,
):
    target = "alvo" if action != "read" else None
    intent = "moderacao" if action != "read" else None
    with patch.object(
        g, "hard_block", return_value=hard or hard_allow()
    ), patch.object(g, "kernel_check", return_value=kernel or kernel_allow()):
        return g.authorize_action(
            action,
            0.0,
            False,
            user_id,
            target=target,
            intent=intent,
            policy_result=policy_result,
            subject_id=subject_id,
            request_id=request_id,
            expected_policy_engine_id=expected_engine_id,
        )


def make_motor(history=5):
    root = tempfile.mkdtemp(prefix="os115_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os115-key",
        policy_mem_path=os.path.join(root, "policy"),
        context_mem_path=os.path.join(root, "context"),
        dashboard_history=history,
    )
    motor.cortex = CapturingCortex()
    return motor, root


# ---------------------------------------------------------------------------
# Contrato de proveniência
# ---------------------------------------------------------------------------


class ProvenanceContractTests(unittest.TestCase):
    def test_issued_policy_has_versioned_provenance(self):
        engine, policy = issue(action="read")
        provenance = policy["provenance"]
        self.assertEqual(
            provenance["contract_version"], POLICY_PROVENANCE_CONTRACT_VERSION
        )
        self.assertEqual(provenance["issuer"], PROVENANCE_ISSUER)
        self.assertEqual(provenance["status"], "ISSUED")
        self.assertEqual(provenance["engine_id"], engine.engine_id)
        self.assertTrue(provenance["evaluation_id"].startswith("eval_"))
        self.assertEqual(provenance["request_id"], REQ)
        self.assertEqual(provenance["user_id"], "u1")
        self.assertEqual(provenance["subject_id"], "u1")
        self.assertEqual(provenance["action"], "read")

    def test_unbound_evaluation_is_marked_and_cannot_authorize(self):
        engine = new_engine()
        policy = engine.evaluate("u1", "teste")
        self.assertEqual(policy["provenance"]["status"], "UNBOUND")
        result = authorize_direct(
            "read",
            policy,
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_unbound")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)

    def test_textual_source_is_not_provenance(self):
        fabricated = raw_policy()
        fabricated["source"] = "PolicyEngine"
        fabricated["issuer"] = "PolicyEngine20"
        fabricated["contract_version"] = 1
        result = authorize_direct("read", fabricated)
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_missing")

    def test_structural_validator_does_not_confer_provenance(self):
        fabricated = raw_policy(level=0, read_only=False)
        self.assertIsNone(validate_policy_result(fabricated))
        result = authorize_direct("read", fabricated)
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_missing")

    def test_unknown_contract_version_is_rejected(self):
        engine, policy = issue()
        policy["provenance"]["contract_version"] = 77
        result = authorize_direct(
            "read", policy, expected_engine_id=engine.engine_id
        )
        self.assertEqual(result["blocked_by"], "policy_contract_version_unknown")

    def test_malformed_provenance_is_rejected(self):
        engine, policy = issue()
        policy["provenance"] = "PolicyEngine"
        result = authorize_direct(
            "read", policy, expected_engine_id=engine.engine_id
        )
        self.assertEqual(result["blocked_by"], "policy_provenance_invalid")

    def test_unknown_evaluation_id_is_rejected(self):
        engine, policy = issue()
        policy["provenance"]["evaluation_id"] = "eval_fabricada"
        result = authorize_direct(
            "read", policy, expected_engine_id=engine.engine_id
        )
        self.assertEqual(result["blocked_by"], "policy_provenance_unknown")


# ---------------------------------------------------------------------------
# Vinculação contextual
# ---------------------------------------------------------------------------


class ContextBindingTests(unittest.TestCase):
    def test_missing_request_id_is_not_compatibility(self):
        engine, policy = issue()
        result = authorize_direct(
            "read",
            policy,
            request_id=None,
            expected_engine_id=engine.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_request_mismatch")

    def test_divergent_request_id_is_rejected(self):
        engine, policy = issue(request_id="req_original")
        result = authorize_direct(
            "read",
            policy,
            request_id="req_outra",
            expected_engine_id=engine.engine_id,
        )
        self.assertEqual(result["blocked_by"], "policy_request_mismatch")

    def test_divergent_user_id_is_rejected(self):
        engine, policy = issue(user_id="u1")
        result = authorize_direct(
            "read",
            policy,
            user_id="u2",
            expected_engine_id=engine.engine_id,
        )
        self.assertEqual(result["blocked_by"], "policy_user_mismatch")

    def test_divergent_subject_id_is_rejected(self):
        engine, policy = issue(subject_id="subject_1")
        result = authorize_direct(
            "read",
            policy,
            subject_id="subject_2",
            expected_engine_id=engine.engine_id,
        )
        self.assertEqual(result["blocked_by"], "policy_subject_mismatch")

    def test_divergent_action_is_rejected(self):
        engine, policy = issue(action="read")
        result = authorize_direct(
            "delete",
            policy,
            expected_engine_id=engine.engine_id,
        )
        self.assertEqual(result["blocked_by"], "policy_action_mismatch")

    def test_other_engine_instance_is_rejected(self):
        engine, policy = issue()
        other = new_engine()
        result = authorize_direct(
            "read",
            policy,
            expected_engine_id=other.engine_id,
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_engine_mismatch")

    def test_inconsistent_binding_fields_are_rejected(self):
        engine, policy = issue(request_id=REQ)
        policy["provenance"]["request_id"] = "req_forjado"
        result = authorize_direct(
            "read", policy, expected_engine_id=engine.engine_id
        )
        self.assertEqual(
            result["blocked_by"], "policy_provenance_inconsistent"
        )

    def test_top_level_identity_fields_do_not_create_binding(self):
        engine, policy = issue()
        copied = dict(policy)
        copied["request_id"] = REQ
        copied["user_id"] = "u1"
        copied["subject_id"] = "u1"
        copied["action"] = "read"
        result = authorize_direct(
            "read", copied, expected_engine_id=engine.engine_id
        )
        self.assertIs(result["allowed"], False)
        # A cópia é rejeitada por identidade e os campos extras alteram o
        # digest; ambos os motivos são fail-closed e nenhum cria vínculo.
        self.assertIn(
            result["blocked_by"],
            ("policy_provenance_copy", "policy_provenance_mutated"),
        )


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------


class LifecycleTests(unittest.TestCase):
    def test_genuine_policy_is_consumed_once(self):
        engine, policy = issue(action="delete")
        first = authorize_direct(
            "delete", policy, expected_engine_id=engine.engine_id
        )
        second = authorize_direct(
            "delete", policy, expected_engine_id=engine.engine_id
        )
        self.assertIs(first["allowed"], True)
        self.assertIs(second["allowed"], False)
        self.assertEqual(second["blocked_by"], "policy_provenance_reused")

    def test_copy_is_rejected(self):
        engine, policy = issue()
        result = authorize_direct(
            "read", dict(policy), expected_engine_id=engine.engine_id
        )
        self.assertEqual(result["blocked_by"], "policy_provenance_copy")

    def test_deepcopy_is_rejected(self):
        engine, policy = issue()
        result = authorize_direct(
            "read", copy.deepcopy(policy), expected_engine_id=engine.engine_id
        )
        self.assertEqual(result["blocked_by"], "policy_provenance_copy")

    def test_json_round_trip_is_rejected(self):
        engine, policy = issue()
        rebuilt = json.loads(json.dumps(policy))
        result = authorize_direct(
            "read", rebuilt, expected_engine_id=engine.engine_id
        )
        self.assertEqual(result["blocked_by"], "policy_provenance_copy")

    def test_mutation_after_issue_is_rejected(self):
        engine, policy = issue(action="delete", stress=80.0)
        self.assertIs(policy["modifiers"]["read_only"], True)
        policy["modifiers"]["read_only"] = False
        policy["policy_level"] = 0
        result = authorize_direct(
            "delete", policy, expected_engine_id=engine.engine_id
        )
        self.assertEqual(result["blocked_by"], "policy_provenance_mutated")

    def test_failed_binding_attempt_does_not_consume_evaluation(self):
        engine, policy = issue(request_id=REQ)
        rejected = authorize_direct(
            "read",
            policy,
            request_id="req_errado",
            expected_engine_id=engine.engine_id,
        )
        accepted = authorize_direct(
            "read",
            policy,
            request_id=REQ,
            expected_engine_id=engine.engine_id,
        )
        self.assertEqual(rejected["blocked_by"], "policy_request_mismatch")
        self.assertIs(accepted["allowed"], True)

    def test_copied_result_does_not_consume_original(self):
        engine, policy = issue()
        copied = dict(policy)
        rejected = authorize_direct(
            "read", copied, expected_engine_id=engine.engine_id
        )
        accepted = authorize_direct(
            "read", policy, expected_engine_id=engine.engine_id
        )
        self.assertEqual(rejected["blocked_by"], "policy_provenance_copy")
        self.assertIs(accepted["allowed"], True)

    def test_concurrent_consumption_allows_only_one(self):
        engine, policy = issue()

        def consume():
            return verify_policy_result(
                policy,
                request_id=REQ,
                user_id="u1",
                subject_id=None,
                action="read",
                expected_engine_id=engine.engine_id,
            )["status"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: consume(), range(2)))
        self.assertEqual(sorted(statuses), ["REUSED", "VALID"])


# ---------------------------------------------------------------------------
# Integração com authorize_action e com o motor
# ---------------------------------------------------------------------------


class AuthorizationIntegrationTests(unittest.TestCase):
    def test_genuine_read_is_complete_and_not_executed(self):
        engine, policy = issue(action="read")
        result = authorize_direct(
            "read", policy, expected_engine_id=engine.engine_id
        )
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_AUTHORIZED)
        self.assertIs(result["authorization_complete"], True)
        self.assertEqual(result["authority_scope"], "HARD_BLOCK_KERNEL_POLICY")
        self.assertEqual(result["execution"]["status"], "NOT_EXECUTED")
        self.assertIs(result["execution"]["action_executed"], False)
        self.assertEqual(
            result["mechanisms"]["policy"]["provenance"],
            "ISSUED_BY_POLICY_ENGINE_IN_PROCESS",
        )
        self.assertEqual(
            result["mechanisms"]["policy"]["provenance_status"], "VALID"
        )

    def test_genuine_write_is_authorized_but_not_executed(self):
        engine, policy = issue(action="create")
        result = authorize_direct(
            "create", policy, expected_engine_id=engine.engine_id
        )
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_AUTHORIZED)
        self.assertIs(result["authorization_complete"], True)
        self.assertIs(result["execution"]["action_executed"], False)

    def test_absent_policy_read_is_partial(self):
        result = authorize_direct("read")
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_PARTIAL)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["mechanisms"]["policy"]["provenance"], "ABSENT")

    def test_absent_policy_write_is_denied(self):
        result = authorize_direct("create")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_context_required")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)

    def test_hard_block_denial_does_not_consume_policy(self):
        engine, policy = issue(action="read")
        denied = authorize_direct(
            "read",
            policy,
            expected_engine_id=engine.engine_id,
            hard=hard_deny(),
        )
        allowed = authorize_direct(
            "read",
            policy,
            expected_engine_id=engine.engine_id,
        )
        self.assertEqual(denied["blocked_by"], "hard_block_rust")
        self.assertIs(allowed["allowed"], True)

    def test_kernel_denial_does_not_consume_policy(self):
        engine, policy = issue(action="read")
        denied = authorize_direct(
            "read",
            policy,
            expected_engine_id=engine.engine_id,
            kernel=kernel_deny(),
        )
        allowed = authorize_direct(
            "read",
            policy,
            expected_engine_id=engine.engine_id,
        )
        self.assertEqual(denied["blocked_by"], "kernel_constitucional")
        self.assertIs(allowed["allowed"], True)

    def test_policy_read_only_denies_with_complete_decision(self):
        engine, policy = issue(action="create", stress=80.0)
        result = authorize_direct(
            "create", policy, expected_engine_id=engine.engine_id
        )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_read_only")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], True)
        self.assertIs(result["policy_evaluated"], True)

    def test_provenance_verification_exception_never_allows(self):
        engine, policy = issue()
        with patch.object(
            g, "verify_policy_result", side_effect=RuntimeError("falha")
        ):
            result = authorize_direct(
                "read", policy, expected_engine_id=engine.engine_id
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_provenance_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )

    def test_controls_exception_after_valid_provenance_never_allows(self):
        engine, policy = issue()
        with patch.object(
            g, "build_policy_controls", side_effect=RuntimeError("falha")
        ):
            result = authorize_direct(
                "read", policy, expected_engine_id=engine.engine_id
            )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["blocked_by"], "policy_internal_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )

    def test_legacy_dict_cannot_authorize_read_or_write(self):
        fabricated = raw_policy(level=0, read_only=False)
        read = authorize_direct("read", fabricated)
        write = authorize_direct("create", fabricated)
        for result in (read, write):
            self.assertIs(result["allowed"], False)
            self.assertEqual(
                result["blocked_by"], "policy_provenance_missing"
            )
            self.assertIs(result["authorization_complete"], False)

    def test_no_permissive_legacy_fallback_parameter(self):
        with self.assertRaises(TypeError):
            g.authorize_action(
                "read",
                0.0,
                False,
                "u1",
                policy_result=raw_policy(),
                allow_legacy_policy_result=True,
            )


# ---------------------------------------------------------------------------
# Motor, Córtex e auditoria
# ---------------------------------------------------------------------------


class MotorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = make_motor()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _read(self, request_id=REQ):
        return self.motor.process_interaction(
            "u1", "teste", "texto", action="read", request_id=request_id
        )

    def test_authorized_read_reaches_cortex_with_valid_provenance(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = self._read()
        self.assertNotIn("blocked", result)
        self.assertEqual(result["authorization_status"], AUTHORIZATION_AUTHORIZED)
        self.assertIs(result["authorization_complete"], True)
        self.assertEqual(result["cortex_status"], "CORTEX_OK")
        self.assertEqual(self.motor.cortex.calls, 1)
        self.assertEqual(result["policy_provenance"]["status"], "VALID")
        self.assertEqual(
            result["policy_result"]["provenance"]["request_id"], REQ
        )
        self.assertEqual(result["request_id"], REQ)

    def test_fabricated_policy_blocks_before_cortex(self):
        with patch.object(
            self.motor.policy_engine,
            "evaluate",
            return_value=raw_policy(level=0, read_only=False),
        ), patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = self.motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id=REQ
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_provenance_missing")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(self.motor.cortex.calls, 0)

    def test_policy_from_other_engine_blocks_before_cortex(self):
        other_engine, other_policy = issue(
            action="read", request_id=REQ
        )
        with patch.object(
            self.motor.policy_engine, "evaluate", return_value=other_policy
        ), patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = self.motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id=REQ
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_engine_mismatch")
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(self.motor.cortex.calls, 0)

    def test_policy_engine_failure_is_infrastructure_failure(self):
        with patch.object(
            self.motor.policy_engine,
            "evaluate",
            side_effect=RuntimeError("falha simulada"),
        ):
            result = self.motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id=REQ
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_internal_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )
        self.assertIs(result["policy_result"], None)
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")

    def test_provenance_internal_error_is_infrastructure_failure(self):
        with patch.object(
            g, "verify_policy_result", side_effect=RuntimeError("falha")
        ), patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = self.motor.process_interaction(
                "u1", "teste", "texto", action="read", request_id=REQ
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_provenance_error")
        self.assertEqual(
            result["authorization_status"],
            AUTHORIZATION_INFRASTRUCTURE_FAILURE,
        )
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")

    def test_read_only_policy_blocks_write_before_cortex(self):
        self.motor.virtual_liver.add_stress(80.0)
        with patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            result = self.motor.process_interaction(
                "u1",
                "teste",
                "texto",
                action="create",
                target="alvo",
                intent="moderacao",
                request_id=REQ,
            )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_read_only")
        self.assertEqual(result["authorization_status"], AUTHORIZATION_DENIED)
        self.assertIs(result["authorization_complete"], True)
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(self.motor.cortex.calls, 0)
        self.assertEqual(result["policy_provenance"]["status"], "VALID")

    def test_audit_record_has_provenance_metadata_but_not_raw_policy(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), patch.object(
            g, "kernel_check", return_value=kernel_allow()
        ):
            self._read()
        stored = self.motor.authorization_history[-1]
        mechanism = stored["mechanisms"]["policy"]
        self.assertEqual(
            mechanism["provenance"], "ISSUED_BY_POLICY_ENGINE_IN_PROCESS"
        )
        self.assertEqual(mechanism["provenance_status"], "VALID")
        self.assertIsInstance(mechanism["evaluation_id"], str)
        self.assertEqual(mechanism["contract_version"], 1)
        self.assertNotIn("policy_result", stored)
        self.assertNotIn("policy_modifiers", stored)


if __name__ == "__main__":
    unittest.main()
