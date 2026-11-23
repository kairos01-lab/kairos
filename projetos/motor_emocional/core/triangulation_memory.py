"""Memória por Triangulação — armazenamento e recuperação com contrato OS102.

- IDs persistentes são UUID4 (ou explícitos), nunca `hash()`/timestamp.
- O embedding é um vetor determinístico de 3 dimensões derivado de SHA-256
  sobre a triangulação. Ele é estável entre processos, mas **não** é um
  embedding semântico; a limitação é explícita.
- Registros novos usam schema v2 com `context_json` e `integrity_metadata`
  (SHA-256 do conteúdo canônico + SHA-256 do embedding).
- Registros legados (schema v1) são lidos como `legacy_unverified`, depois de
  validação estrutural, e marcados como tal.
- Erros de backend não viram `[]`: `retrieve()` levanta exceções específicas;
  `retrieve_with_status()` devolve um estado explícito.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import logging
import math
import threading
import time
import uuid
from typing import Any, List, Optional

import chromadb
import chromadb.errors as chroma_errors
import numpy as np

from .memory_contract import (
    LEGACY_SCHEMA_VERSION,
    MAX_CONTEXT_BYTES,
    MAX_TOP_K,
    MEMORY_FOUND,
    MEMORY_NOT_FOUND,
    MEMORY_OK,
    MEMORY_UNAVAILABLE,
    SCHEMA_VERSION,
    MemoryContractError,
    MemoryDuplicateIdError,
    MemoryIntegrityError,
    MemoryInvalidRecord,
    MemoryStorageError,
    MemoryTimeout,
    MemoryUnavailable,
    RESERVED_METADATA_KEYS,
    build_integrity_metadata,
    content_digest,
    embedding_digest,
    parse_integrity_metadata,
    retrieval_result,
    safe_error,
    status_from_exception,
    store_result,
    validate_context,
    validate_memory_id,
    validate_memory_type,
    validate_similarity,
    validate_source,
    validate_text,
)

logger = logging.getLogger("TriangulationMemory")

EMBEDDING_KIND = "sha256_triangulation_v1"


def _first_sequence(value: Any) -> List[Any]:
    """Normaliza respostas do ChromaDB (listas aninhadas ou arrays numpy)."""
    if not isinstance(value, (list, tuple)) or not value:
        return []
    first = value[0]
    if isinstance(first, (list, tuple)):
        return list(first)
    if hasattr(first, "tolist"):
        converted = first.tolist()
        return converted if isinstance(converted, list) else []
    return []


def _is_duplicate_error(error: BaseException) -> bool:
    for name in ("IDAlreadyExistsError", "UniqueConstraintError", "DuplicateIDError"):
        error_type = getattr(chroma_errors, name, None)
        if error_type is not None and isinstance(error, error_type):
            return True
    return False


def _memory_access(method):
    """Serializar todas as operações públicas da memória por instância.

    Ordem de locks: motor (OS109/110) -> memória. Não há caminho memória ->
    motor, evitando inversão. Acesso direto adquire apenas o lock da memória.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._access_lock:
            return method(self, *args, **kwargs)

    return wrapper


