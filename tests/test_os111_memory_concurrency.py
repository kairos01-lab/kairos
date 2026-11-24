# -*- coding: utf-8 -*-
"""Testes OS111 — sincronização, integridade e isolamento da memória.

Usa ChromaDB local temporário, eventos e ThreadPoolExecutor. Sem modelo/API.
"""
from __future__ import annotations

import concurrent.futures
import os
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core.memory_contract import (  # noqa: E402
    MEMORY_FOUND,
    MEMORY_NOT_FOUND,
    MemoryDuplicateIdError,
    MemoryStorageError,
)
from core.triangulation_memory import TriangulationMemory  # noqa: E402


class BlockingCollection:
    """Proxy que bloqueia `add` para testar leitura durante gravação."""

    def __init__(self, real, entered, release):
        self._real = real
        self._entered = entered
        self._release = release

    def __getattr__(self, name):
        return getattr(self._real, name)

    def add(self, *args, **kwargs):
        self._entered.set()
        self._release.wait(timeout=5)
        return self._real.add(*args, **kwargs)


class MemoryAccessTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="os111_mem_")
        self.mem = TriangulationMemory(
            persist_path=os.path.join(self.root, "db")
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_concurrent_stores_are_serialized_and_unique(self):
        def store(index):
            return self.mem.store(
                "policy_engine",
                f"u{index}",
                "teste",
                context={"evento": f"e{index}"},
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(store, [1, 2]))
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(self.mem.collection.count(), 2)

    def test_retrieve_waits_for_in_flight_store(self):
        entered = threading.Event()
        release = threading.Event()
        retrieve_started = threading.Event()
        real = self.mem.collection
        self.mem.collection = BlockingCollection(real, entered, release)

        def store():
            return self.mem.store(
                "policy_engine", "u1", "teste", context={"evento": "novo"}
            )

        def retrieve():
            retrieve_started.set()
            return self.mem.retrieve("policy_engine", "u1", "teste")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            write = pool.submit(store)
            self.assertTrue(entered.wait(timeout=5))
            read = pool.submit(retrieve)
            self.assertTrue(retrieve_started.wait(timeout=5))
            self.assertFalse(read.done())
            release.set()
            memory_id = write.result(timeout=5)
            records = read.result(timeout=5)
        self.assertEqual(records[0]["memory"]["id"], memory_id)
        self.assertEqual(records[0]["memory"]["context"]["evento"], "novo")

    def test_retrieve_with_status_during_store_is_consistent(self):
        entered = threading.Event()
        release = threading.Event()
        real = self.mem.collection
        self.mem.collection = BlockingCollection(real, entered, release)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            write = pool.submit(
                self.mem.store,
                "policy_engine", "u1", "teste",
                context={"evento": "novo"},
            )
            self.assertTrue(entered.wait(timeout=5))
            read = pool.submit(
                self.mem.retrieve_with_status,
                "policy_engine", "u1", "teste",
            )
            release.set()
            write.result(timeout=5)
            result = read.result(timeout=5)
        self.assertEqual(result["status"], MEMORY_FOUND)
        self.assertEqual(result["records"][0]["memory"]["context"]["evento"], "novo")

    def test_two_identities_are_filtered(self):
        self.mem.store("policy_engine", "u1", "teste", context={"u": 1})
        self.mem.store("policy_engine", "u2", "teste", context={"u": 2})
        first = self.mem.retrieve("policy_engine", "u1", "teste")
        second = self.mem.retrieve("policy_engine", "u2", "teste")
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]["memory"]["context"]["u"], 1)
        self.assertEqual(second[0]["memory"]["context"]["u"], 2)
        self.assertEqual(first[0]["memory"]["target"], "u1")
        self.assertEqual(second[0]["memory"]["target"], "u2")

    def test_concurrent_identity_queries_do_not_mix(self):
        self.mem.store("policy_engine", "u1", "teste", context={"u": 1})
        self.mem.store("policy_engine", "u2", "teste", context={"u": 2})

        def query(user):
            return self.mem.retrieve_with_status(
                "policy_engine", user, "teste"
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(query, ["u1", "u2"]))
        self.assertEqual(first["records"][0]["memory"]["context"]["u"], 1)
        self.assertEqual(second["records"][0]["memory"]["context"]["u"], 2)
        self.assertNotEqual(
            first["records"][0]["memory"]["id"],
            second["records"][0]["memory"]["id"],
        )

    def test_direct_query_can_choose_another_identity_without_auth(self):
        self.mem.store("policy_engine", "u2", "teste", context={"segredo": "u2"})
        # Não há autenticação: uma consulta direta pode escolher u2. Este teste
        # documenta a limitação, não uma autorização.
        result = self.mem.retrieve("policy_engine", "u2", "teste")
        self.assertEqual(result[0]["memory"]["context"]["segredo"], "u2")

    def test_concurrent_duplicate_id_has_one_winner(self):
        def store():
            return self.mem.store(
                "policy_engine", "u1", "teste",
                context={"evento": "x"},
                memory_id="mem_fixed_os111",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(store), pool.submit(store)]
            results = []
            for future in futures:
                try:
                    results.append(("ok", future.result(timeout=5)))
                except MemoryDuplicateIdError as error:
                    results.append(("duplicate", str(error)))
        self.assertEqual(sum(1 for kind, _ in results if kind == "ok"), 1)
        self.assertEqual(
            sum(1 for kind, _ in results if kind == "duplicate"), 1
        )
        self.assertEqual(self.mem.collection.count(), 1)

    def test_exception_releases_memory_lock(self):
        real = self.mem.collection

        class FailingOnce:
            def __init__(self):
                self.failed = False

            def __getattr__(self, name):
                return getattr(real, name)

            def add(self, *args, **kwargs):
                if not self.failed:
                    self.failed = True
                    raise RuntimeError("falha simulada")
                return real.add(*args, **kwargs)

        self.mem.collection = FailingOnce()
        with self.assertRaises(MemoryStorageError):
            self.mem.store(
                "policy_engine", "u1", "teste", context={"evento": "x"}
            )
        # Lock deve ter sido liberado; a próxima gravação funciona.
        memory_id = self.mem.store(
            "policy_engine", "u2", "teste", context={"evento": "y"}
        )
        self.assertTrue(memory_id.startswith("mem_"))

    def test_missing_is_not_error(self):
        result = self.mem.retrieve_with_status(
            "policy_engine", "u1", "teste"
        )
        self.assertEqual(result["status"], MEMORY_NOT_FOUND)
        self.assertIsNone(result["error"])

    def test_deadlock_timeout_guard(self):
        """Duas operações concorrentes devem terminar dentro do timeout."""
        def operation(index):
            if index % 2:
                return self.mem.store(
                    "policy_engine", f"u{index}", "teste",
                    context={"i": index},
                )
            return self.mem.retrieve_with_status(
                "policy_engine", f"u{index - 1}", "teste"
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(operation, i) for i in range(4)]
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(len(results), 4)


if __name__ == "__main__":
    unittest.main()
