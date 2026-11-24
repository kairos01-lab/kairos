# -*- coding: utf-8 -*-
"""Testes OS107 — fronteiras, tipos, strings, números e equivalência.

Não executam ação CRUD, modelo, API paga ou rede real. O binário Rust é usado
apenas para comparar rejeições de entrada.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402
from core import web_server  # noqa: E402
from core.memory_contract import MEMORY_NOT_FOUND, retrieval_result  # noqa: E402
from core.motor_sistema import MotorEmocional  # noqa: E402
from core.policy_engine import PolicyEngine20  # noqa: E402
from core.virtual_liver import VirtualLiver  # noqa: E402


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
    root = tempfile.mkdtemp(prefix="os107_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os107-key",
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


class ProcessInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = _motor()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _call(self, **overrides):
        kwargs = {
            "user_id": "u1",
            "threat_type": "teste",
            "user_input": "texto",
            "system_prompt": "",
            "action": "read",
            "target": "usuario",
            "intent": "moderacao",
            "from_majority_vote": False,
        }
        kwargs.update(overrides)
        return self.motor.process_interaction(**kwargs)

    def test_invalid_user_id_is_rejected_before_policy(self):
        cases = [
            None, 1, [], {}, "", "   ", " u1", "u1 ", "u\x001",
            "u\u200b1", "a" * 257,
        ]
        for value in cases:
            with self.subTest(value=value):
                result = self._call(user_id=value)
                self.assertIs(result["blocked"], True)
                self.assertEqual(result["blocked_by"], "guard_invalid_input")
                self.assertEqual(result["validation"]["field"], "user_id")
                self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(self.motor.cortex.calls, 0)
        self.assertEqual(self.motor.virtual_liver.get_stress_level(), 0.0)

    def test_invalid_threat_type_is_rejected_before_policy(self):
        cases = [
            None, 1, [], {}, "", "   ", " teste", "teste ",
            "te\x00ste", "te\u200bste", "a" * 513,
        ]
        for value in cases:
            with self.subTest(value=value):
                result = self._call(threat_type=value)
                self.assertIs(result["blocked"], True)
                self.assertEqual(result["blocked_by"], "guard_invalid_input")
                self.assertEqual(result["validation"]["field"], "threat_type")
                self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")
        self.assertEqual(self.motor.cortex.calls, 0)

    def test_invalid_structural_fields_are_rejected(self):
        cases = [
            ("user_input", []),
            ("user_input", 1),
            ("system_prompt", 1),
            ("system_prompt", []),
            ("action", None),
            ("action", 1),
            ("action", "delete "),
            ("action", "foo"),
            ("target", []),
            ("target", {}),
            ("intent", 1),
            ("from_majority_vote", "true"),
            ("from_majority_vote", 1),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                result = self._call(**{field: value})
                self.assertIs(result["blocked"], True)
                self.assertEqual(result["blocked_by"], "guard_invalid_input")
                self.assertEqual(result["validation"]["field"], field)
                self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")

    def test_invalid_input_does_not_change_stress(self):
        before = self.motor.virtual_liver.get_stress_level()
        result = self._call(threat_type=[])
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["validation"]["field"], "threat_type")
        self.assertEqual(self.motor.virtual_liver.get_stress_level(), before)

    def test_trigger_break_glass_invalid_user_is_structured(self):
        result = self.motor.trigger_break_glass([])
        self.assertIs(result["authorized"], False)
        self.assertEqual(result["break_glass_status"], "BREAK_GLASS_INVALID_INPUT")
        self.assertEqual(result["validation"]["field"], "user_id")
        self.assertIn("motivo_recusa", result["break_glass"])


class PolicyEngineDirectValidationTests(unittest.TestCase):
    def test_evaluate_rejects_unhashable_or_non_text(self):
        for value in ([], {}, None, 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PolicyEngine20(FakeLiver(80.0), FakeMemory()).evaluate(
                        "u", value
                    )

    def test_evaluate_rejects_invalid_user_id(self):
        for value in ([], {}, None, 1, "", "   "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PolicyEngine20(FakeLiver(80.0), FakeMemory()).evaluate(
                        value, "teste"
                    )


@unittest.skipUnless(_binary_available(), "binário do Guarda-Costas ausente")
class RustPythonEquivalenceTests(unittest.TestCase):
    def _rust(self, op, data):
        binary = g._binary_path()
        return subprocess.run(
            [binary],
            input=json.dumps({"op": op, "data": data}),
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_hard_block_invalid_stress_type(self):
        py = g.hard_block("delete", "50", False, "u1")
        rust = self._rust(
            "hard_block",
            {
                "action": "delete",
                "stress_level": "50",
                "is_reincident": False,
                "user_id": "u1",
            },
        )
        self.assertEqual(py["guard_status"], "GUARD_INVALID_INPUT")
        self.assertIs(py["allowed"], False)
        self.assertEqual(rust.returncode, 2)

    def test_hard_block_empty_user_id(self):
        py = g.hard_block("delete", 50.0, False, "")
        rust = self._rust(
            "hard_block",
            {
                "action": "delete",
                "stress_level": 50.0,
                "is_reincident": False,
                "user_id": "",
            },
        )
        self.assertEqual(py["guard_status"], "GUARD_INVALID_INPUT")
        self.assertIs(py["allowed"], False)
        self.assertEqual(rust.returncode, 2)

    def test_kernel_empty_target(self):
        py = g.kernel_check("delete", "", "perseguicao")
        rust = self._rust(
            "kernel",
            {
                "action": "delete",
                "target": "",
                "intent": "perseguicao",
                "from_majority_vote": False,
            },
        )
        self.assertEqual(py["kernel_status"], "KERNEL_INVALID_INPUT")
        self.assertIs(py["allowed"], False)
        self.assertEqual(rust.returncode, 2)


@unittest.skipUnless(_binary_available(), "binário do Guarda-Costas ausente")
class ValidInputSmokeTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = _motor()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_valid_unicode_identity_is_not_input_invalid(self):
        result = self.motor.process_interaction(
            "usuário_ç",
            "decisão",
            "texto",
            action="read",
            target="usuario",
            intent="moderacao",
        )
        self.assertNotEqual(result.get("blocked_by"), "guard_invalid_input")
        self.assertNotIn("validation", result)


class WebInputBoundaryTests(unittest.TestCase):
    class BadJsonRequest:
        headers = {}

        async def json(self):
            raise ValueError("json inválido")

        async def stream(self):
            yield b"{nao-json"

    class JsonRequest:
        headers = {}

        def __init__(self, payload):
            self.payload = payload

        async def json(self):
            return self.payload

        async def stream(self):
            yield json.dumps(self.payload).encode("utf-8")

    def test_interact_invalid_json_returns_400(self):
        with patch.object(web_server, "motor", types.SimpleNamespace()):
            response = asyncio.run(
                web_server.api_interact(self.BadJsonRequest())
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON", json.loads(response.body)["error"])

    def test_interact_invalid_input_returns_400(self):
        class FakeMotor:
            def process_interaction(self, **kwargs):
                return {
                    "blocked": True,
                    "blocked_by": "guard_invalid_input",
                    "validation": {"field": "threat_type"},
                }

        with patch.object(web_server, "motor", FakeMotor()):
            response = asyncio.run(
                web_server.api_interact(self.JsonRequest({"threat_type": []}))
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body)["blocked_by"], "guard_invalid_input"
        )

    def test_interact_non_object_returns_400(self):
        with patch.object(web_server, "motor", types.SimpleNamespace()):
            response = asyncio.run(web_server.api_interact(self.JsonRequest([])))
        self.assertEqual(response.status_code, 400)

    def test_break_glass_invalid_json_returns_400(self):
        with patch.object(web_server, "motor", types.SimpleNamespace()):
            response = asyncio.run(
                web_server.api_break_glass(self.BadJsonRequest())
            )
        self.assertEqual(response.status_code, 400)

    def test_break_glass_invalid_input_returns_400(self):
        class FakeMotor:
            def trigger_break_glass(self, **kwargs):
                return {
                    "authorized": False,
                    "break_glass_status": "BREAK_GLASS_INVALID_INPUT",
                    "validation": {"field": "user_id"},
                }

        with patch.object(web_server, "motor", FakeMotor()):
            response = asyncio.run(
                web_server.api_break_glass(self.JsonRequest({"user_id": []}))
            )
        self.assertEqual(response.status_code, 400)

    def test_stress_invalid_json_returns_400(self):
        with patch.object(web_server, "motor", types.SimpleNamespace()):
            response = asyncio.run(web_server.api_stress(self.BadJsonRequest()))
        self.assertEqual(response.status_code, 400)


class NumericBoundaryTests(unittest.TestCase):
    def test_virtual_liver_rejects_invalid_amounts(self):
        for amount in (
            float("nan"), float("inf"), float("-inf"), -1.0, "10", True, None
        ):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    VirtualLiver().add_stress(amount)

    def test_virtual_liver_caps_large_finite_amount(self):
        liver = VirtualLiver()
        liver.add_stress(200.0)
        self.assertLessEqual(liver.get_stress_level(), 100.0)
        self.assertGreaterEqual(liver.get_stress_level(), 95.0)

    def test_web_stress_rejects_numeric_edges(self):
        class FakeRequest:
            headers = {}

            def __init__(self, payload):
                self.payload = payload

            async def json(self):
                return self.payload

            async def stream(self):
                yield json.dumps(self.payload).encode("utf-8")

        dummy = types.SimpleNamespace(virtual_liver=VirtualLiver())
        with patch.object(web_server, "motor", dummy):
            for amount in (float("nan"), float("inf"), -1, 101, "10", True):
                with self.subTest(amount=amount):
                    response = asyncio.run(
                        web_server.api_stress(FakeRequest({"amount": amount}))
                    )
                    self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
