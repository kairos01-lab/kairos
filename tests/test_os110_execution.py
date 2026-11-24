# -*- coding: utf-8 -*-
"""Testes OS110 — executor serial, cancelamento, shutdown e acessos.

Motores falsos, eventos e ASGI em processo; sem modelo, API paga ou rede.
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

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402
from core import web_server  # noqa: E402
from core.cortex_prefrontal import CortexPreFrontal  # noqa: E402
from core.motor_sistema import MotorEmocional, MotorShuttingDown  # noqa: E402


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
        self.release = threading.Event()

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


class SlowCortex(EchoCortex):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()

    async def generate_response_result(self, **kwargs):
        self.entered.set()
        await asyncio.to_thread(self.release.wait, 5)
        return await super().generate_response_result(**kwargs)


class SelectiveCortex(EchoCortex):
    async def generate_response_result(self, **kwargs):
        if kwargs.get("user_context", {}).get("user_id") == "u1":
            raise RuntimeError("falha simulada u1")
        return await super().generate_response_result(**kwargs)


def _motor():
    root = tempfile.mkdtemp(prefix="os110_motor_")
    motor = MotorEmocional(
        cortex_api_key="fake-os110-key",
        policy_mem_path=os.path.join(root, "policy"),
        context_mem_path=os.path.join(root, "context"),
        dashboard_history=5,
    )
    return motor, root


def _read_kwargs(user_id="u1"):
    return {
        "user_id": user_id,
        "threat_type": "teste",
        "user_input": "texto",
        "action": "read",
        "target": "usuario",
        "intent": "moderacao",
    }


class AsyncExecutorTests(unittest.TestCase):
    def setUp(self):
        self.motor, self.root = _motor()
        self.auth = patch.object(g, "authorize_action", side_effect=_allowed_auth)
        self.auth.start()

    def tearDown(self):
        self.auth.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_health_responds_while_slow_interaction_and_status_waits(self):
        cortex = SlowCortex()
        self.motor.cortex = cortex

        async def scenario():
            with patch.object(web_server, "motor", self.motor):
                interaction = asyncio.create_task(
                    self.motor.process_interaction_async(**_read_kwargs("u1"))
                )
                await asyncio.to_thread(cortex.entered.wait, 5)
                transport = httpx.ASGITransport(app=web_server.app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    health = await client.get("/api/health")
                    self.assertEqual(health.status_code, 200)
                    self.assertEqual(health.json()["status"], "ok")
                    status_task = asyncio.create_task(
                        client.get("/api/status")
                    )
                    for _ in range(3):
                        await asyncio.sleep(0)
                    self.assertFalse(status_task.done())
                    cortex.release.set()
                    await interaction
                    status = await status_task
                    self.assertEqual(status.status_code, 200)
                    self.assertIn("system", status.json())
            await self.motor.shutdown_async(timeout=5)

        asyncio.run(scenario())

    def test_two_async_interactions_are_serialized(self):
        self.motor.cortex = EchoCortex()

        async def scenario():
            results = await asyncio.gather(
                self.motor.process_interaction_async(**_read_kwargs("u1")),
                self.motor.process_interaction_async(**_read_kwargs("u2")),
            )
            await self.motor.shutdown_async(timeout=5)
            return results

        results = asyncio.run(scenario())
        self.assertEqual(
            {results[0]["response"], results[1]["response"]},
            {"ok-u1", "ok-u2"},
        )
        self.assertEqual(self.motor.cortex.max_active, 1)

    def test_executor_exception_does_not_break_queue(self):
        self.motor.cortex = SelectiveCortex()

        async def scenario():
            bad = asyncio.create_task(
                self.motor.process_interaction_async(**_read_kwargs("u1"))
            )
            good = asyncio.create_task(
                self.motor.process_interaction_async(**_read_kwargs("u2"))
            )
            bad_result = await bad
            good_result = await good
            await self.motor.shutdown_async(timeout=5)
            return bad_result, good_result

        bad, good = asyncio.run(scenario())
        self.assertEqual(bad["cortex_status"], "CORTEX_INTERNAL_ERROR")
        self.assertEqual(good["response"], "ok-u2")

    def test_cancellation_does_not_release_serialization(self):
        cortex = SlowCortex()
        self.motor.cortex = cortex

        async def scenario():
            first = asyncio.create_task(
                self.motor.process_interaction_async(**_read_kwargs("u1"))
            )
            await asyncio.to_thread(cortex.entered.wait, 5)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first

            second = asyncio.create_task(
                self.motor.process_interaction_async(**_read_kwargs("u2"))
            )
            for _ in range(3):
                await asyncio.sleep(0)
            self.assertFalse(second.done())
            cortex.release.set()
            result = await second
            await self.motor.shutdown_async(timeout=5)
            return result

        result = asyncio.run(scenario())
        self.assertEqual(result["response"], "ok-u2")

    def test_shutdown_complete_after_idle(self):
        self.motor.cortex = EchoCortex()

        async def scenario():
            await self.motor.process_interaction_async(**_read_kwargs("u1"))
            return await self.motor.shutdown_async(timeout=5)

        result = asyncio.run(scenario())
        self.assertTrue(result["shutdown_complete"])

    def test_shutdown_timeout_reports_incomplete(self):
        cortex = SlowCortex()
        self.motor.cortex = cortex

        async def scenario():
            interaction = asyncio.create_task(
                self.motor.process_interaction_async(**_read_kwargs("u1"))
            )
            await asyncio.to_thread(cortex.entered.wait, 5)
            info = await self.motor.shutdown_async(timeout=0.01)
            cortex.release.set()
            await interaction
            return info

        info = asyncio.run(scenario())
        self.assertFalse(info["shutdown_complete"])
        self.assertTrue(info["timed_out"])

    def test_new_async_operation_is_rejected_after_begin_shutdown(self):
        self.motor.cortex = EchoCortex()
        self.motor.begin_shutdown()

        async def scenario():
            with self.assertRaises(MotorShuttingDown):
                await self.motor.process_interaction_async(**_read_kwargs("u1"))

        asyncio.run(scenario())

    def test_dispatch_failure_is_explicit(self):
        self.motor.cortex = EchoCortex()
        self.motor._executor.shutdown(wait=True)

        async def scenario():
            with self.assertRaises(RuntimeError):
                await self.motor.process_interaction_async(**_read_kwargs("u1"))

        asyncio.run(scenario())

    def test_cortex_shutdown_failure_is_reported(self):
        class BadShutdownCortex(EchoCortex):
            def shutdown(self):
                raise RuntimeError("falha de shutdown")

        self.motor.cortex = BadShutdownCortex()

        async def scenario():
            return await self.motor.shutdown_async(timeout=1.0)

        result = asyncio.run(scenario())
        self.assertFalse(result["shutdown_complete"])
        self.assertIn("RuntimeError", result["cortex_shutdown"]["error"])

    def test_ws_send_timeout_is_explicit(self):
        class SlowWS:
            async def send_json(self, payload):
                await asyncio.Event().wait()

        with patch.object(web_server, "WS_SEND_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(asyncio.TimeoutError):
                asyncio.run(web_server._ws_send(SlowWS(), {"type": "ping"}))

    def test_broadcast_failure_does_not_remove_fast_client(self):
        manager = web_server.ConnectionManager(
            max_connections=2, send_timeout=0.05
        )

        class FailingWS:
            def __init__(self):
                self.closed = None

            async def accept(self):
                return None

            async def close(self, code=1000):
                self.closed = code

            async def send_json(self, payload):
                raise RuntimeError("envio falhou")

        class FastWS(FailingWS):
            async def send_json(self, payload):
                self.closed = "sent"

        async def scenario():
            bad = FailingWS()
            fast = FastWS()
            await manager.connect(bad)
            await manager.connect(fast)
            await manager.broadcast({"type": "status"})
            return bad, fast

        bad, fast = asyncio.run(scenario())
        self.assertNotIn(bad, manager.active_connections)
        self.assertIn(fast, manager.active_connections)
        self.assertEqual(fast.closed, "sent")


class CortexAccessTests(unittest.TestCase):
    def test_direct_cortex_metadata_waits_for_shared_lock(self):
        lock = threading.RLock()
        cortex = CortexPreFrontal(
            use_local=False,
            api_key="fake-os110-cortex",
            api_endpoint="https://example.invalid/v1/chat/completions",
            read_key_file=False,
            state_lock=lock,
        )
        started = threading.Event()

        def read_info():
            started.set()
            return cortex.get_system_info()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with lock:
                future = pool.submit(read_info)
                self.assertTrue(started.wait(timeout=5))
                self.assertFalse(future.done())
            # O lock foi liberado; o worker deve concluir.
            info = future.result(timeout=5)
        self.assertEqual(info["requested_mode"], "api")


if __name__ == "__main__":
    unittest.main()
