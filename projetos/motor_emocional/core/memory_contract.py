"""Contrato de memória da OS102.

Define estados, exceções, limites e validação de registros. Este módulo não
importa ChromaDB; é a base compartilhada por armazenamento, ponte de contexto e
Policy Engine.

Princípio: um registro recuperado é dado histórico, não autoridade. O digest
detecta divergência de conteúdo em relação ao momento da gravação; não prova
autoria nem resiste a um invasor que altere conteúdo e digest.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, List, Mapping, Optional

MEMORY_OK = "MEMORY_OK"
MEMORY_FOUND = "MEMORY_FOUND"
MEMORY_NOT_FOUND = "MEMORY_NOT_FOUND"
MEMORY_UNAVAILABLE = "MEMORY_UNAVAILABLE"
MEMORY_TIMEOUT = "MEMORY_TIMEOUT"
MEMORY_INVALID_DATA = "MEMORY_INVALID_DATA"
MEMORY_INTEGRITY_FAILURE = "MEMORY_INTEGRITY_FAILURE"
MEMORY_STORAGE_ERROR = "MEMORY_STORAGE_ERROR"
MEMORY_INTERNAL_ERROR = "MEMORY_INTERNAL_ERROR"

MEMORY_STATUSES = frozenset({
    MEMORY_OK,
    MEMORY_FOUND,
    MEMORY_NOT_FOUND,
    MEMORY_UNAVAILABLE,
    MEMORY_TIMEOUT,
    MEMORY_INVALID_DATA,
    MEMORY_INTEGRITY_FAILURE,
    MEMORY_STORAGE_ERROR,
    MEMORY_INTERNAL_ERROR,
})

FAILURE_STATUSES = frozenset({
    MEMORY_UNAVAILABLE,
    MEMORY_TIMEOUT,
    MEMORY_INVALID_DATA,
    MEMORY_INTEGRITY_FAILURE,
    MEMORY_STORAGE_ERROR,
    MEMORY_INTERNAL_ERROR,
})

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
INTEGRITY_ALGORITHM = "sha256"
MAX_ID_CHARS = 128
MAX_TEXT_CHARS = 512
MAX_SOURCE_CHARS = 64
MAX_MEMORY_TYPE_CHARS = 64
MAX_CONTEXT_BYTES = 64 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_TOP_K = 100
MAX_ERROR_CHARS = 300
MAX_FORMATTED_CONTEXT_CHARS = 16 * 1024

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
MEMORY_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

# Campos que pertencem ao schema/armazenamento, não ao conteúdo do chamador.
RESERVED_METADATA_KEYS = frozenset({
    "memory_id",
    "schema_version",
    "system",
    "target",
    "threat",
    "source",
    "memory_type",
    "embedding_dim",
    "embedding_kind",
    "created_at",
    "updated_at",
    "created_at_ms",
    "updated_at_ms",
    "timestamp",
    "context_json",
    "integrity_metadata",
    "fallback",
})


class MemoryContractError(Exception):
    """Falha de contrato de memória; nunca deve virar memória válida."""


class MemoryUnavailable(MemoryContractError):
    """Backend indisponível ou inacessível."""


class MemoryTimeout(MemoryContractError):
    """Backend excedeu o tempo de resposta."""


class MemoryInvalidRecord(MemoryContractError):
    """Registro malformado, incompatível ou fora dos limites."""


class MemoryIntegrityError(MemoryContractError):
    """Digest de conteúdo ou embedding divergente."""


class MemoryStorageError(MemoryContractError):
    """Falha de gravação/leitura no backend."""


class MemoryMetricMismatchError(MemoryStorageError):
    """A coleção existente usa uma métrica incompatível.

    A inicialização falha sem apagar a coleção. A recriação só pode ocorrer
    por uma chamada explícita a ``TriangulationMemory.reset()``.
    """

    def __init__(self, collection_name: str, requested_metric: str, actual_metric: str):
        self.collection_name = collection_name
        self.requested_metric = requested_metric
        self.actual_metric = actual_metric
        super().__init__(
            f"coleção '{collection_name}' usa métrica '{actual_metric}', "
            f"mas foi solicitada '{requested_metric}'; nenhum dado foi apagado"
        )


class MemoryDuplicateIdError(MemoryStorageError):
    """Tentativa de gravar um ID já existente."""


class MemoryReservedFieldError(MemoryInvalidRecord):
    """Contexto externo tentou usar um campo reservado."""


def validate_text(
    field: str,
    value: Any,
    *,
    max_chars: int = MAX_TEXT_CHARS,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise MemoryInvalidRecord(f"{field} deve ser string")
    if not allow_empty and not value.strip():
        raise MemoryInvalidRecord(f"{field} vazio")
    if len(value) > max_chars:
        raise MemoryInvalidRecord(
            f"{field} excede {max_chars} caracteres"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise MemoryInvalidRecord(f"{field} contém caractere de controle")
    return value


def validate_memory_id(value: Any) -> str:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise MemoryInvalidRecord("memory_id inválido")
    return value


def validate_source(value: Any) -> str:
    if not isinstance(value, str) or not SOURCE_PATTERN.match(value):
        raise MemoryInvalidRecord("source inválido")
    return value


def validate_memory_type(value: Any) -> str:
    if not isinstance(value, str) or not MEMORY_TYPE_PATTERN.match(value):
        raise MemoryInvalidRecord("memory_type inválido")
    return value


def validate_context(context: Any) -> str:
    """Valida e serializa o conteúdo canonicamente. Retorna JSON canônico."""
    if not isinstance(context, dict):
        raise MemoryInvalidRecord("context deve ser um dicionário")
    if not context:
        raise MemoryInvalidRecord("context vazio")

    for key in context:
        if not isinstance(key, str) or not key:
            raise MemoryInvalidRecord("context com chave inválida")
        if key in RESERVED_METADATA_KEYS:
            raise MemoryReservedFieldError(
                f"context não pode sobrescrever campo reservado: {key}"
            )
        if len(key) > 128:
            raise MemoryInvalidRecord("context com chave longa demais")
        if any(ord(char) < 32 or ord(char) == 127 for char in key):
            raise MemoryInvalidRecord("context com caractere de controle na chave")

    _validate_json_value(context)

    try:
        canonical = json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MemoryInvalidRecord(
            f"context não é JSON canônico: {type(error).__name__}"
        ) from error

    if len(canonical.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise MemoryInvalidRecord(
            f"context excede {MAX_CONTEXT_BYTES} bytes"
        )
    return canonical


def _validate_json_value(value: Any, depth: int = 0) -> None:
    if depth > 8:
        raise MemoryInvalidRecord("context excede a profundidade máxima")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise MemoryInvalidRecord("context com chave não textual")
            _validate_json_value(item, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item, depth + 1)
        return
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MemoryInvalidRecord("context contém número não finito")
        return
    raise MemoryInvalidRecord(
        f"context contém tipo não suportado: {type(value).__name__}"
    )


def canonical_record_payload(
    *,
    memory_id: str,
    schema_version: int,
    system: str,
    target: str,
    threat: str,
    context: Mapping[str, Any],
    source: str,
    memory_type: str,
    created_at_ms: int,
    updated_at_ms: int,
    embedding_kind: str,
) -> str:
    payload = {
        "memory_id": memory_id,
        "schema_version": schema_version,
        "system": system,
        "target": target,
        "threat": threat,
        "context": context,
        "source": source,
        "memory_type": memory_type,
        "created_at_ms": created_at_ms,
        "updated_at_ms": updated_at_ms,
        "embedding_kind": embedding_kind,
    }
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MemoryInvalidRecord(
            f"registro não é JSON canônico: {type(error).__name__}"
        ) from error


def content_digest(
    *,
    memory_id: str,
    schema_version: int,
    system: str,
    target: str,
    threat: str,
    context: Mapping[str, Any],
    source: str,
    memory_type: str,
    created_at_ms: int,
    updated_at_ms: int,
    embedding_kind: str,
) -> str:
    canonical = canonical_record_payload(
        memory_id=memory_id,
        schema_version=schema_version,
        system=system,
        target=target,
        threat=threat,
        context=context,
        source=source,
        memory_type=memory_type,
        created_at_ms=created_at_ms,
        updated_at_ms=updated_at_ms,
        embedding_kind=embedding_kind,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def embedding_digest(embedding: Any) -> str:
    import numpy as np

    array = np.asarray(embedding, dtype="<f4")
    if array.ndim != 1 or array.shape[0] != 3:
        raise MemoryInvalidRecord("embedding deve ter 3 dimensões")
    if not np.all(np.isfinite(array)):
        raise MemoryInvalidRecord("embedding contém valor não finito")
    if float(np.linalg.norm(array)) == 0.0:
        raise MemoryInvalidRecord("embedding não pode ser vetor nulo")
    return hashlib.sha256(array.tobytes()).hexdigest()


def build_integrity_metadata(content_sha256: str, embedding_sha256: str) -> str:
    if not _is_sha256_hex(content_sha256) or not _is_sha256_hex(embedding_sha256):
        raise MemoryInvalidRecord("digest de integridade inválido")
    return json.dumps(
        {
            "algorithm": INTEGRITY_ALGORITHM,
            "content_digest": content_sha256,
            "embedding_digest": embedding_sha256,
            "schema_version": SCHEMA_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def parse_integrity_metadata(value: Any) -> Dict[str, str]:
    if not isinstance(value, str) or len(value) > MAX_METADATA_BYTES:
        raise MemoryInvalidRecord("integrity_metadata ausente ou grande demais")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise MemoryInvalidRecord("integrity_metadata não é JSON") from error
    if not isinstance(parsed, dict):
        raise MemoryInvalidRecord("integrity_metadata não é objeto")
    if parsed.get("algorithm") != INTEGRITY_ALGORITHM:
        raise MemoryInvalidRecord("algoritmo de integridade não suportado")
    if parsed.get("schema_version") != SCHEMA_VERSION:
        raise MemoryInvalidRecord("schema_version de integridade incompatível")
    content = parsed.get("content_digest")
    embedding = parsed.get("embedding_digest")
    if not _is_sha256_hex(content) or not _is_sha256_hex(embedding):
        raise MemoryInvalidRecord("digest de integridade malformado")
    return {
        "content_digest": content.lower(),
        "embedding_digest": embedding.lower(),
    }


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def validate_similarity(value: Any, field: str = "similarity") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoryInvalidRecord(f"{field} não numérica")
    number = float(value)
    if not math.isfinite(number):
        raise MemoryInvalidRecord(f"{field} não finita")
    return number


def safe_error(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    text = text.replace("\n", " ").replace("\r", " ")
    return text[:MAX_ERROR_CHARS]


def status_from_exception(error: BaseException) -> str:
    if isinstance(error, MemoryTimeout):
        return MEMORY_TIMEOUT
    if isinstance(error, MemoryUnavailable):
        return MEMORY_UNAVAILABLE
    if isinstance(error, MemoryIntegrityError):
        return MEMORY_INTEGRITY_FAILURE
    if isinstance(error, MemoryInvalidRecord):
        return MEMORY_INVALID_DATA
    if isinstance(error, MemoryStorageError):
        return MEMORY_STORAGE_ERROR
    return MEMORY_INTERNAL_ERROR


def retrieval_result(
    status: str,
    *,
    records: Optional[List[dict]] = None,
    error: Optional[BaseException | str] = None,
    collection: str = "",
    persistent: bool = False,
    truncated: bool = False,
) -> dict:
    if status not in MEMORY_STATUSES:
        status = MEMORY_INTERNAL_ERROR
    if isinstance(error, BaseException):
        error_text = safe_error(error)
    elif isinstance(error, str):
        error_text = error[:MAX_ERROR_CHARS]
    else:
        error_text = None
    return {
        "status": status,
        "records": records or [],
        "error": error_text,
        "collection": collection,
        "persistent": bool(persistent),
        "truncated": bool(truncated),
    }


def store_result(
    status: str,
    *,
    memory_id: Optional[str] = None,
    error: Optional[BaseException | str] = None,
) -> dict:
    if status not in (MEMORY_OK, MEMORY_INVALID_DATA, MEMORY_STORAGE_ERROR,
                      MEMORY_UNAVAILABLE, MEMORY_TIMEOUT, MEMORY_INTERNAL_ERROR):
        status = MEMORY_INTERNAL_ERROR
    if isinstance(error, BaseException):
        error_text = safe_error(error)
    elif isinstance(error, str):
        error_text = error[:MAX_ERROR_CHARS]
    else:
        error_text = None
    return {"status": status, "memory_id": memory_id, "error": error_text}
