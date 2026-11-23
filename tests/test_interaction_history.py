# -*- coding: utf-8 -*-
"""Testes da persistência histórica F3 (OS163)."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import decimal
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "projetos" / "motor_emocional"
if str(MOTOR) not in sys.path:
    sys.path.insert(0, str(MOTOR))

from core.interaction_history import (  # noqa: E402
    AppendResult,
    EventType,
    HistoryEvent,
    InMemoryInteractionHistoryStore,
    PersistenceStatus,
    SqliteInteractionHistoryStore,
    default_history_db_path,
)


def _binary_available():
    return (MOTOR / "guarda_costas" / "target" / "release" / "guarda_costas").is_file()


def event(
    request_id="req_1",
    event_type=EventType.INTERACTION,
    payload=None,
    **kwargs,
):
    return HistoryEvent(
        event_type=event_type,
        request_id=request_id,
        payload={"detail": "ok"} if payload is None else payload,
        requester_id=kwargs.pop("requester_id", "u1"),
        subject_id=kwargs.pop("subject_id", "u1"),
        threat_type=kwargs.pop("threat_type", "decisao"),
        action=kwargs.pop("action", "read"),
        authorization_status=kwargs.pop("authorization_status", "AUTHORIZED"),
        execution_status=kwargs.pop("execution_status", "CORTEX_ONLY"),
        cortex_status=kwargs.pop("cortex_status", "CORTEX_OK"),
        system_state=kwargs.pop("system_state", "OPERACIONAL"),
        **kwargs,
    )


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryInteractionHistoryStore()

    def test_append_and_get_sequence(self):
        first = self.store.append(event(), idempotency_key="r1:e1")
        second = self.store.append(event(request_id="req_1"), idempotency_key="r1:e2")
        self.assertEqual(first.status, PersistenceStatus.RECORDED)
        self.assertEqual(second.status, PersistenceStatus.RECORDED)
        records = self.store.get("req_1")
        self.assertEqual([r.sequence for r in records], [1, 2])
        self.assertIsNone(records[0].prev_record_hash_sha256)
        self.assertEqual(
            records[1].prev_record_hash_sha256, records[0].record_hash_sha256
        )

    def test_duplicate_preserves_times(self):
        first = self.store.append(event(), idempotency_key="r1:e1")
        duplicate = self.store.append(event(), idempotency_key="r1:e1")
        self.assertEqual(duplicate.status, PersistenceStatus.DUPLICATE)
        self.assertEqual(
            duplicate.stored_record.occurred_at_unix_ms,
            first.stored_record.occurred_at_unix_ms,
        )
        self.assertEqual(
            duplicate.stored_record.recorded_at_unix_ms,
            first.stored_record.recorded_at_unix_ms,
        )

    def test_idempotency_conflict(self):
        self.store.append(event(payload={"x": 1}), idempotency_key="r1:e1")
        result = self.store.append(event(payload={"x": 2}), idempotency_key="r1:e1")
        self.assertEqual(result.status, PersistenceStatus.IDEMPOTENCY_CONFLICT)
        self.assertIsNotNone(result.existing_record_id)

    def test_payload_is_copied(self):
        payload = {"nested": {"value": 1}}
        result = self.store.append(
            event(payload=payload), idempotency_key="r1:e1"
        )
        payload["nested"]["value"] = 999
        stored = self.store.get_record(result.stored_record.record_id)
        self.assertEqual(stored.payload["nested"]["value"], 1)

    def test_invalid_payloads(self):
        cases = (
            {"x": (1, 2)},
            {"x": b"bytes"},
            {"x": {1, 2}},
            {"x": float("nan")},
            {"x": float("inf")},
            {"x": float("-inf")},
            {"x": dt.datetime.now()},
            {"x": decimal.Decimal("1.5")},
            {"x": uuid.uuid4()},
            {"record_id": "reserved"},
            {1: "non-string-key"},
            {"x": "\ud800"},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                result = self.store.append(event(payload=payload))
                self.assertEqual(result.status, PersistenceStatus.INVALID_RECORD)

    def test_payload_limits(self):
        deep = "value"
        for _ in range(20):
            deep = {"nested": deep}
        cases = (
            {"x": deep},
            {"x": list(range(257))},
            {"x": "a" * 8193},
            {f"k{i}": i for i in range(129)},
            {"x": ["a" * 8192 for _ in range(9)]},
        )
        for index, payload in enumerate(cases):
            with self.subTest(index=index):
                result = self.store.append(event(payload=payload))
                self.assertEqual(result.status, PersistenceStatus.INVALID_RECORD)

    def test_list_for_subject(self):
        self.store.append(
            event(request_id="r1", subject_id="alice"), idempotency_key="r1:e1"
        )
        self.store.append(
            event(request_id="r2", subject_id="bob"), idempotency_key="r2:e1"
        )
        records = self.store.list_for_subject("alice")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].subject_id, "alice")

    def test_parent_outcome(self):
        intent = self.store.append(
            event(event_type=EventType.INTENT, payload={"step": "intent"}),
            idempotency_key="r1:intent",
        )
        child = self.store.append(
            event(
                event_type=EventType.OUTCOME,
                payload={"step": "outcome"},
                parent_record_id=intent.stored_record.record_id,
            ),
            idempotency_key="r1:outcome",
        )
        self.assertEqual(child.status, PersistenceStatus.RECORDED)
        self.assertEqual(
            child.stored_record.parent_record_id,
            intent.stored_record.record_id,
        )
        self.assertTrue(self.store.verify_integrity().ok)


class SqliteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="os163_history_")
        self.path = Path(self.tmp.name) / "data" / "interaction_history.db"
        self.store = SqliteInteractionHistoryStore(self.path, busy_timeout_ms=1000)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_append_get_reopen(self):
        created = self.store.append(event(), idempotency_key="r1:e1")
        self.assertEqual(created.status, PersistenceStatus.RECORDED)
        record_id = created.stored_record.record_id
        self.store.close()
        self.store = SqliteInteractionHistoryStore(self.path)
        records = self.store.get("req_1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, record_id)
        self.assertTrue(self.store.verify_integrity().ok)

    def test_duplicate_and_conflict(self):
        first = self.store.append(event(), idempotency_key="r1:e1")
        duplicate = self.store.append(event(), idempotency_key="r1:e1")
        conflict = self.store.append(
            event(payload={"different": True}), idempotency_key="r1:e1"
        )
        self.assertEqual(duplicate.status, PersistenceStatus.DUPLICATE)
        self.assertEqual(
            duplicate.stored_record.occurred_at_unix_ms,
            first.stored_record.occurred_at_unix_ms,
        )
        self.assertEqual(conflict.status, PersistenceStatus.IDEMPOTENCY_CONFLICT)

    def test_chain_per_request(self):
        self.store.append(
            event(request_id="r1"), idempotency_key="r1:e1"
        )
        self.store.append(
            event(request_id="r2"), idempotency_key="r2:e1"
        )
        second = self.store.append(
            event(request_id="r1", payload={"second": True}),
            idempotency_key="r1:e2",
        )
        r1 = self.store.get("r1")
        r2 = self.store.get("r2")
        self.assertIsNone(r1[0].prev_record_hash_sha256)
        self.assertEqual(r1[1].prev_record_hash_sha256, r1[0].record_hash_sha256)
        self.assertIsNone(r2[0].prev_record_hash_sha256)
        self.assertNotEqual(r1[1].prev_record_hash_sha256, r2[0].record_hash_sha256)
        self.assertTrue(self.store.verify_integrity().ok)

    def test_order_get_and_list(self):
        one = self.store.append(event(request_id="r1"), idempotency_key="r1:e1")
        two = self.store.append(event(request_id="r1"), idempotency_key="r1:e2")
        self.assertEqual(
            [r.record_id for r in self.store.get("r1")],
            [one.stored_record.record_id, two.stored_record.record_id],
        )
        with self.store._conn:
            self.store._conn.execute(
                "UPDATE interaction_events SET occurred_at_unix_ms = 123 WHERE request_id = 'r1'"
            )
        recent = self.store.list_recent(limit=10)
        self.assertEqual(
            [r.record_id for r in recent],
            sorted(
                [one.stored_record.record_id, two.stored_record.record_id],
                reverse=True,
            ),
        )

    def test_integrity_detects_tampering(self):
        created = self.store.append(event(), idempotency_key="r1:e1")
        self.assertTrue(self.store.verify_integrity().ok)
        with self.store._conn:
            self.store._conn.execute(
                "UPDATE interaction_events SET authorization_status = 'DENIED' "
                "WHERE record_id = ?",
                (created.stored_record.record_id,),
            )
        report = self.store.verify_integrity()
        self.assertFalse(report.ok)
        self.assertEqual(report.first_bad_record_id, created.stored_record.record_id)

    def test_chain_tampering_detected(self):
        first = self.store.append(event(request_id="r1"), idempotency_key="r1:e1")
        second = self.store.append(event(request_id="r1"), idempotency_key="r1:e2")
        with self.store._conn:
            self.store._conn.execute(
                "UPDATE interaction_events SET prev_record_hash_sha256 = ? "
                "WHERE record_id = ?",
                ("0" * 64, second.stored_record.record_id),
            )
        report = self.store.verify_integrity()
        self.assertFalse(report.ok)
        self.assertEqual(report.first_bad_record_id, second.stored_record.record_id)

    def test_payload_corruption_detected(self):
        created = self.store.append(event(), idempotency_key="r1:e1")
        with self.store._conn:
            self.store._conn.execute(
                "UPDATE interaction_events SET payload_json = '{\"tampered\":true}' "
                "WHERE record_id = ?",
                (created.stored_record.record_id,),
            )
        report = self.store.verify_integrity()
        self.assertFalse(report.ok)
        self.assertEqual(report.first_bad_record_id, created.stored_record.record_id)
        duplicate = self.store.append(event(), idempotency_key="r1:e1")
        self.assertEqual(duplicate.status, PersistenceStatus.CORRUPT)

    def test_permissions_are_restrictive(self):
        self.assertEqual(
            stat.S_IMODE(self.path.stat().st_mode), 0o600
        )
        self.assertEqual(
            stat.S_IMODE(self.path.parent.stat().st_mode), 0o700
        )

    def test_parent_validation(self):
        intent = self.store.append(
            event(request_id="r1", event_type=EventType.INTENT),
            idempotency_key="r1:intent",
        )
        child = self.store.append(
            event(
                request_id="r1",
                event_type=EventType.OUTCOME,
                parent_record_id=intent.stored_record.record_id,
            ),
            idempotency_key="r1:outcome",
        )
        self.assertEqual(child.status, PersistenceStatus.RECORDED)
        missing = self.store.append(
            event(
                event_type=EventType.OUTCOME,
                parent_record_id="rec_missing",
            ),
            idempotency_key="r1:missing",
        )
        self.assertEqual(missing.status, PersistenceStatus.INVALID_RECORD)
        self.assertEqual(missing.error_code, "PARENT_NOT_FOUND")

        other = self.store.append(
            event(request_id="r2", event_type=EventType.INTENT),
            idempotency_key="r2:intent",
        )
        wrong_request = self.store.append(
            event(
                request_id="r1",
                event_type=EventType.OUTCOME,
                parent_record_id=other.stored_record.record_id,
            ),
            idempotency_key="r1:wrong-request",
        )
        self.assertEqual(wrong_request.error_code, "PARENT_REQUEST_MISMATCH")

        wrong_type = self.store.append(
            event(
                request_id="r1",
                event_type=EventType.OUTCOME,
                parent_record_id=child.stored_record.record_id,
            ),
            idempotency_key="r1:wrong-type",
        )
        self.assertEqual(wrong_type.error_code, "PARENT_TYPE_INVALID")

    def test_foreign_keys_enabled_and_reopen(self):
        self.assertEqual(
            self.store._conn.execute("PRAGMA foreign_keys").fetchone()[0], 1
        )
        self.store.close()
        self.store = SqliteInteractionHistoryStore(self.path)
        self.assertEqual(
            self.store._conn.execute("PRAGMA foreign_keys").fetchone()[0], 1
        )
        # Inserção direta sem pai deve falhar na FK.
        columns = (
            "record_id,event_schema_version,request_id,event_type,sequence,"
            "occurred_at_unix_ms,recorded_at_unix_ms,authentication_status,"
            "identity_status,payload_json,event_hash_sha256,record_hash_sha256,"
            "parent_record_id"
        )
        values = (
            "rec_fk", 1, "r_fk", "INTERACTION", 1, 1, 1,
            "IDENTITY_UNAUTHENTICATED", "IDENTITY_UNAUTHENTICATED", "{}",
            "a" * 64, "b" * 64, "rec_missing",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._conn.execute(
                f"INSERT INTO interaction_events ({columns}) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )

    def test_write_failure_is_explicit(self):
        with patch.object(
            self.store, "_commit",
            side_effect=sqlite3.OperationalError("disk full"),
        ):
            result = self.store.append(event(), idempotency_key="r1:e1")
        self.assertEqual(result.status, PersistenceStatus.WRITE_FAILED)
        self.assertEqual(self.store.get("req_1"), [])
        self.assertTrue(self.store.verify_integrity().ok)

    def test_timeout(self):
        self.store.close()
        self.store = SqliteInteractionHistoryStore(
            self.path, busy_timeout_ms=50
        )
        other = sqlite3.connect(str(self.path), isolation_level=None)
        try:
            other.execute("PRAGMA journal_mode=WAL")
            other.execute("BEGIN IMMEDIATE")
            result = self.store.append(event(), idempotency_key="r1:e1")
            self.assertEqual(result.status, PersistenceStatus.TIMEOUT)
            other.execute("ROLLBACK")
        finally:
            other.close()

    def test_concurrent_writers(self):
        def writer(index):
            store = SqliteInteractionHistoryStore(self.path, busy_timeout_ms=5000)
            try:
                result = store.append(
                    event(request_id="concurrent", payload={"i": index}),
                    idempotency_key=f"concurrent:{index}",
                )
                return result.status
            finally:
                store.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(writer, range(8)))
        self.assertEqual(statuses, [PersistenceStatus.RECORDED] * 8)
        records = self.store.get("concurrent")
        self.assertEqual(len(records), 8)
        self.assertEqual([r.sequence for r in records], list(range(1, 9)))
        self.assertTrue(self.store.verify_integrity().ok)

    def test_health_and_close(self):
        health = self.store.health()
        self.assertEqual(health.status, "OK")
        self.assertEqual(health.physical_schema_version, 1)
        self.assertTrue(health.writable)
        self.store.close()
        self.assertEqual(self.store.health().status, "UNAVAILABLE")


class DefaultPathTests(unittest.TestCase):
    def test_default_path_outside_repository(self):
        path = default_history_db_path().resolve()
        repo = ROOT.resolve()
        with self.assertRaises(ValueError):
            path.relative_to(repo)

    def test_env_override_and_repo_rejection(self):
        with tempfile.TemporaryDirectory(prefix="os163_path_") as directory:
            path = Path(directory) / "custom.db"
            with patch.dict(os.environ, {"KAIROS_HISTORY_DB": str(path)}):
                self.assertEqual(default_history_db_path().resolve(), path.resolve())
                store = SqliteInteractionHistoryStore()
                try:
                    self.assertEqual(store.db_path, path.resolve())
                finally:
                    store.close()
        with self.assertRaises(ValueError):
            SqliteInteractionHistoryStore(ROOT / "forbidden_history.db")


class SqliteExtraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="os163_extra_")
        self.path = Path(self.tmp.name) / "history.db"
        self.store = SqliteInteractionHistoryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_get_record_and_list_for_subject(self):
        created = self.store.append(
            event(request_id="r1", subject_id="alice"),
            idempotency_key="r1:e1",
        )
        self.assertEqual(
            self.store.get_record(created.stored_record.record_id).record_id,
            created.stored_record.record_id,
        )
        records = self.store.list_for_subject("alice")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].request_id, "r1")

    def test_event_hash_tampering_detected(self):
        created = self.store.append(event(), idempotency_key="r1:e1")
        with self.store._conn:
            self.store._conn.execute(
                "UPDATE interaction_events SET event_hash_sha256 = ? "
                "WHERE record_id = ?",
                ("0" * 64, created.stored_record.record_id),
            )
        report = self.store.verify_integrity()
        self.assertFalse(report.ok)
        self.assertEqual(report.first_bad_record_id, created.stored_record.record_id)

    def test_append_after_close_is_unavailable(self):
        self.store.close()
        result = self.store.append(event(), idempotency_key="r1:e1")
        self.assertEqual(result.status, PersistenceStatus.UNAVAILABLE)


@unittest.skipUnless(
    _binary_available(), "binário do Guarda-Costas ausente no worktree"
)
class MotorHistoryIntegrationTests(unittest.TestCase):
    """Integração delimitada: Motor → InteractionHistoryStore.

    Os testes unitários do store permanecem na suíte; este grupo exige o
    binário release do Guarda-Costas e é marcado como skip quando ele não
    existe. Nenhuma asserção de segurança foi removida.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="os163_motor_")
        self.root = Path(self.tmp.name)
        self.store = InMemoryInteractionHistoryStore()
        self.motor = None

    def tearDown(self):
        if self.motor is not None:
            try:
                self.motor.begin_shutdown()
            except Exception:
                pass
        self.store.close()
        self.tmp.cleanup()

    def _motor(self, cortex=None):
        import core.motor_sistema as motor_module
        from core.motor_sistema import MotorEmocional

        if cortex is None:
            class Cortex:
                async def generate_response_result(self, **kwargs):
                    return {
                        "status": "CORTEX_OK",
                        "response": "resposta controlada",
                    }
            cortex = Cortex()
        with patch.object(motor_module, "init_cortex", return_value=cortex):
            self.motor = MotorEmocional(
                policy_mem_path=str(self.root / "policy"),
                context_mem_path=str(self.root / "context"),
                dashboard_history=5,
                history_store=self.store,
            )
        return self.motor

    def test_success_records_interaction_without_raw_text(self):
        motor = self._motor()
        result = motor.process_interaction(
            "u1", "decisao", user_input="segredo-do-usuario",
            action="read", request_id="req_int_1",
        )
        self.assertEqual(result["audit_completeness"], "COMPLETE")
        self.assertEqual(result["persistence"]["status"], "RECORDED")
        records = self.store.get("req_int_1")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.event_type, EventType.INTERACTION)
        self.assertNotIn("segredo-do-usuario", str(record.payload))
        self.assertNotIn("resposta controlada", str(record.payload))
        self.assertTrue(self.store.verify_integrity().ok)

    def test_invalid_input_records_validation_event(self):
        motor = self._motor()
        result = motor.process_interaction(
            "", "decisao", user_input="x", action="read",
            request_id="req_int_bad",
        )
        self.assertEqual(result["authorization_status"], "INPUT_INVALID")
        records = self.store.get("req_int_bad")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].event_type, EventType.VALIDATION_REJECTED)
        self.assertEqual(result["audit_completeness"], "COMPLETE")

    def test_blocked_delete_records_denial(self):
        motor = self._motor()
        motor.virtual_liver.add_stress(100.0)
        result = motor.process_interaction(
            "u1", "decisao", user_input="x", action="delete",
            target="arquivo", intent="apagar", request_id="req_int_deny",
        )
        self.assertTrue(result["blocked"])
        records = self.store.get("req_int_deny")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].event_type, EventType.AUTHORIZATION_DENIED)
        self.assertEqual(result["persistence"]["status"], "RECORDED")

    def test_cortex_failure_records_cortex_failure(self):
        class Cortex:
            async def generate_response_result(self, **kwargs):
                return {"status": "CORTEX_TIMEOUT", "response": None}
        motor = self._motor(Cortex())
        result = motor.process_interaction(
            "u1", "decisao", user_input="x", action="read",
            request_id="req_int_cortex",
        )
        self.assertEqual(result["cortex_status"], "CORTEX_TIMEOUT")
        records = self.store.get("req_int_cortex")
        self.assertEqual(records[0].event_type, EventType.CORTEX_FAILURE)

    def test_persistence_failure_sets_audit_incomplete(self):
        motor = self._motor()
        failure = AppendResult(
            PersistenceStatus.WRITE_FAILED, None, None,
            "WRITE_FAILED", "disco cheio", False,
        )
        with patch.object(self.store, "append", return_value=failure):
            result = motor.process_interaction(
                "u1", "decisao", user_input="x", action="read",
                request_id="req_int_fail",
            )
        self.assertEqual(result["audit_completeness"], "INCOMPLETE")
        self.assertEqual(result["persistence"]["status"], "WRITE_FAILED")
        self.assertEqual(self.store.get("req_int_fail"), [])

    def test_break_glass_keeps_semantics_and_records_event(self):
        motor = self._motor()
        result = motor.trigger_break_glass("u1", request_id="req_int_bg")
        self.assertIs(result["operation_authorized"], False)
        records = self.store.get("req_int_bg")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].event_type, EventType.BREAK_GLASS)
        self.assertEqual(result["persistence"]["status"], "RECORDED")
        self.assertFalse(records[0].payload["break_glass"]["operation_authorized"])


if __name__ == "__main__":
    unittest.main()
