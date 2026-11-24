# -*- coding: utf-8 -*-
"""Testes OS106 — caminhos de autorização e controles efetivos.

Cobrem inventário de caminhos, chamada direta a `authorize_action`, os seis
controles do Policy Engine, precedência e consistência do status.
Nenhuma ação CRUD é executada; não existe executor no repositório.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402
from core import web_server  # noqa: E402
from core.cortex_prefrontal import CortexPreFrontal  # noqa: E402
from core.memory_contract import MEMORY_NOT_FOUND, retrieval_result  # noqa: E402
from core.motor_sistema import MotorEmocional  # noqa: E402
from core.policy_engine import PolicyEngine20  # noqa: E402


class FakeLiver:
    def __init__(self, stress):
        self.stress = stress

    def get_stress_level(self):
        return self.stress


class FakeMemory:
    def retrieve_with_status(self, **kwargs):
        return retrieval_result(MEMORY_NOT_FOUND)


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


def _motor():
    root = tempfile.mkdtemp(prefix="os106_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os106-key",
        policy_mem_path=os.path.join(root, "policy"),
        context_mem_path=os.path.join(root, "context"),
        dashboard_history=5,
    )
    motor.cortex = CapturingCortex()
    return motor, root


def _binary_available():
    try:
        g._binary_path()
    except g.GuardError:
        return False
    return True


class PolicyStatusConsistencyTests(unittest.TestCase):
    def test_status_and_evaluate_use_same_thresholds(self):
        for stress in (0.0, 60.0, 60.5, 75.5, 76.0, 76.5, 95.0, 95.5, 100.0):
            with self.subTest(stress=stress):
                engine = PolicyEngine20(FakeLiver(stress), FakeMemory())
                evaluated = engine.evaluate("u", "t")["policy_level"]
                status = engine.get_status()["policy_level"]
                self.assertEqual(evaluated, status)


@unittest.skipUnless(_binary_available(), "binário do Guarda-Costas ausente")
class AuthorizationPathTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = _motor()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _main(self, action, stress=70.0):
        self.motor.virtual_liver.add_stress(stress)
        return self.motor.process_interaction(
            "u1",
            "teste",
            "texto",
            action=action,
            target="usuario",
            intent="moderacao",
        )

    def test_direct_authorize_action_requires_policy_for_writes(self):
        # OS112: chamada direta de escrita sem policy_result falha fechado.
        direct = g.authorize_action(
            "create", 80.0, False, "u1",
            target="usuario", intent="moderacao",
        )
        self.assertIs(direct["allowed"], False)
        self.assertEqual(direct["blocked_by"], "policy_context_required")
        self.assertEqual(direct["authorization_status"], "DENIED")
        self.assertFalse(direct["authorization_complete"])

        # Com o resultado da política, read_only é aplicado no mesmo ponto.
        # OS115: o resultado precisa ser emitido pelo Policy Engine e
        # vinculado a este request_id/ação.
        engine = PolicyEngine20(FakeLiver(80.0), FakeMemory())
        policy_result = engine.evaluate(
            "u1",
            "teste",
            request_id="req_os106",
            action="create",
        )
        direct_with_policy = g.authorize_action(
            "create", 80.0, False, "u1",
            target="usuario", intent="moderacao",
            policy_result=policy_result,
            request_id="req_os106",
            expected_policy_engine_id=engine.engine_id,
        )
        self.assertIs(direct_with_policy["allowed"], False)
        self.assertEqual(direct_with_policy["blocked_by"], "policy_read_only")
        self.assertEqual(direct_with_policy["authorization_status"], "DENIED")

        main = self._main("create", 80.0)
        self.assertIs(main["blocked"], True)
        self.assertEqual(main["blocked_by"], "policy_read_only")

    def test_direct_authorize_action_still_enforces_hard_block(self):
        direct = g.authorize_action(
            "delete", 99.0, False, "u1",
            target="usuario", intent="moderacao",
        )
        self.assertIs(direct["allowed"], False)
        self.assertEqual(direct["blocked_by"], "hard_block_rust")

    def test_direct_authorize_action_still_enforces_kernel(self):
        direct = g.authorize_action(
            "delete", 0.0, False, "u1",
            target="minoria", intent="perseguicao",
        )
        self.assertIs(direct["allowed"], False)
        self.assertEqual(direct["blocked_by"], "kernel_constitucional")

    def test_direct_cortex_does_not_call_authorization(self):
        cortex = CortexPreFrontal(
            use_local=False,
            api_key="fake-os106-cortex-key",
            api_endpoint="https://example.invalid/v1/chat/completions",
            read_key_file=False,
        )
        cortex._post_chat = AsyncMock(
            return_value={
                "status": 200,
                "data": {
                    "choices": [
                        {
                            "message": {"content": "texto"},
                            "finish_reason": "stop",
                        }
                    ],
                    "model": "fake-cortex-model",
                },
                "text": "",
            }
        )
        cortex.model_name = "fake-cortex-model"
        with patch.object(
            g, "authorize_action", side_effect=AssertionError("não deve autorizar")
        ):
            text = asyncio.run(cortex.generate_response(
                emotional_state={
                    "valencia": 0.0,
                    "energia": 0.0,
                    "previsibilidade": 0.0,
                },
                stress_level=50.0,
                policy_level=0,
                policy_action="normal",
                user_context={},
                system_prompt="",
            ))
        self.assertEqual(text, "texto")

    def test_break_glass_does_not_call_authorize_action(self):
        with patch.object(
            g, "authorize_action", side_effect=AssertionError("não deve autorizar")
        ):
            result = self.motor.trigger_break_glass("u1")
        self.assertIs(result["authorized"], False)
        self.assertEqual(result["break_glass_status"], "BREAK_GLASS_INVALID_INPUT")

    def test_six_controls_are_exposed_at_level_2(self):
        result = self._main("read", 80.0)
        controls = result["policy_controls"]
        for name in (
            "read_only",
            "connection_cut",
            "adjusted_threshold",
            "max_words",
            "latency_ms",
            "judicial_alibi",
        ):
            self.assertIn(name, controls)
        self.assertEqual(controls["max_words"]["calculated"], 20)
        self.assertEqual(controls["max_words"]["status"], "CALCULATED_ONLY")
        self.assertEqual(controls["latency_ms"]["calculated"], 1000)
        self.assertEqual(controls["latency_ms"]["status"], "CALCULATED_ONLY")
        self.assertIsNone(controls["judicial_alibi"]["calculated"])
        self.assertEqual(controls["judicial_alibi"]["status"], "NOT_CALCULATED")
        self.assertEqual(controls["connection_cut"]["status"], "NOT_CALCULATED")

    def test_calculated_only_controls_at_level_3(self):
        result = self._main("read", 97.0)
        controls = result["policy_controls"]
        self.assertEqual(controls["max_words"]["calculated"], 0)
        self.assertEqual(controls["latency_ms"]["calculated"], 2000)
        self.assertTrue(controls["judicial_alibi"]["calculated"])
        self.assertFalse(controls["judicial_alibi"]["enforced"])
        self.assertEqual(controls["judicial_alibi"]["status"], "CALCULATED_ONLY")
        self.assertTrue(controls["connection_cut"]["calculated"])
        self.assertFalse(controls["connection_cut"]["enforced"])
        self.assertEqual(controls["connection_cut"]["status"], "CONTRACT_INCOMPLETE")

    def test_max_words_zero_does_not_stop_response(self):
        result = self._main("read", 97.0)
        self.assertNotIn("blocked", result)
        self.assertEqual(result["policy_controls"]["max_words"]["calculated"], 0)
        self.assertFalse(result["policy_controls"]["max_words"]["enforced"])
        self.assertEqual(self.motor.cortex.calls, 1)

    def test_main_flow_policy_block_is_auditable(self):
        result = self._main("update", 80.0)
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["blocked_by"], "policy_read_only")
        self.assertTrue(result["policy_controls"]["read_only"]["blocked"])
        self.assertNotIn("resposta", json.dumps(result["policy_controls"]))
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")


class EndpointInventoryTests(unittest.TestCase):
    def test_api_interact_calls_process_interaction(self):
        class FakeMotor:
            def __init__(self):
                self.calls = []

            def process_interaction(self, **kwargs):
                self.calls.append(kwargs)
                return {"response": "ok", "blocked": False}

        class FakeRequest:
            headers = {}

            async def json(self):
                return {
                    "user_id": "u1",
                    "threat_type": "teste",
                    "action": "read",
                    "target": "usuario",
                    "intent": "moderacao",
                }

            async def stream(self):
                yield json.dumps(await self.json()).encode("utf-8")

        motor = FakeMotor()
        with patch.object(web_server, "motor", motor):
            result = asyncio.run(web_server.api_interact(FakeRequest()))
        self.assertEqual(result["response"], "ok")
        self.assertEqual(len(motor.calls), 1)
        self.assertEqual(motor.calls[0]["action"], "read")

    def test_api_break_glass_calls_trigger_break_glass(self):
        class FakeMotor:
            def __init__(self):
                self.calls = 0

            def trigger_break_glass(self, **kwargs):
                self.calls += 1
                return {"authorized": True, "break_glass_status": "BREAK_GLASS_AUTHORIZED"}

        class FakeRequest:
            headers = {}

            async def json(self):
                return {"user_id": "u1"}

            async def stream(self):
                yield json.dumps(await self.json()).encode("utf-8")

        motor = FakeMotor()
        with patch.object(web_server, "motor", motor):
            result = asyncio.run(web_server.api_break_glass(FakeRequest()))
        self.assertEqual(result["authorized"], True)
        self.assertEqual(motor.calls, 1)


if __name__ == "__main__":
    unittest.main()
