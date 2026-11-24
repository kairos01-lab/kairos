# -*- coding: utf-8 -*-
"""Testes OS108 — limites HTTP/JSON, WebSocket e isolamento.

Não usam modelo/API/rede externa. O WebSocket é exercitado com TestClient em
processo; o motor é substituído por um double quando o teste é de transporte.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import web_server  # noqa: E402
from core.motor_sistema import MotorEmocional  # noqa: E402


class FakeMotor:
    def __init__(self):
        self.calls = []

    def process_interaction(self, **kwargs):
        self.calls.append(kwargs)
        return {"response": kwargs.get("user_id"), "blocked": False}

    def get_current_status(self):
        return {"system": {"current_stress": 0.0}}


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
    root = tempfile.mkdtemp(prefix="os108_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os108-key",
        policy_mem_path=os.path.join(root, "policy"),
        context_mem_path=os.path.join(root, "context"),
        dashboard_history=5,
    )
    motor.cortex = CapturingCortex()
    return motor, root


class HttpLimitTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web_server.app)
        self.motor = FakeMotor()
        self.patch = patch.object(web_server, "motor", self.motor)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.client.close()

    def test_empty_body_is_400(self):
        response = self.client.post(
            "/api/interact", content=b"", headers={"content-type": "application/json"}
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_is_400(self):
        response = self.client.post(
            "/api/interact",
            content=b"{nao-json",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON", response.json()["error"])

    def test_non_object_is_400(self):
        response = self.client.post("/api/interact", json=[])
        self.assertEqual(response.status_code, 400)

    def test_body_over_limit_is_413(self):
        body = b"x" * (web_server.MAX_HTTP_BODY_BYTES + 1)
        response = self.client.post(
            "/api/interact", content=body, headers={"content-type": "application/json"}
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("corpo excede", response.json()["error"])

    def test_deep_json_is_400(self):
        nested = {}
        current = nested
        for _ in range(web_server.MAX_JSON_DEPTH + 2):
            child = {}
            current["x"] = child
            current = child
        response = self.client.post("/api/interact", json=nested)
        self.assertEqual(response.status_code, 400)
        self.assertIn("profundidade", response.json()["error"])

    def test_too_many_object_keys_is_400(self):
        payload = {f"k{i}": i for i in range(web_server.MAX_JSON_OBJECT_KEYS + 1)}
        response = self.client.post("/api/interact", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("propriedades", response.json()["error"])

    def test_too_many_list_items_is_400(self):
        payload = {"x": list(range(web_server.MAX_JSON_LIST_ITEMS + 1))}
        response = self.client.post("/api/interact", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("itens", response.json()["error"])

    def test_too_long_json_string_is_400(self):
        payload = {"x": "a" * (web_server.MAX_JSON_STRING_CHARS + 1)}
        response = self.client.post("/api/interact", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("string JSON", response.json()["error"])

    def test_nonfinite_json_number_is_400(self):
        response = self.client.post(
            "/api/stress",
            content=b'{"amount": NaN}',
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("não finito", response.json()["error"])

    def test_chunked_body_over_limit_is_413(self):
        class StreamRequest:
            headers = {}

            async def stream(self):
                for _ in range(3):
                    yield b"x" * (web_server.MAX_HTTP_BODY_BYTES // 2)

        body, response = asyncio.run(web_server._json_object(StreamRequest()))
        self.assertIsNone(body)
        self.assertEqual(response.status_code, 413)

    def test_invalid_content_length_is_400(self):
        class HeaderRequest:
            headers = {"content-length": "nao-numero"}

            async def stream(self):
                yield b"{}"

        body, response = asyncio.run(web_server._json_object(HeaderRequest()))
        self.assertIsNone(body)
        self.assertEqual(response.status_code, 400)

    def test_extra_fields_are_currently_ignored(self):
        response = self.client.post(
            "/api/interact",
            json={"user_id": "u1", "extra": "ignorado"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.motor.calls), 1)
        self.assertEqual(self.motor.calls[0]["user_id"], "u1")

    def test_concurrent_http_requests_keep_distinct_inputs(self):
        async def run():
            transport = httpx.ASGITransport(app=web_server.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                responses = await asyncio.gather(*[
                    client.post(
                        "/api/interact",
                        json={"user_id": f"u{i}", "threat_type": "teste"},
                    )
                    for i in range(5)
                ])
                return [response.json()["response"] for response in responses]

        with patch.object(web_server, "motor", self.motor):
            responses = asyncio.run(run())
        self.assertEqual(responses, [f"u{i}" for i in range(5)])


class WebSocketTests(unittest.TestCase):
    def setUp(self):
        web_server.manager.active_connections.clear()
        self.client = TestClient(web_server.app)
        self.patch = patch.object(web_server, "motor", None)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        web_server.manager.active_connections.clear()
        self.client.close()

    def test_valid_text_gets_pong(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text("hello")
            self.assertEqual(ws.receive_json(), {"type": "pong", "echo": "hello"})
        self.assertEqual(len(web_server.manager.active_connections), 0)

    def test_empty_message_is_rejected_without_closing(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text("   ")
            self.assertEqual(ws.receive_json()["type"], "error")
            ws.send_text("ok")
            self.assertEqual(ws.receive_json()["type"], "pong")

    def test_message_above_limit_closes_with_1009(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text("x" * (web_server.MAX_WS_MESSAGE_CHARS + 1))
            error = ws.receive_json()
            self.assertEqual(error["type"], "error")
            self.assertIn("acima do limite", error["error"])
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
        self.assertEqual(len(web_server.manager.active_connections), 0)

    def test_binary_message_closes_with_1003(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_bytes(b"\x00\x01")
            error = ws.receive_json()
            self.assertEqual(error["type"], "error")
            self.assertIn("binária", error["error"])
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()

    def test_rapid_messages_are_processed_sequentially(self):
        with self.client.websocket_connect("/ws") as ws:
            for index in range(10):
                ws.send_text(f"m{index}")
            echoes = [ws.receive_json()["echo"] for _ in range(10)]
        self.assertEqual(echoes, [f"m{i}" for i in range(10)])

    def test_two_connections_are_isolated(self):
        with self.client.websocket_connect("/ws") as first, \
                self.client.websocket_connect("/ws") as second:
            first.send_text("a")
            second.send_text("b")
            self.assertEqual(first.receive_json()["echo"], "a")
            self.assertEqual(second.receive_json()["echo"], "b")
        self.assertEqual(len(web_server.manager.active_connections), 0)

    def test_connection_limit_rejects_extra_client(self):
        manager = web_server.ConnectionManager(max_connections=1)

        class FakeWS:
            def __init__(self):
                self.accepted = False
                self.close_code = None

            async def accept(self):
                self.accepted = True

            async def close(self, code=1000):
                self.close_code = code

        async def run():
            first = FakeWS()
            second = FakeWS()
            self.assertTrue(await manager.connect(first))
            self.assertFalse(await manager.connect(second))
            return first, second

        first, second = asyncio.run(run())
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(second.close_code, 1013)


class MotorMessageLimitsTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = _motor()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_user_input_over_limit_is_rejected_before_policy(self):
        result = self.motor.process_interaction(
            "u1", "teste", "a" * 8_193,
            action="read", target="usuario", intent="moderacao",
        )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["validation"]["field"], "user_input")
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")

    def test_system_prompt_over_limit_is_rejected_before_policy(self):
        result = self.motor.process_interaction(
            "u1", "teste", "texto", system_prompt="a" * 32_769,
            action="read", target="usuario", intent="moderacao",
        )
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["validation"]["field"], "system_prompt")
        self.assertEqual(result["cortex_status"], "CORTEX_NOT_CALLED")


if __name__ == "__main__":
    unittest.main()
