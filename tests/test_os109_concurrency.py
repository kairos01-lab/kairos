# -*- coding: utf-8 -*-
"""Testes OS109 — concorrência, ciclo de vida e isolamento.

Usam motores falsos, eventos/barreiras e TestClient/ASGI em processo. Não
executam modelo/API/rede externa, ação CRUD ou SV-01.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402
from core import web_server  # noqa: E402
from core.motor_sistema import MotorEmocional  # noqa: E402


def _allowed_auth(**kwargs):
    return {
        "allowed": True,
        "blocked_by": None,
        "guard_status": "GUARD_OK",
        "kernel_status": "KERNEL_ALLOW",
        "kernel": {"kernel_status": "KERNEL_ALLOW", "allowed": True},
        "hard_block": {"allowed": True, "guard_status": "GUARD_OK"},
        "reasoning": "fake allow",
    }


class EchoCortex:
    def __init__(self):
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    async def generate_response_result(self, **kwargs):
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            user_id = kwargs.get("user_context", {}).get("user_id")
            return {
                "status": "CORTEX_OK",
                "response": f"ok-{user_id}",
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
        finally:
            with self._lock:
                self.active -= 1


class BlockingCortex(EchoCortex):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    async def generate_response_result(self, **kwargs):
        self.entered.set()
        await asyncio.to_thread(self.release.wait, 5)
        return await super().generate_response_result(**kwargs)


class SelectiveCortex(EchoCortex):
    async def generate_response_result(self, **kwargs):
        user_id = kwargs.get("user_context", {}).get("user_id")
        if user_id == "u1":
            raise RuntimeError("falha simulada u1")
        return await super().generate_response_result(**kwargs)


def _motor():
    root = tempfile.mkdtemp(prefix="os109_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os109-key",
        policy_mem_path=os.path.join(root, "policy"),
        context_mem_path=os.path.join(root, "context"),
        dashboard_history=5,
    )
    return motor, root


class MotorConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = _motor()
        self.auth_patch = patch.object(g, "authorize_action", side_effect=_allowed_auth)
        self.auth_patch.start()

    def tearDown(self):
        self.auth_patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _read(self, user_id):
        return self.motor.process_interaction(
            user_id,
            "teste",
            "texto",
            action="read",
            target="usuario",
            intent="moderacao",
        )

    def test_two_identities_do_not_share_context(self):
        self.motor.cortex = EchoCortex()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self._read, "u1")
            second = pool.submit(self._read, "u2")
            a, b = first.result(), second.result()
        self.assertEqual({a["response"], b["response"]}, {"ok-u1", "ok-u2"})
        self.assertEqual(self.motor.cortex.max_active, 1)

    def test_slow_process_serializes_status_and_second_process(self):
        cortex = BlockingCortex()
        self.motor.cortex = cortex
        status_started = threading.Event()

        def run_status():
            status_started.set()
            return asyncio.run(web_server.api_status())

        with patch.object(web_server, "motor", self.motor):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self._read, "u1")
                self.assertTrue(cortex.entered.wait(timeout=5))
                status = pool.submit(run_status)
                self.assertTrue(status_started.wait(timeout=5))
                # O status usa o mesmo lock do motor; não observa estado
                # intermediário enquanto a interação está bloqueada.
                self.assertFalse(status.done())
                cortex.release.set()
                first.result(timeout=5)
                status.result(timeout=5)
        self.assertEqual(cortex.calls, 1)

    def test_exception_in_one_request_does_not_break_another(self):
        self.motor.cortex = SelectiveCortex()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            bad = pool.submit(self._read, "u1")
            good = pool.submit(self._read, "u2")
            bad_result = bad.result(timeout=5)
            good_result = good.result(timeout=5)
        self.assertEqual(bad_result["cortex_status"], "CORTEX_INTERNAL_ERROR")
        self.assertIsNone(bad_result["response"])
        self.assertEqual(good_result["response"], "ok-u2")
        self.assertEqual(self.motor.cortex.max_active, 1)

    def test_authorization_happens_before_cortex(self):
        order = []

        def auth(**kwargs):
            order.append("auth")
            return _allowed_auth()

        class OrderCortex(EchoCortex):
            async def generate_response_result(self, **kwargs):
                order.append("cortex")
                return await super().generate_response_result(**kwargs)

        self.motor.cortex = OrderCortex()
        with patch.object(g, "authorize_action", side_effect=auth):
            self._read("u1")
        self.assertEqual(order, ["auth", "cortex"])

    def test_status_is_consistent_after_process(self):
        self.motor.cortex = EchoCortex()
        result = self._read("u1")
        status = self.motor.get_current_status()
        self.assertEqual(result["response"], "ok-u1")
        self.assertIn("system", status)
        self.assertIn("liver", status)


class WebSocketResourceTests(unittest.TestCase):
    class FakeWS:
        def __init__(self, send_timeout=False):
            self.messages = []
            self.closed = None
            self.send_timeout = send_timeout

        async def accept(self):
            return None

        async def close(self, code=1000):
            self.closed = code

        async def send_json(self, message):
            if self.send_timeout:
                await asyncio.Event().wait()
            self.messages.append(message)

    def test_slow_client_does_not_block_fast_client(self):
        manager = web_server.ConnectionManager(
            max_connections=2, send_timeout=0.05
        )

        async def run():
            slow = self.FakeWS(send_timeout=True)
            fast = self.FakeWS()
            self.assertTrue(await manager.connect(slow))
            self.assertTrue(await manager.connect(fast))
            await manager.broadcast({"type": "status"})
            return slow, fast

        slow, fast = asyncio.run(run())
        self.assertEqual(fast.messages, [{"type": "status"}])
        self.assertNotIn(slow, manager.active_connections)
        self.assertIn(fast, manager.active_connections)

    def test_close_all_releases_connections(self):
        manager = web_server.ConnectionManager(max_connections=2)
        first = self.FakeWS()
        second = self.FakeWS()

        async def run():
            await manager.connect(first)
            await manager.connect(second)
            await manager.close_all()

        asyncio.run(run())
        self.assertEqual(first.closed, 1001)
        self.assertEqual(second.closed, 1001)
        self.assertEqual(manager.active_connections, set())

    def test_connection_limit_is_atomic_after_accept(self):
        manager = web_server.ConnectionManager(max_connections=1)
        first = self.FakeWS()
        second = self.FakeWS()

        async def run():
            return await asyncio.gather(
                manager.connect(first), manager.connect(second)
            )

        ok_first, ok_second = asyncio.run(run())
        self.assertEqual(sorted([ok_first, ok_second]), [False, True])
        closed = [ws.closed for ws in (first, second) if ws.closed is not None]
        self.assertEqual(closed, [1013])
        self.assertEqual(len(manager.active_connections), 1)


class LifecycleTests(unittest.TestCase):
    def test_websocket_disconnect_clears_active_connections(self):
        web_server.manager.active_connections.clear()
        with patch.object(web_server, "motor", None):
            with TestClient(web_server.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.send_text("hello")
                    self.assertEqual(ws.receive_json()["type"], "pong")
                self.assertEqual(web_server.manager.active_connections, set())
        web_server.manager.active_connections.clear()

    def test_broadcast_uses_snapshot_when_set_changes(self):
        manager = web_server.ConnectionManager(max_connections=2)
        first = WebSocketResourceTests.FakeWS()
        second = WebSocketResourceTests.FakeWS()

        async def run():
            await manager.connect(first)

            async def add_second():
                await manager.connect(second)

            await asyncio.gather(manager.broadcast({"type": "status"}), add_second())

        asyncio.run(run())
        self.assertTrue(first.messages)
        self.assertIn(second, manager.active_connections)


if __name__ == "__main__":
    unittest.main()
