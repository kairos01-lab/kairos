# -*- coding: utf-8 -*-
"""Persistência histórica durável do Kairós (F3).

Implementação mínima autorizada pela OS163: SQLite da biblioteca padrão,
sem dependências externas, sem memória cognitiva e sem ChromaDB.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol, Sequence

SCHEMA_VERSION = 1
SUPPORTED_EVENT_SCHEMA_VERSIONS = (1,)
MAX_PAYLOAD_DEPTH = 16
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_PAYLOAD_KEYS = 128
MAX_PAYLOAD_ITEMS = 256
MAX_PAYLOAD_STRING = 8192
MAX_RECORD_ATTEMPTS = 3
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

_RESERVED_PAYLOAD_KEYS = frozenset({
    "record_id", "event_schema_version", "request_id", "correlation_id",
    "parent_record_id", "idempotency_key", "event_type", "sequence",
    "occurred_at_unix_ms", "recorded_at_unix_ms", "requester_id",
    "subject_id", "authentication_status", "identity_status",
    "authority_basis", "threat_type", "action", "target_hmac",
    "target_chars", "intent_hmac", "intent_chars", "authorization_status",
    "execution_status", "cortex_status", "system_state", "payload",
    "payload_json", "event_hash_sha256", "record_hash_sha256",
    "prev_record_hash_sha256", "record_hmac", "hmac_key_version",
})


class EventType(str, Enum):
    INTERACTION = "INTERACTION"
    INTENT = "INTENT"
    OUTCOME = "OUTCOME"
    CORTEX_FAILURE = "CORTEX_FAILURE"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    BREAK_GLASS = "BREAK_GLASS"
    AUDIT_GAP = "AUDIT_GAP"


class PersistenceStatus(str, Enum):
    RECORDED = "RECORDED"
    DUPLICATE = "DUPLICATE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    SEQUENCE_CONFLICT = "SEQUENCE_CONFLICT"
    INVALID_RECORD = "INVALID_RECORD"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    WRITE_FAILED = "WRITE_FAILED"
    CORRUPT = "CORRUPT"


class AuditCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_REQUIRED = "NOT_REQUIRED"


class HistoryStoreError(Exception):
    """Erro de uso/estado do store."""


class InvalidHistoryEvent(HistoryStoreError):
    """Evento inválido; nada foi gravado."""


class HistoryStoreCorruption(HistoryStoreError):
    """Registro persistido ilegível/corrompido."""


@dataclass(frozen=True)
class HistoryEvent:
    event_type: EventType
    request_id: str
    payload: Mapping[str, object]
    correlation_id: str | None = None
    parent_record_id: str | None = None
    event_schema_version: int = 1
    requester_id: str | None = None
    subject_id: str | None = None
    authentication_status: str = "IDENTITY_UNAUTHENTICATED"
    identity_status: str = "IDENTITY_UNAUTHENTICATED"
    authority_basis: str | None = None
    threat_type: str | None = None
    action: str | None = None
    target_hmac: str | None = None
    target_chars: int | None = None
    intent_hmac: str | None = None
    intent_chars: int | None = None
    authorization_status: str | None = None
    execution_status: str | None = None
    cortex_status: str | None = None
    system_state: str | None = None


@dataclass(frozen=True)
class StoredHistoryRecord:
    record_id: str
    event_schema_version: int
    request_id: str
    correlation_id: str | None
    parent_record_id: str | None
    idempotency_key: str | None
    event_type: EventType
    sequence: int
    occurred_at_unix_ms: int
    recorded_at_unix_ms: int
    requester_id: str | None
    subject_id: str | None
    authentication_status: str
    identity_status: str
    authority_basis: str | None
    threat_type: str | None
    action: str | None
    target_hmac: str | None
    target_chars: int | None
    intent_hmac: str | None
    intent_chars: int | None
    authorization_status: str | None
    execution_status: str | None
    cortex_status: str | None
    system_state: str | None
    payload: Mapping[str, object]
    event_hash_sha256: str
    record_hash_sha256: str
    prev_record_hash_sha256: str | None
    record_hmac: str | None
    hmac_key_version: int | None


@dataclass(frozen=True)
class AppendResult:
    status: PersistenceStatus
    stored_record: StoredHistoryRecord | None
    existing_record_id: str | None
    error_code: str | None
    error_message: str | None
    retryable: bool


@dataclass(frozen=True)
class StoreHealth:
    status: str
    physical_schema_version: int
    supported_event_schema_versions: tuple[int, ...]
    writable: bool
    latency_ms: float | None
    last_error_code: str | None


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    checked_records: int
    first_bad_record_id: str | None
    anchored_at_unix_ms: int | None
    detail: str | None


class InteractionHistoryStore(Protocol):
    def append(
        self,
        event: HistoryEvent,
        *,
        idempotency_key: str | None = None,
    ) -> AppendResult: ...

    def get(self, request_id: str) -> Sequence[StoredHistoryRecord]: ...
    def get_record(self, record_id: str) -> StoredHistoryRecord | None: ...

    def list_recent(
        self,
        *,
        limit: int = 50,
        before_unix_ms: int | None = None,
        before_record_id: str | None = None,
    ) -> Sequence[StoredHistoryRecord]: ...

    def list_for_subject(
        self,
        subject_id: str,
        *,
        from_unix_ms: int | None = None,
        to_unix_ms: int | None = None,
        limit: int = 100,
    ) -> Sequence[StoredHistoryRecord]: ...

    def health(self) -> StoreHealth: ...
    def verify_integrity(self, *, full: bool = False) -> IntegrityReport: ...
    def close(self) -> None: ...


# ───────────────────────── validação/canonicalização ─────────────────────────


def _text(value, field: str, *, max_chars=512, allow_none=False, allow_empty=False):
    if value is None:
        if allow_none:
            return None
        raise InvalidHistoryEvent(f"{field} ausente")
    if not isinstance(value, str):
        raise InvalidHistoryEvent(f"{field} deve ser string")
    if not allow_empty and not value.strip():
        raise InvalidHistoryEvent(f"{field} vazio")
    if len(value) > max_chars:
        raise InvalidHistoryEvent(f"{field} excede {max_chars} caracteres")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise InvalidHistoryEvent(f"{field} contém caractere de controle")
    return value


def _hmac_field(value, field: str):
    value = _text(value, field, max_chars=64, allow_none=True)
    if value is not None and not HEX64_RE.fullmatch(value):
        raise InvalidHistoryEvent(f"{field} deve ser hex SHA-256/HMAC de 64 caracteres")
    return value


def _non_negative_int(value, field: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidHistoryEvent(f"{field} deve ser inteiro não negativo")
    return value


def _copy_json(value, depth: int = 0):
    if depth > MAX_PAYLOAD_DEPTH:
        raise InvalidHistoryEvent("payload excede profundidade máxima")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        if len(value) > MAX_PAYLOAD_STRING:
            raise InvalidHistoryEvent("string do payload longa demais")
        try:
            value.encode("utf-8", "strict")
        except UnicodeEncodeError as error:
            raise InvalidHistoryEvent("string do payload contém surrogate inválido") from error
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidHistoryEvent("payload contém float não finito")
        return value
    if isinstance(value, list):
        if len(value) > MAX_PAYLOAD_ITEMS:
            raise InvalidHistoryEvent("lista do payload longa demais")
        return [_copy_json(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > MAX_PAYLOAD_KEYS:
            raise InvalidHistoryEvent("objeto do payload tem chaves demais")
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidHistoryEvent("chave do payload não é string")
            if not key or len(key) > 128:
                raise InvalidHistoryEvent("chave do payload inválida")
            try:
                key.encode("utf-8", "strict")
            except UnicodeEncodeError as error:
                raise InvalidHistoryEvent("chave do payload com surrogate inválido") from error
            out[key] = _copy_json(item, depth + 1)
        return out
    raise InvalidHistoryEvent(
        f"tipo não suportado no payload: {type(value).__name__}"
    )


def _copy_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise InvalidHistoryEvent("payload deve ser objeto/dict")
    data = dict(payload)
    for key in data:
        if key in _RESERVED_PAYLOAD_KEYS:
            raise InvalidHistoryEvent(f"chave reservada no payload: {key}")
    copied = _copy_json(data, 0)
    encoded = _canonical_json(copied).encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise InvalidHistoryEvent("payload excede o tamanho máximo")
    return copied


def _canonical_json(value) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise InvalidHistoryEvent(f"payload não canonicalizável: {error}") from error


def _hash(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _event_identity(prepared: dict) -> dict:
    return {
        "event_schema_version": prepared["event_schema_version"],
        "request_id": prepared["request_id"],
        "correlation_id": prepared["correlation_id"],
        "parent_record_id": prepared["parent_record_id"],
        "event_type": prepared["event_type"].value,
        "requester_id": prepared["requester_id"],
        "subject_id": prepared["subject_id"],
        "authentication_status": prepared["authentication_status"],
        "identity_status": prepared["identity_status"],
        "authority_basis": prepared["authority_basis"],
        "threat_type": prepared["threat_type"],
        "action": prepared["action"],
        "target_hmac": prepared["target_hmac"],
        "target_chars": prepared["target_chars"],
        "intent_hmac": prepared["intent_hmac"],
        "intent_chars": prepared["intent_chars"],
        "authorization_status": prepared["authorization_status"],
        "execution_status": prepared["execution_status"],
        "cortex_status": prepared["cortex_status"],
        "system_state": prepared["system_state"],
        "payload": prepared["payload"],
    }


def _record_identity(record: StoredHistoryRecord) -> dict:
    return {
        "record_id": record.record_id,
        "event_schema_version": record.event_schema_version,
        "request_id": record.request_id,
        "correlation_id": record.correlation_id,
        "parent_record_id": record.parent_record_id,
        "idempotency_key": record.idempotency_key,
        "event_type": record.event_type.value,
        "sequence": record.sequence,
        "occurred_at_unix_ms": record.occurred_at_unix_ms,
        "recorded_at_unix_ms": record.recorded_at_unix_ms,
        "requester_id": record.requester_id,
        "subject_id": record.subject_id,
        "authentication_status": record.authentication_status,
        "identity_status": record.identity_status,
        "authority_basis": record.authority_basis,
        "threat_type": record.threat_type,
        "action": record.action,
        "target_hmac": record.target_hmac,
        "target_chars": record.target_chars,
        "intent_hmac": record.intent_hmac,
        "intent_chars": record.intent_chars,
        "authorization_status": record.authorization_status,
        "execution_status": record.execution_status,
        "cortex_status": record.cortex_status,
        "system_state": record.system_state,
        "payload": record.payload,
        "event_hash_sha256": record.event_hash_sha256,
        "prev_record_hash_sha256": record.prev_record_hash_sha256,
        "hmac_key_version": record.hmac_key_version,
    }


def _prepare_event(event: HistoryEvent, idempotency_key: str | None) -> dict:
    if not isinstance(event, HistoryEvent):
        raise InvalidHistoryEvent("evento deve ser HistoryEvent")
    try:
        event_type = (
            event.event_type
            if isinstance(event.event_type, EventType)
            else EventType(event.event_type)
        )
    except Exception as error:
        raise InvalidHistoryEvent("event_type inválido") from error
    if isinstance(event.event_schema_version, bool) or not isinstance(
        event.event_schema_version, int
    ):
        raise InvalidHistoryEvent("event_schema_version deve ser inteiro")
    if event.event_schema_version not in SUPPORTED_EVENT_SCHEMA_VERSIONS:
        raise InvalidHistoryEvent("event_schema_version não suportado")
    request_id = _text(event.request_id, "request_id", max_chars=200)
    correlation_id = _text(
        event.correlation_id, "correlation_id", max_chars=256, allow_none=True
    )
    parent_record_id = _text(
        event.parent_record_id, "parent_record_id", max_chars=200, allow_none=True
    )
    if idempotency_key is not None:
        idempotency_key = _text(
            idempotency_key, "idempotency_key", max_chars=200
        )
    payload = _copy_payload(event.payload)
    requester_id = _text(
        event.requester_id, "requester_id", max_chars=256, allow_none=True
    )
    subject_id = _text(
        event.subject_id, "subject_id", max_chars=256, allow_none=True
    )
    authentication_status = _text(
        event.authentication_status, "authentication_status", max_chars=64
    )
    identity_status = _text(
        event.identity_status, "identity_status", max_chars=64
    )
    authority_basis = _text(
        event.authority_basis, "authority_basis", max_chars=64, allow_none=True
    )
    threat_type = _text(
        event.threat_type, "threat_type", max_chars=512, allow_none=True
    )
    action = _text(event.action, "action", max_chars=32, allow_none=True)
    target_hmac = _hmac_field(event.target_hmac, "target_hmac")
    intent_hmac = _hmac_field(event.intent_hmac, "intent_hmac")
    target_chars = _non_negative_int(event.target_chars, "target_chars")
    intent_chars = _non_negative_int(event.intent_chars, "intent_chars")
    authorization_status = _text(
        event.authorization_status,
        "authorization_status",
        max_chars=64,
        allow_none=True,
    )
    execution_status = _text(
        event.execution_status,
        "execution_status",
        max_chars=64,
        allow_none=True,
    )
    cortex_status = _text(
        event.cortex_status, "cortex_status", max_chars=64, allow_none=True
    )
    system_state = _text(
        event.system_state, "system_state", max_chars=64, allow_none=True
    )
    prepared = {
        "event_type": event_type,
        "request_id": request_id,
        "correlation_id": correlation_id,
        "parent_record_id": parent_record_id,
        "idempotency_key": idempotency_key,
        "event_schema_version": event.event_schema_version,
        "requester_id": requester_id,
        "subject_id": subject_id,
        "authentication_status": authentication_status,
        "identity_status": identity_status,
        "authority_basis": authority_basis,
        "threat_type": threat_type,
        "action": action,
        "target_hmac": target_hmac,
        "target_chars": target_chars,
        "intent_hmac": intent_hmac,
        "intent_chars": intent_chars,
        "authorization_status": authorization_status,
        "execution_status": execution_status,
        "cortex_status": cortex_status,
        "system_state": system_state,
        "payload": payload,
    }
    prepared["event_hash_sha256"] = _hash(_event_identity(prepared))
    return prepared


def _build_record(
    prepared: dict,
    *,
    record_id: str,
    sequence: int,
    occurred_at_unix_ms: int,
    recorded_at_unix_ms: int,
    prev_record_hash_sha256: str | None,
) -> StoredHistoryRecord:
    record = StoredHistoryRecord(
        record_id=record_id,
        event_schema_version=prepared["event_schema_version"],
        request_id=prepared["request_id"],
        correlation_id=prepared["correlation_id"],
        parent_record_id=prepared["parent_record_id"],
        idempotency_key=prepared["idempotency_key"],
        event_type=prepared["event_type"],
        sequence=sequence,
        occurred_at_unix_ms=occurred_at_unix_ms,
        recorded_at_unix_ms=recorded_at_unix_ms,
        requester_id=prepared["requester_id"],
        subject_id=prepared["subject_id"],
        authentication_status=prepared["authentication_status"],
        identity_status=prepared["identity_status"],
        authority_basis=prepared["authority_basis"],
        threat_type=prepared["threat_type"],
        action=prepared["action"],
        target_hmac=prepared["target_hmac"],
        target_chars=prepared["target_chars"],
        intent_hmac=prepared["intent_hmac"],
        intent_chars=prepared["intent_chars"],
        authorization_status=prepared["authorization_status"],
        execution_status=prepared["execution_status"],
        cortex_status=prepared["cortex_status"],
        system_state=prepared["system_state"],
        payload=prepared["payload"],
        event_hash_sha256=prepared["event_hash_sha256"],
        record_hash_sha256="",
        prev_record_hash_sha256=prev_record_hash_sha256,
        record_hmac=None,
        hmac_key_version=None,
    )
    return replace(
        record,
        record_hash_sha256=_hash(_record_identity(record)),
    )


def _record_from_row(row) -> StoredHistoryRecord:
    try:
        payload = json.loads(row["payload_json"])
        payload = _copy_payload(payload)
        event_type = EventType(row["event_type"])
    except Exception as error:
        raise HistoryStoreCorruption(
            f"registro {row['record_id']} ilegível: {error}"
        ) from error
    return StoredHistoryRecord(
        record_id=row["record_id"],
        event_schema_version=row["event_schema_version"],
        request_id=row["request_id"],
        correlation_id=row["correlation_id"],
        parent_record_id=row["parent_record_id"],
        idempotency_key=row["idempotency_key"],
        event_type=event_type,
        sequence=row["sequence"],
        occurred_at_unix_ms=row["occurred_at_unix_ms"],
        recorded_at_unix_ms=row["recorded_at_unix_ms"],
        requester_id=row["requester_id"],
        subject_id=row["subject_id"],
        authentication_status=row["authentication_status"],
        identity_status=row["identity_status"],
        authority_basis=row["authority_basis"],
        threat_type=row["threat_type"],
        action=row["action"],
        target_hmac=row["target_hmac"],
        target_chars=row["target_chars"],
        intent_hmac=row["intent_hmac"],
        intent_chars=row["intent_chars"],
        authorization_status=row["authorization_status"],
        execution_status=row["execution_status"],
        cortex_status=row["cortex_status"],
        system_state=row["system_state"],
        payload=payload,
        event_hash_sha256=row["event_hash_sha256"],
        record_hash_sha256=row["record_hash_sha256"],
        prev_record_hash_sha256=row["prev_record_hash_sha256"],
        record_hmac=row["record_hmac"],
        hmac_key_version=row["hmac_key_version"],
    )


def _record_hash_ok(record: StoredHistoryRecord) -> bool:
    return _hash(_record_identity(record)) == record.record_hash_sha256


def _event_hash_ok(record: StoredHistoryRecord) -> bool:
    prepared = {
        "event_schema_version": record.event_schema_version,
        "request_id": record.request_id,
        "correlation_id": record.correlation_id,
        "parent_record_id": record.parent_record_id,
        "event_type": record.event_type,
        "requester_id": record.requester_id,
        "subject_id": record.subject_id,
        "authentication_status": record.authentication_status,
        "identity_status": record.identity_status,
        "authority_basis": record.authority_basis,
        "threat_type": record.threat_type,
        "action": record.action,
        "target_hmac": record.target_hmac,
        "target_chars": record.target_chars,
        "intent_hmac": record.intent_hmac,
        "intent_chars": record.intent_chars,
        "authorization_status": record.authorization_status,
        "execution_status": record.execution_status,
        "cortex_status": record.cortex_status,
        "system_state": record.system_state,
        "payload": record.payload,
    }
    return _hash(_event_identity(prepared)) == record.event_hash_sha256


def _parent_error(
    parent: StoredHistoryRecord | None,
    child: dict,
    sequence: int,
) -> str | None:
    event_type = child["event_type"]
    parent_id = child["parent_record_id"]
    if event_type == EventType.OUTCOME:
        if parent_id is None:
            return "PARENT_REQUIRED_FOR_OUTCOME"
    elif event_type == EventType.INTENT:
        if parent_id is not None:
            return "PARENT_NOT_ALLOWED_FOR_INTENT"
    elif parent_id is not None and event_type != EventType.AUDIT_GAP:
        return "PARENT_NOT_ALLOWED_FOR_EVENT"
    if parent_id is None:
        return None
    if parent is None:
        return "PARENT_NOT_FOUND"
    if parent.request_id != child["request_id"]:
        return "PARENT_REQUEST_MISMATCH"
    if event_type == EventType.OUTCOME and parent.event_type != EventType.INTENT:
        return "PARENT_TYPE_INVALID"
    if parent.sequence >= sequence:
        return "PARENT_ORDER_INVALID"
    if parent.record_id == child.get("record_id"):
        return "PARENT_SELF_REFERENCE"
    return None


def _validate_limit(limit: int, maximum: int = 1000) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit deve ser inteiro")
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit deve estar entre 1 e {maximum}")
    return limit


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_history_db_path() -> Path:
    raw = os.environ.get("KAIROS_HISTORY_DB")
    path = (
        Path(raw).expanduser()
        if raw
        else Path.home() / ".local" / "share" / "kairos" / "interaction_history.db"
    )
    resolved = path.resolve()
    try:
        resolved.relative_to(_default_repo_root())
    except ValueError:
        return path
    raise ValueError("o banco de histórico não pode ficar dentro do repositório")


# ───────────────────────── implementação em memória ─────────────────────────


class InMemoryInteractionHistoryStore:
    """Implementação determinística para testes; não é persistência durável."""

    def __init__(self):
        self._lock = threading.RLock()
        self._records: dict[str, StoredHistoryRecord] = {}
        self._by_request: dict[str, list[str]] = defaultdict(list)
        self._idempotency: dict[tuple[str, str], str] = {}
        self._closed = False

    @property
    def persistent(self) -> bool:
        return False

    def _ensure_open(self):
        if self._closed:
            raise HistoryStoreError("store fechado")

    def append(
        self,
        event: HistoryEvent,
        *,
        idempotency_key: str | None = None,
    ) -> AppendResult:
        try:
            prepared = _prepare_event(event, idempotency_key)
        except InvalidHistoryEvent as error:
            return AppendResult(
                PersistenceStatus.INVALID_RECORD, None, None,
                "INVALID_EVENT", str(error), False,
            )
        with self._lock:
            if self._closed:
                return AppendResult(
                    PersistenceStatus.UNAVAILABLE, None, None,
                    "STORE_CLOSED", "store fechado", False,
                )
            key = (prepared["request_id"], prepared["idempotency_key"])
            existing_id = (
                self._idempotency.get(key)
                if prepared["idempotency_key"] is not None else None
            )
            if existing_id is not None:
                existing = self._records[existing_id]
                if existing.event_hash_sha256 == prepared["event_hash_sha256"]:
                    return AppendResult(
                        PersistenceStatus.DUPLICATE, existing, existing.record_id,
                        None, None, False,
                    )
                return AppendResult(
                    PersistenceStatus.IDEMPOTENCY_CONFLICT, None,
                    existing.record_id, "IDEMPOTENCY_CONFLICT",
                    "mesma chave com conteúdo diferente", False,
                )

            request_records = self._by_request[prepared["request_id"]]
            sequence = len(request_records) + 1
            prev_hash = (
                self._records[request_records[-1]].record_hash_sha256
                if request_records else None
            )
            record_id = f"rec_{uuid.uuid4().hex}"
            parent = (
                self._records.get(prepared["parent_record_id"])
                if prepared["parent_record_id"] else None
            )
            parent_error = _parent_error(
                parent, {**prepared, "record_id": record_id}, sequence
            )
            if parent_error:
                return AppendResult(
                    PersistenceStatus.INVALID_RECORD, None, None,
                    parent_error, "vínculo parent_record_id inválido", False,
                )
            now = int(time.time() * 1000)
            record = _build_record(
                prepared,
                record_id=record_id,
                sequence=sequence,
                occurred_at_unix_ms=now,
                recorded_at_unix_ms=now,
                prev_record_hash_sha256=prev_hash,
            )
            self._records[record_id] = record
            request_records.append(record_id)
            if prepared["idempotency_key"] is not None:
                self._idempotency[key] = record_id
            return AppendResult(
                PersistenceStatus.RECORDED, record, None, None, None, False
            )

    def get(self, request_id: str) -> Sequence[StoredHistoryRecord]:
        with self._lock:
            self._ensure_open()
            ids = self._by_request.get(request_id, [])
            records = [self._records[i] for i in ids]
            return sorted(records, key=lambda r: r.sequence)

    def get_record(self, record_id: str) -> StoredHistoryRecord | None:
        with self._lock:
            self._ensure_open()
            return self._records.get(record_id)

    def list_recent(
        self,
        *,
        limit: int = 50,
        before_unix_ms: int | None = None,
        before_record_id: str | None = None,
    ) -> Sequence[StoredHistoryRecord]:
        limit = _validate_limit(limit)
        if before_unix_ms is not None and not before_record_id:
            raise ValueError("before_record_id é obrigatório com before_unix_ms")
        with self._lock:
            self._ensure_open()
            records = list(self._records.values())
        records.sort(
            key=lambda r: (r.occurred_at_unix_ms, r.record_id), reverse=True
        )
        if before_unix_ms is not None:
            records = [
                r for r in records
                if r.occurred_at_unix_ms < before_unix_ms
                or (
                    r.occurred_at_unix_ms == before_unix_ms
                    and r.record_id < before_record_id
                )
            ]
        return records[:limit]

    def list_for_subject(
        self,
        subject_id: str,
        *,
        from_unix_ms: int | None = None,
        to_unix_ms: int | None = None,
        limit: int = 100,
    ) -> Sequence[StoredHistoryRecord]:
        limit = _validate_limit(limit)
        with self._lock:
            self._ensure_open()
            records = [
                r for r in self._records.values()
                if r.subject_id == subject_id
                and (from_unix_ms is None or r.occurred_at_unix_ms >= from_unix_ms)
                and (to_unix_ms is None or r.occurred_at_unix_ms <= to_unix_ms)
            ]
        records.sort(
            key=lambda r: (r.occurred_at_unix_ms, r.record_id), reverse=True
        )
        return records[:limit]

    def health(self) -> StoreHealth:
        with self._lock:
            return StoreHealth(
                status="UNAVAILABLE" if self._closed else "OK",
                physical_schema_version=SCHEMA_VERSION,
                supported_event_schema_versions=SUPPORTED_EVENT_SCHEMA_VERSIONS,
                writable=not self._closed,
                latency_ms=0.0,
                last_error_code=None,
            )

    def verify_integrity(self, *, full: bool = False) -> IntegrityReport:
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda r: (r.request_id, r.sequence))
        previous_by_request: dict[str, StoredHistoryRecord] = {}
        first_bad = None
        checked = 0
        for record in records:
            checked += 1
            error = None
            if not _event_hash_ok(record):
                error = "event_hash inválido"
            elif not _record_hash_ok(record):
                error = "record_hash inválido"
            elif record.record_hmac is not None:
                error = "record_hmac não implementado"
            else:
                previous = previous_by_request.get(record.request_id)
                if previous is None:
                    if record.prev_record_hash_sha256 is not None:
                        error = "primeiro registro com prev_record_hash não nulo"
                elif record.prev_record_hash_sha256 != previous.record_hash_sha256:
                    error = "elo da cadeia inválido"
            if error and first_bad is None:
                first_bad = record.record_id
            previous_by_request[record.request_id] = record
        return IntegrityReport(
            ok=first_bad is None,
            checked_records=checked,
            first_bad_record_id=first_bad,
            anchored_at_unix_ms=max(
                (r.recorded_at_unix_ms for r in records), default=None
            ),
            detail="ok" if first_bad is None else "integridade violada",
        )

    def close(self) -> None:
        with self._lock:
            self._closed = True


# ───────────────────────── implementação SQLite ─────────────────────────


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS interaction_events (
        record_id                TEXT PRIMARY KEY,
        event_schema_version     INTEGER NOT NULL CHECK (event_schema_version > 0),
        request_id               TEXT NOT NULL,
        correlation_id           TEXT,
        parent_record_id         TEXT,
        idempotency_key          TEXT,
        event_type               TEXT NOT NULL CHECK (event_type IN (
            'INTERACTION','INTENT','OUTCOME','CORTEX_FAILURE',
            'AUTHORIZATION_DENIED','VALIDATION_REJECTED',
            'INFRASTRUCTURE_FAILURE','BREAK_GLASS','AUDIT_GAP'
        )),
        sequence                 INTEGER NOT NULL CHECK (sequence > 0),
        occurred_at_unix_ms      INTEGER NOT NULL,
        recorded_at_unix_ms      INTEGER NOT NULL,
        requester_id             TEXT,
        subject_id               TEXT,
        authentication_status    TEXT NOT NULL,
        identity_status          TEXT NOT NULL,
        authority_basis          TEXT,
        threat_type              TEXT,
        action                   TEXT,
        target_hmac              TEXT,
        target_chars             INTEGER,
        intent_hmac              TEXT,
        intent_chars             INTEGER,
        authorization_status     TEXT,
        execution_status         TEXT,
        cortex_status            TEXT,
        system_state             TEXT,
        payload_json             TEXT NOT NULL,
        event_hash_sha256        TEXT NOT NULL CHECK (
            length(event_hash_sha256) = 64
            AND event_hash_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        record_hash_sha256       TEXT NOT NULL CHECK (
            length(record_hash_sha256) = 64
            AND record_hash_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        prev_record_hash_sha256  TEXT,
        record_hmac              TEXT,
        hmac_key_version         INTEGER,
        UNIQUE (request_id, sequence),
        FOREIGN KEY (parent_record_id)
            REFERENCES interaction_events(record_id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_events_request_idempotency
    ON interaction_events (request_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_events_request
    ON interaction_events (request_id, recorded_at_unix_ms)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_events_correlation
    ON interaction_events (correlation_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_events_occurred
    ON interaction_events (occurred_at_unix_ms)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_events_requester
    ON interaction_events (requester_id, occurred_at_unix_ms)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_events_subject
    ON interaction_events (subject_id, occurred_at_unix_ms)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_events_type
    ON interaction_events (event_type, occurred_at_unix_ms)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_events_authorization
    ON interaction_events (authorization_status)
    """,
    """
    CREATE TABLE IF NOT EXISTS store_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


class SqliteInteractionHistoryStore:
    """Store durável em SQLite local, separado de qualquer memória cognitiva."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        busy_timeout_ms: int = 5000,
    ):
        path = Path(db_path).expanduser() if db_path is not None else default_history_db_path()
        path = path.resolve()
        try:
            path.relative_to(_default_repo_root())
        except ValueError:
            pass
        else:
            raise ValueError("o banco de histórico não pode ficar dentro do repositório")
        self.db_path = path
        self._lock = threading.RLock()
        self._closed = False
        self._conn: sqlite3.Connection | None = None
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._created_parent = False
        self._open()

    def _open(self):
        parent = self.db_path.parent
        self._created_parent = not parent.exists()
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._created_parent:
            try:
                os.chmod(parent, 0o700)
            except OSError:
                pass
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self._busy_timeout_ms / 1000.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise HistoryStoreError("não foi possível ativar foreign_keys")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
            conn.execute("PRAGMA synchronous = FULL")
            self._conn = conn
            self._initialize_schema()
            self._secure_files()
        except Exception:
            conn.close()
            self._conn = None
            raise

    def _initialize_schema(self):
        assert self._conn is not None
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise HistoryStoreError(
                f"schema físico {version} não suportado (máximo {SCHEMA_VERSION})"
            )
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _SCHEMA_STATEMENTS:
                self._conn.execute(statement)
            self._conn.execute(
                "INSERT OR IGNORE INTO store_meta (key, value) VALUES ('created_at', ?)",
                (str(int(time.time() * 1000)),),
            )
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.execute("COMMIT")
        except Exception:
            self._rollback()
            raise

    def _secure_files(self):
        for candidate in (
            self.db_path,
            Path(str(self.db_path) + "-wal"),
            Path(str(self.db_path) + "-shm"),
        ):
            try:
                if candidate.exists():
                    os.chmod(candidate, 0o600)
            except OSError:
                pass
        if self._created_parent:
            try:
                os.chmod(self.db_path.parent, 0o700)
            except OSError:
                pass

    def _ensure_open(self):
        if self._closed or self._conn is None:
            raise HistoryStoreError("store SQLite fechado")

    def _commit(self):
        assert self._conn is not None
        self._conn.execute("COMMIT")

    def _rollback(self):
        if self._conn is not None and self._conn.in_transaction:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    @staticmethod
    def _invalid(code: str, message: str) -> AppendResult:
        return AppendResult(
            PersistenceStatus.INVALID_RECORD, None, None, code, message, False
        )

    def append(
        self,
        event: HistoryEvent,
        *,
        idempotency_key: str | None = None,
    ) -> AppendResult:
        try:
            prepared = _prepare_event(event, idempotency_key)
        except InvalidHistoryEvent as error:
            return self._invalid("INVALID_EVENT", str(error))
        with self._lock:
            try:
                self._ensure_open()
            except HistoryStoreError as error:
                return AppendResult(
                    PersistenceStatus.UNAVAILABLE, None, None,
                    "STORE_CLOSED", str(error), False,
                )
            for attempt in range(MAX_RECORD_ATTEMPTS):
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as error:
                    text = str(error).lower()
                    if "locked" in text or "busy" in text:
                        return AppendResult(
                            PersistenceStatus.TIMEOUT, None, None,
                            "STORE_BUSY", "banco ocupado", True,
                        )
                    return AppendResult(
                        PersistenceStatus.UNAVAILABLE, None, None,
                        "STORE_UNAVAILABLE", str(error), False,
                    )
                except sqlite3.Error as error:
                    return AppendResult(
                        PersistenceStatus.UNAVAILABLE, None, None,
                        "STORE_UNAVAILABLE", str(error), False,
                    )
                try:
                    existing = self._existing_idempotent(prepared)
                    if existing is not None:
                        self._rollback()
                        if existing.event_hash_sha256 == prepared["event_hash_sha256"]:
                            return AppendResult(
                                PersistenceStatus.DUPLICATE, existing,
                                existing.record_id, None, None, False,
                            )
                        return AppendResult(
                            PersistenceStatus.IDEMPOTENCY_CONFLICT, None,
                            existing.record_id, "IDEMPOTENCY_CONFLICT",
                            "mesma chave com conteúdo diferente", False,
                        )
                    sequence, prev_hash = self._next_sequence(prepared["request_id"])
                    record_id = f"rec_{uuid.uuid4().hex}"
                    parent = None
                    if prepared["parent_record_id"]:
                        row = self._conn.execute(
                            "SELECT * FROM interaction_events WHERE record_id = ?",
                            (prepared["parent_record_id"],),
                        ).fetchone()
                        parent = _record_from_row(row) if row else None
                    parent_error = _parent_error(
                        parent, {**prepared, "record_id": record_id}, sequence
                    )
                    if parent_error:
                        self._rollback()
                        return self._invalid(
                            parent_error, "vínculo parent_record_id inválido"
                        )
                    now = int(time.time() * 1000)
                    record = _build_record(
                        prepared,
                        record_id=record_id,
                        sequence=sequence,
                        occurred_at_unix_ms=now,
                        recorded_at_unix_ms=now,
                        prev_record_hash_sha256=prev_hash,
                    )
                    self._insert(record)
                    self._commit()
                    return AppendResult(
                        PersistenceStatus.RECORDED, record, None, None, None, False
                    )
                except sqlite3.IntegrityError as error:
                    self._rollback()
                    existing = self._existing_idempotent(prepared)
                    if existing is not None:
                        if existing.event_hash_sha256 == prepared["event_hash_sha256"]:
                            return AppendResult(
                                PersistenceStatus.DUPLICATE, existing,
                                existing.record_id, None, None, False,
                            )
                        return AppendResult(
                            PersistenceStatus.IDEMPOTENCY_CONFLICT, None,
                            existing.record_id, "IDEMPOTENCY_CONFLICT",
                            "mesma chave com conteúdo diferente", False,
                        )
                    if attempt + 1 < MAX_RECORD_ATTEMPTS:
                        time.sleep(0.01 * (attempt + 1))
                        continue
                    return AppendResult(
                        PersistenceStatus.SEQUENCE_CONFLICT, None, None,
                        "SEQUENCE_CONFLICT", str(error), True,
                    )
                except sqlite3.OperationalError as error:
                    self._rollback()
                    text = str(error).lower()
                    if ("locked" in text or "busy" in text) and attempt + 1 < MAX_RECORD_ATTEMPTS:
                        time.sleep(0.01 * (attempt + 1))
                        continue
                    if "locked" in text or "busy" in text:
                        return AppendResult(
                            PersistenceStatus.TIMEOUT, None, None,
                            "STORE_BUSY", "banco ocupado", True,
                        )
                    return AppendResult(
                        PersistenceStatus.WRITE_FAILED, None, None,
                        "WRITE_FAILED", str(error), False,
                    )
                except HistoryStoreCorruption as error:
                    self._rollback()
                    return AppendResult(
                        PersistenceStatus.CORRUPT, None, None,
                        "CORRUPT", str(error), False,
                    )
                except Exception as error:
                    self._rollback()
                    return AppendResult(
                        PersistenceStatus.WRITE_FAILED, None, None,
                        "WRITE_FAILED", f"{type(error).__name__}: {error}", False,
                    )
            return AppendResult(
                PersistenceStatus.SEQUENCE_CONFLICT, None, None,
                "SEQUENCE_CONFLICT", "tentativas esgotadas", True,
            )

    def _existing_idempotent(self, prepared: dict):
        key = prepared["idempotency_key"]
        if key is None:
            return None
        row = self._conn.execute(
            "SELECT * FROM interaction_events WHERE request_id = ? AND idempotency_key = ?",
            (prepared["request_id"], key),
        ).fetchone()
        if row is None:
            return None
        record = _record_from_row(row)
        if (
            _canonical_json(record.payload) != row["payload_json"]
            or not _event_hash_ok(record)
            or not _record_hash_ok(record)
        ):
            raise HistoryStoreCorruption(
                f"registro {record.record_id} corrompido na idempotência"
            )
        return record

    def _next_sequence(self, request_id: str) -> tuple[int, str | None]:
        row = self._conn.execute(
            "SELECT sequence, record_hash_sha256 FROM interaction_events "
            "WHERE request_id = ? ORDER BY sequence DESC LIMIT 1",
            (request_id,),
        ).fetchone()
        if row is None:
            return 1, None
        return int(row["sequence"]) + 1, row["record_hash_sha256"]

    def _insert(self, record: StoredHistoryRecord):
        self._conn.execute(
            """
            INSERT INTO interaction_events (
                record_id, event_schema_version, request_id, correlation_id,
                parent_record_id, idempotency_key, event_type, sequence,
                occurred_at_unix_ms, recorded_at_unix_ms, requester_id,
                subject_id, authentication_status, identity_status,
                authority_basis, threat_type, action, target_hmac,
                target_chars, intent_hmac, intent_chars, authorization_status,
                execution_status, cortex_status, system_state, payload_json,
                event_hash_sha256, record_hash_sha256, prev_record_hash_sha256,
                record_hmac, hmac_key_version
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record.record_id, record.event_schema_version, record.request_id,
                record.correlation_id, record.parent_record_id,
                record.idempotency_key, record.event_type.value, record.sequence,
                record.occurred_at_unix_ms, record.recorded_at_unix_ms,
                record.requester_id, record.subject_id,
                record.authentication_status, record.identity_status,
                record.authority_basis, record.threat_type, record.action,
                record.target_hmac, record.target_chars, record.intent_hmac,
                record.intent_chars, record.authorization_status,
                record.execution_status, record.cortex_status,
                record.system_state, _canonical_json(record.payload),
                record.event_hash_sha256, record.record_hash_sha256,
                record.prev_record_hash_sha256, record.record_hmac,
                record.hmac_key_version,
            ),
        )

    def get(self, request_id: str) -> Sequence[StoredHistoryRecord]:
        with self._lock:
            self._ensure_open()
            rows = self._conn.execute(
                "SELECT * FROM interaction_events WHERE request_id = ? "
                "ORDER BY sequence ASC",
                (request_id,),
            ).fetchall()
            return [_record_from_row(row) for row in rows]

    def get_record(self, record_id: str) -> StoredHistoryRecord | None:
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT * FROM interaction_events WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            return _record_from_row(row) if row else None

    def list_recent(
        self,
        *,
        limit: int = 50,
        before_unix_ms: int | None = None,
        before_record_id: str | None = None,
    ) -> Sequence[StoredHistoryRecord]:
        limit = _validate_limit(limit)
        if before_unix_ms is not None and not before_record_id:
            raise ValueError("before_record_id é obrigatório com before_unix_ms")
        with self._lock:
            self._ensure_open()
            if before_unix_ms is None:
                rows = self._conn.execute(
                    "SELECT * FROM interaction_events "
                    "ORDER BY occurred_at_unix_ms DESC, record_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM interaction_events "
                    "WHERE occurred_at_unix_ms < ? "
                    "OR (occurred_at_unix_ms = ? AND record_id < ?) "
                    "ORDER BY occurred_at_unix_ms DESC, record_id DESC LIMIT ?",
                    (before_unix_ms, before_unix_ms, before_record_id, limit),
                ).fetchall()
            return [_record_from_row(row) for row in rows]

    def list_for_subject(
        self,
        subject_id: str,
        *,
        from_unix_ms: int | None = None,
        to_unix_ms: int | None = None,
        limit: int = 100,
    ) -> Sequence[StoredHistoryRecord]:
        limit = _validate_limit(limit)
        with self._lock:
            self._ensure_open()
            clauses = ["subject_id = ?"]
            args: list[object] = [subject_id]
            if from_unix_ms is not None:
                clauses.append("occurred_at_unix_ms >= ?")
                args.append(from_unix_ms)
            if to_unix_ms is not None:
                clauses.append("occurred_at_unix_ms <= ?")
                args.append(to_unix_ms)
            args.append(limit)
            rows = self._conn.execute(
                "SELECT * FROM interaction_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY occurred_at_unix_ms DESC, record_id DESC LIMIT ?",
                tuple(args),
            ).fetchall()
            return [_record_from_row(row) for row in rows]

    def health(self) -> StoreHealth:
        with self._lock:
            if self._closed or self._conn is None:
                return StoreHealth(
                    "UNAVAILABLE", SCHEMA_VERSION,
                    SUPPORTED_EVENT_SCHEMA_VERSIONS, False, None, "STORE_CLOSED",
                )
            started = time.perf_counter()
            try:
                version = self._conn.execute("PRAGMA user_version").fetchone()[0]
                versions = tuple(
                    row[0] for row in self._conn.execute(
                        "SELECT DISTINCT event_schema_version FROM interaction_events "
                        "ORDER BY event_schema_version"
                    ).fetchall()
                )
                writable = self._conn.execute("PRAGMA query_only").fetchone()[0] == 0
                latency = (time.perf_counter() - started) * 1000
                return StoreHealth(
                    "OK", int(version), versions or SUPPORTED_EVENT_SCHEMA_VERSIONS,
                    bool(writable), round(latency, 3), None,
                )
            except sqlite3.Error as error:
                return StoreHealth(
                    "UNAVAILABLE", SCHEMA_VERSION,
                    SUPPORTED_EVENT_SCHEMA_VERSIONS, False, None,
                    f"{type(error).__name__}: {error}",
                )

    def verify_integrity(self, *, full: bool = False) -> IntegrityReport:
        with self._lock:
            self._ensure_open()
            rows = self._conn.execute(
                "SELECT * FROM interaction_events ORDER BY request_id ASC, sequence ASC"
            ).fetchall()
        previous_by_request: dict[str, StoredHistoryRecord] = {}
        first_bad = None
        checked = 0
        for row in rows:
            checked += 1
            try:
                record = _record_from_row(row)
            except HistoryStoreCorruption:
                if first_bad is None:
                    first_bad = row["record_id"]
                continue
            error = None
            try:
                if _canonical_json(record.payload) != row["payload_json"]:
                    error = "payload_json não canônico"
                elif not _event_hash_ok(record):
                    error = "event_hash inválido"
                elif not _record_hash_ok(record):
                    error = "record_hash inválido"
                elif record.record_hmac is not None:
                    error = "record_hmac não implementado"
                else:
                    previous = previous_by_request.get(record.request_id)
                    if previous is None:
                        if record.prev_record_hash_sha256 is not None:
                            error = "primeiro registro com prev_record_hash não nulo"
                    elif record.prev_record_hash_sha256 != previous.record_hash_sha256:
                        error = "elo da cadeia inválido"
            except Exception as exc:
                error = f"falha de verificação: {exc}"
            if error and first_bad is None:
                first_bad = record.record_id
            previous_by_request[record.request_id] = record
        anchored = max((row["recorded_at_unix_ms"] for row in rows), default=None)
        return IntegrityReport(
            ok=first_bad is None,
            checked_records=checked,
            first_bad_record_id=first_bad,
            anchored_at_unix_ms=anchored,
            detail="ok" if first_bad is None else "integridade violada",
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
                try:
                    self._conn.close()
                finally:
                    self._conn = None
            self._closed = True


def create_default_history_store(
    *,
    busy_timeout_ms: int = 5000,
) -> SqliteInteractionHistoryStore:
    """Criar o store padrão fora do repositório (env KAIROS_HISTORY_DB)."""
    return SqliteInteractionHistoryStore(
        default_history_db_path(),
        busy_timeout_ms=busy_timeout_ms,
    )
