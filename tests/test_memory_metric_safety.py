# -*- coding: utf-8 -*-
"""OS169 — métrica incompatível não pode apagar a memória de contexto."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "projetos" / "motor_emocional"
if str(MOTOR) not in sys.path:
    sys.path.insert(0, str(MOTOR))

from core.memory_contract import (  # noqa: E402
    MemoryInvalidRecord,
    MemoryMetricMismatchError,
)
from core.motor_sistema import MotorEmocional  # noqa: E402
from core.triangulation_memory import TriangulationMemory  # noqa: E402


class MetricMismatchSafetyTests(unittest.TestCase):
    """Prova que a inicialização nunca apaga uma coleção incompatível."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="os169_memory_")
        self.root = Path(self.tmp.name)
        self.policy_path = self.root / "policy"
        self.context_path = self.root / "context"

    def tearDown(self):
        self.tmp.cleanup()

    def _memory(self, path: Path, metric=None, **kwargs):
        return TriangulationMemory(
            embedding_dim=3,
            persist_path=str(path),
            metric=metric,
            **kwargs,
        )

    def _seed(self, path: Path, metric="l2"):
        memory = self._memory(path, metric=metric)
        memory_id = memory.store(
            "policy_engine",
            "user-1",
            "decisao",
            context={"evento": "os169", "valor": 7},
        )
        return memory, memory_id

    def _assert_record_survives(self, path: Path, memory_id: str):
        reopened = self._memory(path, metric="l2")
        records = reopened.retrieve(
            "policy_engine",
            "user-1",
            "decisao",
            include_distances=True,
        )
        self.assertTrue(records, "a coleção ficou vazia após a divergência")
        self.assertEqual(records[0]["memory"]["id"], memory_id)
        self.assertEqual(reopened.get_stats()["total"], 1)

    def test_initialization_without_collection_creates_it(self):
        memory = self._memory(self.context_path, metric="cosine")
        self.assertEqual(memory._effective_metric(), "cosine")
        self.assertEqual(memory.get_stats()["total"], 0)

    def test_compatible_metric_keeps_existing_data(self):
        memory, memory_id = self._seed(self.context_path, metric="cosine")
        del memory

        reopened = self._memory(self.context_path, metric="cosine")
        records = reopened.retrieve(
            "policy_engine",
            "user-1",
            "decisao",
            include_distances=True,
        )
        self.assertEqual(records[0]["memory"]["id"], memory_id)
        self.assertEqual(reopened.get_stats()["total"], 1)

    def test_mismatch_does_not_delete_even_with_legacy_flag(self):
        _, memory_id = self._seed(self.context_path, metric="l2")

        with self.assertRaises(MemoryMetricMismatchError) as raised:
            self._memory(
                self.context_path,
                metric="cosine",
                recreate_on_metric_mismatch=True,
            )

        self.assertEqual(raised.exception.actual_metric, "l2")
        self.assertEqual(raised.exception.requested_metric, "cosine")
        self._assert_record_survives(self.context_path, memory_id)

    def test_mismatch_fails_without_deleting_by_default(self):
        _, memory_id = self._seed(self.context_path, metric="l2")

        with self.assertRaises(MemoryMetricMismatchError):
            self._memory(self.context_path, metric="cosine")

        self._assert_record_survives(self.context_path, memory_id)

    def test_explicit_reset_is_the_only_recreation_path(self):
        memory, _ = self._seed(self.context_path, metric="l2")
        self.assertEqual(memory.get_stats()["total"], 1)

        memory.reset()

        self.assertEqual(memory.get_stats()["total"], 0)
        self.assertEqual(memory._effective_metric(), "l2")

    def test_explicit_reset_can_select_new_metric(self):
        memory, _ = self._seed(self.context_path, metric="l2")

        memory.reset(metric="cosine")

        self.assertEqual(memory.get_stats()["total"], 0)
        self.assertEqual(memory.metric, "cosine")
        self.assertEqual(memory._effective_metric(), "cosine")

    def test_invalid_explicit_metric_is_rejected(self):
        memory, memory_id = self._seed(self.context_path, metric="l2")

        with self.assertRaises(MemoryInvalidRecord):
            memory.reset(metric="")

        self._assert_record_survives(self.context_path, memory_id)

    def test_motor_does_not_delete_legacy_context_collection(self):
        _, memory_id = self._seed(self.context_path, metric="l2")

        with self.assertRaises(MemoryMetricMismatchError):
            MotorEmocional(
                policy_mem_path=str(self.policy_path),
                context_mem_path=str(self.context_path),
                dashboard_history=5,
            )

        self._assert_record_survives(self.context_path, memory_id)


if __name__ == "__main__":
    unittest.main()
