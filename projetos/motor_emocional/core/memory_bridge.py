"""Ponte de memória contextual — contrato OS102.

Recuperar não é provar. A ponte distingue:
- memória encontrada;
- ausência legítima de resultado;
- indisponibilidade, timeout, dados inválidos, falha de integridade e erro.

O conteúdo recuperado é serializado como dado, com `<`/`>` escapados para não
fechar o bloco `<R_MEMORIA>`. A ponte não remove palavras como "ignore" ou
"autorize": a separação entre dado e autoridade é estrutural, não filtragem.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .memory_contract import (
    FAILURE_STATUSES,
    MAX_CONTEXT_BYTES,
    MAX_FORMATTED_CONTEXT_CHARS,
    MEMORY_FOUND,
    MEMORY_INTERNAL_ERROR,
    MEMORY_INVALID_DATA,
    MEMORY_NOT_FOUND,
    MEMORY_OK,
    MEMORY_STATUSES,
    MEMORY_UNAVAILABLE,
    MemoryContractError,
    retrieval_result,
    safe_error,
    status_from_exception,
    validate_context,
    validate_memory_id,
    validate_similarity,
)

DEFAULT_THRESHOLD = 0.7


def _result_with_status(
    status: str,
    *,
    records: list = None,
    error: Optional[BaseException | str] = None,
    collection: str = "",
    persistent: bool = False,
    truncated: bool = False,
    eligible_count: int = 0,
    formatted_context: str = "",
    memory_id: str = None,
    similarity: float = None,
    distance: float = None,
) -> dict:
    return {
        "retrieval_ok": status not in FAILURE_STATUSES,
        "retrieval_success": bool(formatted_context) and eligible_count > 0,
        "retrieval_status": status,
        "retrieval_error": (
            safe_error(error)
            if isinstance(error, BaseException)
            else (str(error)[:300] if error else None)
        ),
        "collection": collection,
        "persistent": bool(persistent),
        "records": records or [],
        "eligible_count": eligible_count,
        "candidate_count": len(records or []),
        "formatted_context": formatted_context,
        "memory_id": memory_id,
        "similarity": similarity,
        "distance": distance,
        "truncated": bool(truncated),
    }


class MemoryContextBridge:
    def __init__(self, context_memory):
        self.context_memory = context_memory

    def describe(self) -> Dict[str, Any]:
        """Diagnóstico auditável, sem esconder erro de backend."""
        try:
            described = self.context_memory.describe()
            if not isinstance(described, dict):
                return {
                    "status": MEMORY_INVALID_DATA,
                    "error": "describe não devolveu objeto",
                }
            return described
        except Exception as error:
            return {
                "status": MEMORY_UNAVAILABLE,
                "error": safe_error(error),
            }

    def _backend_result(
        self,
        system: str,
        target: str,
        threat: str,
        top_k: int,
        threshold: float,
    ) -> dict:
        if hasattr(self.context_memory, "retrieve_with_status"):
            try:
                result = self.context_memory.retrieve_with_status(
                    system=system,
                    target=target,
                    threat=threat,
                    top_k=top_k,
                    min_similarity=-2.0,
                    include_distances=True,
                )
            except Exception as error:
                return retrieval_result(
                    status_from_exception(error),
                    error=error,
                )
            if not isinstance(result, dict):
                return retrieval_result(
                    MEMORY_INVALID_DATA,
                    error="retrieve_with_status não devolveu objeto",
                )
            status = result.get("status")
            if status not in MEMORY_STATUSES or status == MEMORY_OK:
                return retrieval_result(
                    MEMORY_INTERNAL_ERROR,
                    error=f"status de memória inválido para recuperação: {status!r}",
                )
            return result

        try:
            raw = self.context_memory.retrieve(
                system=system,
                target=target,
                threat=threat,
                top_k=top_k,
                min_similarity=-2.0,
                include_distances=True,
            )
        except Exception as error:
            return retrieval_result(MEMORY_UNAVAILABLE, error=error)

        if not isinstance(raw, list):
            return retrieval_result(
                MEMORY_INVALID_DATA,
                error="retrieve devolveu tipo diferente de lista",
            )
        return retrieval_result(
            MEMORY_FOUND if raw else MEMORY_NOT_FOUND,
            records=raw,
        )

    def _validate_record(self, raw: Any, threshold: float,
                         allow_legacy_unverified: bool) -> dict:
        if not isinstance(raw, dict):
            raise ValueError("registro não é objeto")
        memory = raw.get("memory")
        if not isinstance(memory, dict):
            raise ValueError("registro sem 'memory'")
        memory_id = memory.get("id")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("registro sem ID textual")
        try:
            memory_id = validate_memory_id(memory_id)
        except MemoryContractError as error:
            raise ValueError("registro com ID inválido") from error
        context = memory.get("context")
        if not isinstance(context, dict) or not context:
            raise ValueError("registro sem conteúdo")
        similarity = validate_similarity(raw.get("similarity"), "similarity")
        distance = validate_similarity(raw.get("distance"), "distance")
        integrity_status = memory.get("integrity_status")
        if integrity_status not in ("verified", "legacy_unverified"):
            raise ValueError("registro com integridade desconhecida")
        schema_version = memory.get("schema_version")
        if type(schema_version) is not int:
            raise ValueError("registro sem schema_version")
        if integrity_status == "verified" and schema_version != 2:
            raise ValueError("registro verificado com schema incompatível")
        if integrity_status == "legacy_unverified" and schema_version != 1:
            raise ValueError("registro legado com schema incompatível")
        source = memory.get("source", "unknown")
        memory_type = memory.get("memory_type", "unknown")
        if not isinstance(source, str) or not isinstance(memory_type, str):
            raise ValueError("registro com origem/tipo inválido")
        fallback = memory.get("fallback", False)
        if type(fallback) is not bool:
            raise ValueError("registro com fallback inválido")

        try:
            content_json = validate_context(context)
        except MemoryContractError as error:
            raise ValueError("conteúdo inválido") from error
        if len(content_json.encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise ValueError("conteúdo excede o limite")

        eligible = (
            similarity >= threshold
            and (integrity_status == "verified" or allow_legacy_unverified)
        )
        return {
            "id": memory_id,
            "similarity": round(similarity, 4),
            "distance": 0.0 if abs(distance) < 1e-12 else round(distance, 6),
            "eligible": eligible,
            "content": context,
            "content_json": content_json,
            "integrity_status": integrity_status,
            "source": source,
            "memory_type": memory_type,
            "schema_version": memory.get("schema_version"),
            "created_at": memory.get("created_at"),
            "fallback": fallback,
        }

    def build_context(
        self,
        system: str,
        target: str,
        threat: str,
        top_k: int = 2,
        threshold: float = DEFAULT_THRESHOLD,
        allow_legacy_unverified: bool = True,
    ) -> Dict[str, Any]:
        """Recupera e formata memórias com estado explícito.

        `retrieval_success` significa "há memória elegível injetada", não
        "a operação de memória funcionou". Use `retrieval_status`/`retrieval_ok`
        para distinguir ausência de falha.
        """
        try:
            threshold = validate_similarity(threshold, "threshold")
        except MemoryContractError as error:
            return _result_with_status(MEMORY_INVALID_DATA, error=error)
        if not (0.0 <= threshold <= 1.0):
            return _result_with_status(
                MEMORY_INVALID_DATA,
                error="threshold fora de 0..1",
            )
        if type(top_k) is not int or top_k < 1:
            return _result_with_status(
                MEMORY_INVALID_DATA,
                error="top_k inválido",
            )
        if type(allow_legacy_unverified) is not bool:
            return _result_with_status(
                MEMORY_INVALID_DATA,
                error="allow_legacy_unverified deve ser booleano",
            )

        backend = self._backend_result(system, target, threat, top_k, threshold)
        status = backend.get("status")
        collection = backend.get("collection", "") or ""
        persistent = bool(backend.get("persistent", False))

        if status != MEMORY_FOUND:
            if status == MEMORY_NOT_FOUND:
                return _result_with_status(
                    MEMORY_NOT_FOUND,
                    collection=collection,
                    persistent=persistent,
                )
            return _result_with_status(
                status,
                error=backend.get("error"),
                collection=collection,
                persistent=persistent,
            )

        raw_records = backend.get("records")
        if not isinstance(raw_records, list) or not raw_records:
            return _result_with_status(
                MEMORY_INVALID_DATA,
                error="MEMORY_FOUND sem registros",
                collection=collection,
                persistent=persistent,
            )

        records = []
        try:
            for raw in raw_records:
                records.append(
                    self._validate_record(
                        raw, threshold, allow_legacy_unverified
                    )
                )
        except Exception as error:
            return _result_with_status(
                MEMORY_INVALID_DATA,
                error=error,
                collection=collection,
                persistent=persistent,
            )

        eligible = sorted(
            (record for record in records if record["eligible"]),
            key=lambda item: item["similarity"],
            reverse=True,
        )

        formatted_parts = []
        formatted_length = 0
        truncated = False
        for record in eligible:
            escaped = (
                record["content_json"]
                .replace("<", "\\u003c")
                .replace(">", "\\u003e")
            )
            line = (
                f"<R_MEMORIA id='{record['id']}' "
                f"sim='{record['similarity']:.2f}' "
                f"trust='{record['integrity_status']}'> "
                f"{escaped} </R_MEMORIA>"
            )
            addition = len(line) + (1 if formatted_parts else 0)
            if formatted_length + addition > MAX_FORMATTED_CONTEXT_CHARS:
                truncated = True
                break
            formatted_parts.append(line)
            formatted_length += addition

        formatted = "\n".join(formatted_parts)
        top = eligible[0] if eligible else None
        return _result_with_status(
            MEMORY_FOUND,
            records=records,
            collection=collection,
            persistent=persistent,
            truncated=truncated,
            eligible_count=len(eligible),
            formatted_context=formatted,
            memory_id=top["id"] if top else None,
            similarity=top["similarity"] if top else None,
            distance=top["distance"] if top else None,
        )