class TriangulationMemory:
    """Memória triangulada com ChromaDB e contrato de integridade OS102."""

    def __init__(
        self,
        embedding_dim: int = 3,
        collection_name: str = "triangulation_mem",
        persist_path: str = None,
        metric: str = None,
        recreate_on_metric_mismatch: bool = False,
    ):
        if type(embedding_dim) is not int or embedding_dim != 3:
            raise MemoryInvalidRecord("embedding_dim deve ser 3")
        self.embedding_dim = embedding_dim
        self.collection_name = collection_name
        self.metric = metric
        self.persist_path = persist_path
        self.persistent = persist_path is not None
        self._access_lock = threading.RLock()

        try:
            if persist_path:
                self.client = chromadb.PersistentClient(path=persist_path)
            else:
                self.client = chromadb.EphemeralClient()
        except Exception as error:
            raise MemoryUnavailable("backend de memória indisponível") from error

        metadata = {"embedding_dim": embedding_dim}
        if metric:
            metadata["hnsw:space"] = metric

        try:
            try:
                self.collection = self.client.get_collection(name=collection_name)
            except chroma_errors.NotFoundError:
                self.collection = self.client.create_collection(
                    name=collection_name, metadata=metadata
                )
            except Exception as error:
                raise MemoryUnavailable(
                    "falha ao abrir coleção de memória"
                ) from error

            effective = self._effective_metric()
            if metric and effective != metric:
                if not recreate_on_metric_mismatch:
                    raise MemoryStorageError(
                        f"coleção '{collection_name}' usa métrica '{effective}', "
                        f"mas foi solicitada '{metric}'"
                    )
                try:
                    self.client.delete_collection(name=collection_name)
                    self.collection = self.client.create_collection(
                        name=collection_name, metadata=metadata
                    )
                except Exception as error:
                    raise MemoryStorageError(
                        "falha ao recriar coleção com métrica solicitada"
                    ) from error
        except MemoryContractError:
            raise
        except Exception as error:
            raise MemoryUnavailable("falha ao inicializar memória") from error

    def _effective_metric(self) -> str:
        meta = getattr(self.collection, "metadata", None) or {}
        return meta.get("hnsw:space", "l2")

    @_memory_access
    def describe(self) -> dict:
        """Diagnóstico sem atributos privados do ChromaDB."""
        try:
            count = self.collection.count()
        except Exception as error:
            return {
                "status": MEMORY_UNAVAILABLE,
                "collection_name": self.collection_name,
                "count": None,
                "requested_metric": self.metric,
                "effective_metric": self._effective_metric(),
                "metadata": dict(getattr(self.collection, "metadata", None) or {}),
                "persistent": self.persistent,
                "error": safe_error(error),
            }
        return {
            "status": MEMORY_OK,
            "collection_name": self.collection_name,
            "count": count,
            "requested_metric": self.metric,
            "effective_metric": self._effective_metric(),
            "metadata": dict(getattr(self.collection, "metadata", None) or {}),
            "persistent": self.persistent,
            "error": None,
        }

    def _generate_embedding(self, system: str, target: str, threat: str) -> np.ndarray:
        """Vetor determinístico de triangulação derivado de SHA-256.

        Não é embedding semântico. É estável entre processos e substitui o
        `hash()` nativo, que variava por processo.
        """
        digest = hashlib.sha256(
            f"{system}|{target}|{threat}".encode("utf-8")
        ).digest()
        values = [
            int.from_bytes(digest[index * 2:index * 2 + 2], "big") / 65535.0
            for index in range(3)
        ]
        embedding = np.array(values, dtype=np.float32)
        if float(np.linalg.norm(embedding)) == 0.0:
            embedding[0] = 1.0
        return embedding

    def _normalize_embedding(self, embedding: Any) -> np.ndarray:
        array = np.asarray(embedding, dtype=np.float32)
        if array.ndim != 1 or array.shape[0] != self.embedding_dim:
            raise MemoryInvalidRecord("embedding com dimensão inválida")
        if not np.all(np.isfinite(array)):
            raise MemoryInvalidRecord("embedding contém valor não finito")
        norm = float(np.linalg.norm(array))
        if norm == 0.0:
            raise MemoryInvalidRecord("embedding não pode ser vetor nulo")
        return (array / norm).astype(np.float32)

    @_memory_access
    def store(
        self,
        system: str,
        target: str,
        threat: str,
        embedding: np.ndarray = None,
        context: dict = None,
        *,
        memory_id: str = None,
        source: str = "internal",
        memory_type: str = "context",
    ) -> str:
        """Grava um registro validado. Levanta exceções específicas em falha.

        O ID é UUID4 por padrão. Um ID explícito é aceito, mas duplicatas
        levantam `MemoryDuplicateIdError`; não há sobrescrita silenciosa.
        """
        system = validate_text("system", system)
        target = validate_text("target", target)
        threat = validate_text("threat", threat)
        context_json = validate_context(context)
        source = validate_source(source)
        memory_type = validate_memory_type(memory_type)

        if memory_id is None:
            memory_id = f"mem_{uuid.uuid4().hex}"
        else:
            memory_id = validate_memory_id(memory_id)

        if embedding is None:
            embedding = self._generate_embedding(system, target, threat)
        normalized = self._normalize_embedding(embedding)

        created_at_ms = int(time.time() * 1000)
        if created_at_ms <= 0:
            raise MemoryStorageError("relógio do sistema inválido")
        updated_at_ms = created_at_ms
        integrity = build_integrity_metadata(
            content_digest(
                memory_id=memory_id,
                schema_version=SCHEMA_VERSION,
                system=system,
                target=target,
                threat=threat,
                context=context,
                source=source,
                memory_type=memory_type,
                created_at_ms=created_at_ms,
                updated_at_ms=updated_at_ms,
                embedding_kind=EMBEDDING_KIND,
            ),
            embedding_digest(normalized),
        )

        metadata = {
            "memory_id": memory_id,
            "schema_version": SCHEMA_VERSION,
            "system": system,
            "target": target,
            "threat": threat,
            "source": source,
            "memory_type": memory_type,
            "embedding_dim": self.embedding_dim,
            "embedding_kind": EMBEDDING_KIND,
            "created_at_ms": created_at_ms,
            "updated_at_ms": updated_at_ms,
            "context_json": context_json,
            "integrity_metadata": integrity,
        }

        try:
            existing = self.collection.get(ids=[memory_id], include=[])
            if existing.get("ids"):
                raise MemoryDuplicateIdError(
                    f"memory_id já existe: {memory_id}"
                )
            self.collection.add(
                ids=[memory_id],
                embeddings=[normalized.tolist()],
                documents=[f"{system} | {target} | {threat}"],
                metadatas=[metadata],
            )
            # `add` do ChromaDB pode ignorar silenciosamente um ID
            # duplicado em corrida entre processos. Confirmamos o conteúdo.
            stored = self.collection.get(
                ids=[memory_id], include=["metadatas"]
            )
            stored_ids = stored.get("ids") or []
            stored_metadatas = stored.get("metadatas") or []
            if not stored_ids or not stored_metadatas:
                raise MemoryStorageError("gravação não confirmada pelo backend")
            if stored_metadatas[0].get("integrity_metadata") != integrity:
                raise MemoryDuplicateIdError(
                    f"memory_id colidiu durante a gravação: {memory_id}"
                )
        except MemoryContractError:
            raise
        except Exception as error:
            if _is_duplicate_error(error):
                raise MemoryDuplicateIdError(
                    f"memory_id já existe: {memory_id}"
                ) from error
            raise MemoryStorageError(
                f"falha ao armazenar memória: {type(error).__name__}: {error}"
            ) from error
        return memory_id

    @_memory_access
    def store_with_status(self, *args, **kwargs) -> dict:
        try:
            memory_id = self.store(*args, **kwargs)
            return store_result(MEMORY_OK, memory_id=memory_id)
        except Exception as error:
            return store_result(
                status_from_exception(error),
                error=error,
            )

    def _validate_query(
        self,
        system: Optional[str],
        target: Optional[str],
        threat: Optional[str],
        top_k: int,
        min_similarity: float,
        include_distances: bool,
    ) -> None:
        for field, value in (
            ("system", system),
            ("target", target),
            ("threat", threat),
        ):
            if value is not None:
                validate_text(field, value, allow_empty=True)
        if type(top_k) is not int or not (1 <= top_k <= MAX_TOP_K):
            raise MemoryInvalidRecord(f"top_k deve estar entre 1 e {MAX_TOP_K}")
        validate_similarity(min_similarity, "min_similarity")
        if type(include_distances) is not bool:
            raise MemoryInvalidRecord("include_distances deve ser booleano")

    def _cosine_similarity(self, query_embedding: np.ndarray, stored_embedding: Any) -> float:
        query = np.asarray(query_embedding, dtype=np.float64)
        stored = np.asarray(stored_embedding, dtype=np.float64)
        if query.shape != stored.shape or query.ndim != 1:
            raise MemoryInvalidRecord("embedding armazenado com dimensão inválida")
        query_norm = float(np.linalg.norm(query))
        stored_norm = float(np.linalg.norm(stored))
        if query_norm == 0.0 or stored_norm == 0.0:
            raise MemoryInvalidRecord("embedding nulo no cálculo de similaridade")
        similarity = float(np.dot(query, stored) / (query_norm * stored_norm))
        if not math.isfinite(similarity):
            raise MemoryInvalidRecord("similaridade não finita")
        return similarity

    def _parse_record(
        self,
        memory_id: str,
        metadata: dict,
        embedding: Any,
        similarity: float,
        distance: float,
    ) -> dict:
        if not isinstance(metadata, dict):
            raise MemoryInvalidRecord("metadados do registro não são objeto")

        schema = metadata.get("schema_version", LEGACY_SCHEMA_VERSION)
        if type(schema) is not int or schema not in (LEGACY_SCHEMA_VERSION, SCHEMA_VERSION):
            raise MemoryInvalidRecord("schema_version incompatível")

        if schema == SCHEMA_VERSION:
            return self._parse_v2_record(
                memory_id, metadata, embedding, similarity, distance
            )
        return self._parse_v1_record(
            memory_id, metadata, embedding, similarity, distance
        )

    def _parse_v2_record(
        self,
        memory_id: str,
        metadata: dict,
        embedding: Any,
        similarity: float,
        distance: float,
    ) -> dict:
        stored_id = validate_memory_id(metadata.get("memory_id"))
        if stored_id != memory_id:
            raise MemoryInvalidRecord("memory_id não corresponde ao ID do ChromaDB")

        system = validate_text("system", metadata.get("system"))
        target = validate_text("target", metadata.get("target"))
        threat = validate_text("threat", metadata.get("threat"))
        source = validate_source(metadata.get("source"))
        memory_type = validate_memory_type(metadata.get("memory_type"))

        context_json = metadata.get("context_json")
        if not isinstance(context_json, str) or len(context_json) > MAX_CONTEXT_BYTES * 2:
            raise MemoryInvalidRecord("context_json ausente ou grande demais")
        try:
            context = json.loads(context_json)
        except json.JSONDecodeError as error:
            raise MemoryInvalidRecord("context_json não é JSON") from error
        validate_context(context)

        created_at_ms = metadata.get("created_at_ms")
        updated_at_ms = metadata.get("updated_at_ms")
        if (
            type(created_at_ms) is not int
            or type(updated_at_ms) is not int
            or created_at_ms <= 0
            or updated_at_ms <= 0
            or updated_at_ms < created_at_ms
        ):
            raise MemoryInvalidRecord("timestamps inválidos")

        if metadata.get("embedding_kind") != EMBEDDING_KIND:
            raise MemoryInvalidRecord("embedding_kind incompatível")
        if metadata.get("embedding_dim") != self.embedding_dim:
            raise MemoryInvalidRecord("embedding_dim incompatível")

        if embedding is None:
            raise MemoryInvalidRecord("embedding ausente para registro v2")
        normalized = self._normalize_embedding(embedding)

        integrity = parse_integrity_metadata(metadata.get("integrity_metadata"))
        expected_content = content_digest(
            memory_id=memory_id,
            schema_version=SCHEMA_VERSION,
            system=system,
            target=target,
            threat=threat,
            context=context,
            source=source,
            memory_type=memory_type,
            created_at_ms=created_at_ms,
            updated_at_ms=updated_at_ms,
            embedding_kind=EMBEDDING_KIND,
        )
        expected_embedding = embedding_digest(normalized)
        if not hmac.compare_digest(
            integrity["content_digest"], expected_content
        ):
            raise MemoryIntegrityError("digest de conteúdo divergente")
        if not hmac.compare_digest(
            integrity["embedding_digest"], expected_embedding
        ):
            raise MemoryIntegrityError("digest de embedding divergente")

        return {
            "memory": {
                "id": memory_id,
                "system": system,
                "target": target,
                "threat": threat,
                "context": context,
                "embedding": normalized.tolist(),
                "timestamp": created_at_ms / 1000.0,
                "created_at": created_at_ms / 1000.0,
                "created_at_ms": created_at_ms,
                "updated_at": updated_at_ms / 1000.0,
                "updated_at_ms": updated_at_ms,
                "schema_version": SCHEMA_VERSION,
                "source": source,
                "memory_type": memory_type,
                "integrity_status": "verified",
                "fallback": False,
            },
            "similarity": round(similarity, 4),
            "distance": 0.0 if abs(distance) < 1e-12 else round(distance, 6),
        }

    def _parse_v1_record(
        self,
        memory_id: str,
        metadata: dict,
        embedding: Any,
        similarity: float,
        distance: float,
    ) -> dict:
        system = validate_text("system", metadata.get("system"), allow_empty=True)
        target = validate_text("target", metadata.get("target"), allow_empty=True)
        threat = validate_text("threat", metadata.get("threat"), allow_empty=True)

        timestamp = validate_similarity(metadata.get("timestamp"), "timestamp")
        if timestamp < 0.0:
            raise MemoryInvalidRecord("timestamp legado inválido")

        embedding_dim = metadata.get("embedding_dim")
        if embedding_dim is not None and embedding_dim != self.embedding_dim:
            raise MemoryInvalidRecord("embedding_dim legado incompatível")

        fallback = metadata.get("fallback", False)
        if type(fallback) is not bool:
            raise MemoryInvalidRecord("fallback legado inválido")

        context = {
            key: value
            for key, value in metadata.items()
            if key not in RESERVED_METADATA_KEYS
        }
        validate_context(context)

        stored_embedding = None
        if embedding is not None:
            stored_embedding = self._normalize_embedding(embedding).tolist()

        return {
            "memory": {
                "id": memory_id,
                "system": system,
                "target": target,
                "threat": threat,
                "context": context,
                "embedding": stored_embedding,
                "timestamp": timestamp,
                "created_at": timestamp,
                "schema_version": LEGACY_SCHEMA_VERSION,
                "source": "legacy",
                "memory_type": "legacy_context",
                "integrity_status": "legacy_unverified",
                "fallback": fallback,
            },
            "similarity": round(similarity, 4),
            "distance": 0.0 if abs(distance) < 1e-12 else round(distance, 6),
        }

    @_memory_access
    def retrieve(
        self,
        system: str = None,
        target: str = None,
        threat: str = None,
        top_k: int = 5,
        min_similarity: float = 0.1,
        include_distances: bool = False,
    ) -> list:
        """Recupera memórias. Retorna [] apenas quando não há resultados.

        Falhas de backend, dados inválidos e divergências de integridade
        levantam exceções específicas (`MemoryUnavailable`, `MemoryStorageError`,
        `MemoryInvalidRecord`, `MemoryIntegrityError`, `MemoryTimeout`).
        Use `retrieve_with_status()` para obter um estado explícito sem
        exceção.
        """
        self._validate_query(
            system, target, threat, top_k, min_similarity, include_distances
        )
        query_embedding = self._generate_embedding(
            system or "", target or "", threat or ""
        )

        filters = []
        if system:
            filters.append({"system": system})
        if target:
            filters.append({"target": target})
        if threat:
            filters.append({"threat": threat})
        if not filters:
            where_filter = None
        elif len(filters) == 1:
            where_filter = filters[0]
        else:
            where_filter = {"$and": filters}

        include_fields = ["metadatas", "embeddings", "documents"]
        if include_distances:
            include_fields.append("distances")

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding.tolist()],
                where=where_filter,
                n_results=top_k,
                include=include_fields,
            )
        except TimeoutError as error:
            raise MemoryTimeout(
                f"timeout na consulta de memória: {type(error).__name__}: {error}"
            ) from error
        except chroma_errors.NotFoundError as error:
            raise MemoryUnavailable(
                f"coleção de memória indisponível: {type(error).__name__}: {error}"
            ) from error
        except Exception as error:
            raise MemoryStorageError(
                f"falha na consulta de memória: {type(error).__name__}: {error}"
            ) from error

        id_list = _first_sequence(results.get("ids"))
        if not id_list:
            return []
        metadata_list = _first_sequence(results.get("metadatas"))
        embedding_list = _first_sequence(results.get("embeddings"))
        if embedding_list and not isinstance(
            embedding_list[0], (list, tuple, np.ndarray)
        ):
            # Alguns backends devolvem um único vetor 1-D em vez de lista de vetores.
            embedding_list = [embedding_list]
        distance_list = _first_sequence(results.get("distances"))
        if len(metadata_list) < len(id_list):
            raise MemoryInvalidRecord("resultado do backend sem metadados completos")

        retrieved = []
        for index, raw_id in enumerate(id_list):
            memory_id = validate_memory_id(raw_id)
            metadata = metadata_list[index]
            embedding = (
                embedding_list[index]
                if index < len(embedding_list)
                else None
            )

            if include_distances and index < len(distance_list):
                distance = validate_similarity(distance_list[index], "distance")
                similarity = 1.0 - distance
            elif embedding is not None:
                similarity = self._cosine_similarity(query_embedding, embedding)
                distance = 1.0 - similarity
            else:
                raise MemoryInvalidRecord("resultado sem distância nem embedding")

            if not math.isfinite(similarity):
                raise MemoryInvalidRecord("similaridade não finita")
            if similarity < min_similarity:
                continue
            retrieved.append(
                self._parse_record(
                    memory_id, metadata, embedding, similarity, distance
                )
            )

        retrieved.sort(key=lambda item: item["similarity"], reverse=True)
        return retrieved[:top_k]

    @_memory_access
    def retrieve_with_status(
        self,
        system: str = None,
        target: str = None,
        threat: str = None,
        top_k: int = 5,
        min_similarity: float = 0.1,
        include_distances: bool = False,
    ) -> dict:
        """Como `retrieve`, mas devolve `{status, records, error, ...}`."""
        try:
            records = self.retrieve(
                system=system,
                target=target,
                threat=threat,
                top_k=top_k,
                min_similarity=min_similarity,
                include_distances=include_distances,
            )
            status = MEMORY_FOUND if records else MEMORY_NOT_FOUND
            return retrieval_result(
                status,
                records=records,
                collection=self.collection_name,
                persistent=self.persistent,
            )
        except Exception as error:
            return retrieval_result(
                status_from_exception(error),
                error=error,
                collection=self.collection_name,
                persistent=self.persistent,
            )

    @_memory_access
    def get_stats(self) -> dict:
        try:
            count = self.collection.count()
            return {
                "status": MEMORY_OK,
                "total": count,
                "embedding_dim": self.embedding_dim,
                "persistent": self.persistent,
                "collection_name": self.collection_name,
                "error": None,
            }
        except Exception as error:
            logger.warning(
                "[TriangulationMemory] get_stats falhou: %s",
                type(error).__name__,
            )
            return {
                "status": MEMORY_UNAVAILABLE,
                "total": None,
                "embedding_dim": self.embedding_dim,
                "persistent": self.persistent,
                "collection_name": self.collection_name,
                "error": safe_error(error),
            }

    @_memory_access
    def reset(self):
        """Remove e recria a coleção. Falhas reais são levantadas."""
        try:
            self.client.delete_collection(name=self.collection_name)
        except chroma_errors.NotFoundError:
            pass
        except Exception as error:
            raise MemoryStorageError("falha ao remover coleção") from error

        metadata = {"embedding_dim": self.embedding_dim}
        if self.metric:
            metadata["hnsw:space"] = self.metric
        try:
            self.collection = self.client.create_collection(
                name=self.collection_name, metadata=metadata
            )
        except Exception as error:
            raise MemoryStorageError("falha ao recriar coleção") from error

    @_memory_access
    def get_collection_info(self) -> dict:
        try:
            collection = self.client.get_collection(name=self.collection_name)
            return {
                "status": MEMORY_OK,
                "name": self.collection_name,
                "total_items": collection.count(),
                "metadata": dict(collection.metadata or {}),
                "persistent": self.persistent,
                "error": None,
            }
        except Exception as error:
            return {
                "status": MEMORY_UNAVAILABLE,
                "name": self.collection_name,
                "total_items": None,
                "metadata": {},
                "persistent": self.persistent,
                "error": safe_error(error),
            }


def create_memory_client(persist_path: str = None) -> TriangulationMemory:
    """Factory para criar cliente de memória."""
    return TriangulationMemory(embedding_dim=3, persist_path=persist_path)
