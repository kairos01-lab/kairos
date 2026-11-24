"""Motor Emocional Completo - Integração do Sistema.

Línguagem central que orquestra:
1. Matriz RGB Emocional
2. Fígado Virtual (gestão de estresse)
3. Memória por Triangulação
4. Policy Engine 2.0 (degradação graciosa)
5. Cortex Pre-Frontal (LLM)
6. Dashboard em tempo real
"""
import asyncio
import concurrent.futures
import copy
import functools
import threading
import time
import numpy as np
from collections import deque
from typing import Dict, Any

from .emotional_matrix import EmotionalMatrix
from .virtual_liver import VirtualLiver
from .triangulation_memory import TriangulationMemory
from .memory_bridge import MemoryContextBridge
from .policy_engine import PolicyEngine20
from .policy_controls import build_policy_controls as _build_policy_controls
from .authorization_contract import (
    AUTHORIZATION_AUTHORIZED,
    AUTHORIZATION_DENIED,
    AUTHORIZATION_INFRASTRUCTURE_FAILURE,
    AUTHORIZATION_INPUT_INVALID,
    AUTHORIZATION_PARTIAL,
    EXECUTION_CORTEX_ONLY,
    EXECUTION_NOT_EXECUTED,
    build_authorization_record,
    build_evidence_record,
    build_identity_context,
    derive_authorization_status,
    new_request_id,
)
from .cortex_prefrontal import (
    CortexPreFrontal,
    init_cortex,
    get_cortex,
    CORTEX_OK,
    CORTEX_TRUNCATED,
    CORTEX_STATUSES,
    CORTEX_INTERNAL_ERROR,
    CORTEX_INVALID_RESPONSE,
    CORTEX_EMPTY_RESPONSE,
)
from .dashboard import EmotionalDashboard, init_dashboard, get_dashboard
from .interaction_history import (
    AppendResult,
    AuditCompleteness,
    EventType,
    HistoryEvent,
    InteractionHistoryStore,
    PersistenceStatus,
    create_default_history_store,
)
from . import guarda_costas


def _run_coroutine_sync(coroutine):
    """Executa uma corrotina sem reutilizá-la em caso de exceção.

    Se já existe um event loop no thread atual (ex.: rota FastAPI), a corrotina
    roda em um thread separado. Fora de um loop, `asyncio.run` cria um loop
    isolado. Nunca há uma segunda execução da mesma corrotina.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


_MAX_USER_ID_CHARS = 256
_MAX_THREAT_TYPE_CHARS = 512
_MAX_USER_INPUT_CHARS = 8_192
_MAX_SYSTEM_PROMPT_CHARS = 32_768
_MAX_REQUEST_ID_CHARS = 128
_VALID_ACTIONS = frozenset({"create", "read", "update", "delete"})


def _has_control_or_format(value: str) -> bool:
    for char in value:
        code = ord(char)
        if code < 32 or code == 127:
            return True
        if (
            0x200B <= code <= 0x200F
            or 0x202A <= code <= 0x202E
            or 0x2060 <= code <= 0x206F
            or code == 0xFEFF
        ):
            return True
    return False


def _text_input_error(field: str, value, max_chars: int):
    if not isinstance(value, str):
        return f"{field} deve ser string"
    if not value.strip():
        return f"{field} vazio"
    if value != value.strip():
        return f"{field} com espaço no início ou no fim"
    if len(value) > max_chars:
        return f"{field} excede {max_chars} caracteres"
    if _has_control_or_format(value):
        return f"{field} contém caractere de controle/formatação"
    return None


def _validate_interaction_inputs(
    user_id,
    threat_type,
    user_input,
    system_prompt,
    action,
    target,
    intent,
    from_majority_vote,
    subject_id=None,
    request_id=None,
):
    """Valida tipos/estrutura antes de qualquer decisão de segurança.

    Não normaliza nem converte valores complexos em string. Retorna o primeiro
    erro seguro ou `None`.
    """
    error = _text_input_error("user_id", user_id, _MAX_USER_ID_CHARS)
    if error:
        return {"field": "user_id", "reason": error}
    error = _text_input_error("threat_type", threat_type, _MAX_THREAT_TYPE_CHARS)
    if error:
        return {"field": "threat_type", "reason": error}
    if subject_id is not None:
        error = _text_input_error("subject_id", subject_id, _MAX_USER_ID_CHARS)
        if error:
            return {"field": "subject_id", "reason": error}
    if request_id is not None:
        error = _text_input_error(
            "request_id", request_id, _MAX_REQUEST_ID_CHARS
        )
        if error:
            return {"field": "request_id", "reason": error}
    if user_input is not None and not isinstance(user_input, str):
        return {"field": "user_input", "reason": "user_input deve ser string ou None"}
    if isinstance(user_input, str) and len(user_input) > _MAX_USER_INPUT_CHARS:
        return {
            "field": "user_input",
            "reason": f"user_input excede {_MAX_USER_INPUT_CHARS} caracteres",
        }
    if not isinstance(system_prompt, str):
        return {"field": "system_prompt", "reason": "system_prompt deve ser string"}
    if len(system_prompt) > _MAX_SYSTEM_PROMPT_CHARS:
        return {
            "field": "system_prompt",
            "reason": f"system_prompt excede {_MAX_SYSTEM_PROMPT_CHARS} caracteres",
        }
    if not isinstance(action, str) or action not in _VALID_ACTIONS:
        return {
            "field": "action",
            "reason": "action deve ser create, read, update ou delete",
        }
    if target is not None and not isinstance(target, str):
        return {"field": "target", "reason": "target deve ser string ou None"}
    if intent is not None and not isinstance(intent, str):
        return {"field": "intent", "reason": "intent deve ser string ou None"}
    if type(from_majority_vote) is not bool:
        return {
            "field": "from_majority_vote",
            "reason": "from_majority_vote deve ser booleano estrito",
        }
    return None


class MotorShuttingDown(RuntimeError):
    """Nova operação recusada porque o motor está encerrando."""


def _serialized_motor_state(method):
    """Serializar mutações/leituras de estado do motor por instância.

    O motor compartilha fígado, matriz, histórico, dashboard, política e
    Córtex. A execução concorrente real não é suportada; o lock impede
    interleaving quando chamadores usam threads. Ele não move a execução para
    outra thread e não resolve, sozinho, bloqueio de event loop.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            result = method(self, *args, **kwargs)
            if method.__name__ in (
                "process_interaction",
                "trigger_break_glass",
                "add_stress",
            ):
                try:
                    snapshot = self._snapshot_status()
                    snapshot["snapshot_status"] = "CURRENT"
                    self._status_snapshot = copy.deepcopy(snapshot)
                except Exception:
                    pass
            return result

    return wrapper


class MotorEmocional:
    """Orquestrador principal do sistema emocional."""

    def __init__(
        self,
        cortex_use_local: bool = False,
        cortex_model_path: str = None,
        cortex_api_key: str = None,
        cortex_use_router: bool = False,
        cortex_api_router=None,
        dashboard_history: int = 50,
        policy_mem_path: str = '/tmp/policy_mem',
        context_mem_path: str = '/tmp/context_mem',
        liver_decay: float = 0.003,
        liver_cap: float = 100.0,
        history_store: InteractionHistoryStore | None = None,
    ):
        """Inicializar motor emocional completo.

        Args:
            cortex_use_local: Se True, usa LLM local via ctranslate2
            cortex_model_path: Caminho para modelo GGUF local
            cortex_api_key: Chave de API para LLM remoto
            dashboard_history: Tamanho do histórico da dashboard
            liver_decay: Taxa de decaimento do fígado (λ)
            liver_cap: Capacidade máxima de estresse do fígado (S_0)
        """
        self._state_lock = threading.RLock()
        self._shutting_down = False
        self._shutdown_complete = False
        self._status_snapshot = None
        self._last_executor_future = None
        self.history_store = history_store
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="kairos-motor",
        )
        # 1. Inicializar componentes límbicos
        self.emotional_matrix = EmotionalMatrix()
        self.virtual_liver = VirtualLiver(decay_rate=liver_decay, stress_cap=liver_cap)
        
        # Duas instâncias separadas (isolar Policy de Contexto)
        self.triangulation_memory = TriangulationMemory(embedding_dim=3, persist_path=policy_mem_path)
        self.context_memory = TriangulationMemory(
            embedding_dim=3,
            persist_path=context_mem_path,
            metric="cosine",  # métrica explícita da variável independente
        )
        self.memory_bridge = MemoryContextBridge(self.context_memory)

        # 2. Policy Engine 2.0 (degradação graciosa)
        self.policy_engine = PolicyEngine20(
            liver=self.virtual_liver,
            memory=self.triangulation_memory,
        )

        # 3. Cortex Pre-Frontal (LLM)
        self.cortex = init_cortex(
            use_local=cortex_use_local,
            local_model_path=cortex_model_path,
            api_key=cortex_api_key,
            use_router=cortex_use_router,
            api_router=cortex_api_router,
            state_lock=self._state_lock,
        )

        # 4. Dashboard
        self.dashboard = init_dashboard(history_size=dashboard_history)

        # 5. Histórico de interações
        self.interaction_history = deque(maxlen=dashboard_history)
        self.authorization_history = deque(maxlen=dashboard_history)
        self.start_time = time.time()

        # Estado atual
        self.current_policy_action = "Nenhuma"
        self.current_system_state = "INICIALIZANDO"
        try:
            snapshot = self._snapshot_status()
            snapshot["snapshot_status"] = "CURRENT"
            self._status_snapshot = copy.deepcopy(snapshot)
        except Exception:
            self._status_snapshot = None

        print("✅ Motor Emocional Completo inicializado")
        print("   Componentes:")
        print("   - Matriz RGB Emocional")
        print("   - Fígado Virtual (gerenciamento de entropia)")
        print("   - Memória por Triangulação")
        print("   - Policy Engine 2.0 (Degradação Graciosa)")
        print("   - Cortex Pre-Frontal")
        print("   - Dashboard em tempo real")

    def _record_authorization_audit(self, record: dict) -> dict:
        """Registrar decisão sem permitir que falha de log altere o resultado."""
        try:
            self.authorization_history.append(copy.deepcopy(record))
            return {
                "status": "RECORDED",
                "entries": len(self.authorization_history),
                "error": None,
            }
        except Exception as error:
            # A decisão já foi tomada; falha de auditoria não pode virar
            # autorização nem reverter uma negação.
            return {
                "status": "LOGGING_FAILED",
                "entries": None,
                "error": type(error).__name__,
            }

    def _authorization_record(
        self,
        *,
        request_id_value,
        identity,
        action,
        target,
        intent,
        threat_type,
        hard_block,
        kernel,
        policy_controls,
        decision,
        decision_reason,
        policy_evaluated,
        complete,
        execution_status,
        execution_detail,
        reincidence_basis=None,
        policy_provenance=None,
    ) -> dict:
        record = build_authorization_record(
            request_id=request_id_value,
            identity=identity,
            action=action,
            target=target,
            intent=intent,
            threat_type=threat_type,
            hard_block=hard_block,
            kernel=kernel,
            policy_controls=policy_controls,
            decision=decision,
            decision_reason=decision_reason,
            policy_evaluated=policy_evaluated,
            complete=complete,
            execution_status=execution_status,
            execution_detail=execution_detail,
            reincidence_basis=reincidence_basis,
            policy_provenance=policy_provenance,
        )
        record["audit"] = self._record_authorization_audit(record)
        return record

    def _invalid_input_result(
        self,
        validation: dict,
        t0: float,
        *,
        identity=None,
        request_id_value=None,
        action=None,
        target=None,
        intent=None,
        threat_type=None,
    ) -> Dict[str, Any]:
        """Resultado fail-closed para entrada rejeitada antes da política."""
        stress = self.virtual_liver.get_stress_level()
        identity = identity or build_identity_context(None)
        request_id_value = request_id_value or new_request_id()
        record = self._authorization_record(
            request_id_value=request_id_value,
            identity=identity,
            action=action,
            target=target,
            intent=intent,
            threat_type=threat_type,
            hard_block={},
            kernel=None,
            policy_controls={"evaluated": False, "status": "INPUT_INVALID"},
            decision=AUTHORIZATION_INPUT_INVALID,
            decision_reason=(
                f"ENTRADA INVÁLIDA ({validation['field']}): "
                f"{validation['reason']}"
            ),
            policy_evaluated=False,
            complete=False,
            execution_status=EXECUTION_NOT_EXECUTED,
            execution_detail="Entrada rejeitada antes de Hard Block/Kernel/Policy.",
        )
        authorization = {
            "guard_status": "GUARD_INVALID_INPUT",
            "kernel_status": "KERNEL_NOT_EVALUATED",
            "kernel": None,
            "hard_block": {},
            "reincidence_input": None,
            "reincidence_basis": "INPUT_INVALID",
        }
        authorization.update(record)
        authorization["authorization_status"] = record["decision"]
        return {
            "request_id": request_id_value,
            "response": None,
            "blocked": True,
            "blocked_by": "guard_invalid_input",
            "guard_status": "GUARD_INVALID_INPUT",
            "kernel_status": "KERNEL_NOT_EVALUATED",
            "reasoning": (
                f"ENTRADA INVÁLIDA ({validation['field']}): "
                f"{validation['reason']}"
            ),
            "emotional_state": {
                "valencia": float(self.emotional_matrix.get_state()[0]),
                "energia": float(self.emotional_matrix.get_state()[1]),
                "previsibilidade": float(self.emotional_matrix.get_state()[2]),
            },
            "stress_level": {
                "value": stress,
                "level": None,
                "action": "não avaliada",
            },
            "guarda_costas": {},
            "kernel": None,
            "authorization": authorization,
            "authorization_status": record["decision"],
            "authorization_complete": False,
            "execution": record["execution"],
            "policy_result": None,
            "policy_controls": {
                "evaluated": False,
                "status": "INPUT_INVALID",
            },
            "validation": {
                "status": "INPUT_INVALID",
                "field": validation["field"],
                "reason": validation["reason"],
            },
            "cortex_status": "CORTEX_NOT_CALLED",
            "cortex_meta": {},
            "processing_time_ms": round((time.time() - t0) * 1000, 2),
            "system_state": "INPUT_INVALID",
        }

    def _policy_failure_result(
        self,
        error,
        t0: float,
        *,
        identity,
        request_id_value,
        action,
        target,
        intent,
        threat_type,
    ) -> Dict[str, Any]:
        """Falha do Policy Engine é estado explícito, nunca autorização."""
        stress = self.virtual_liver.get_stress_level()
        reason = (
            f"FALHA DO POLICY ENGINE: {type(error).__name__}: {error}"
        )
        record = self._authorization_record(
            request_id_value=request_id_value,
            identity=identity,
            action=action,
            target=target,
            intent=intent,
            threat_type=threat_type,
            hard_block={},
            kernel=None,
            policy_controls={"evaluated": False, "status": "POLICY_ERROR"},
            decision=AUTHORIZATION_INFRASTRUCTURE_FAILURE,
            decision_reason=reason,
            policy_evaluated=False,
            complete=False,
            execution_status=EXECUTION_NOT_EXECUTED,
            execution_detail="Policy Engine falhou; operação não executada.",
        )
        authorization = {
            "guard_status": "POLICY_NOT_EVALUATED",
            "kernel_status": "KERNEL_NOT_EVALUATED",
            "kernel": None,
            "hard_block": {},
            "reincidence_input": None,
            "reincidence_basis": "POLICY_ERROR",
        }
        authorization.update(record)
        authorization["authorization_status"] = record["decision"]
        self.dashboard.record_interaction(
            emotional_state={
                "valencia": float(self.emotional_matrix.get_state()[0]),
                "energia": float(self.emotional_matrix.get_state()[1]),
                "previsibilidade": float(self.emotional_matrix.get_state()[2]),
            },
            stress_level=stress,
            policy_level=None,
            policy_action=f"[POLÍTICA] {reason}",
        )
        self.current_system_state = "POLICY_INDISPONIVEL"
        return {
            "request_id": request_id_value,
            "response": None,
            "blocked": True,
            "blocked_by": "policy_internal_error",
            "guard_status": "POLICY_NOT_EVALUATED",
            "kernel_status": "KERNEL_NOT_EVALUATED",
            "reasoning": reason,
            "emotional_state": {
                "valencia": float(self.emotional_matrix.get_state()[0]),
                "energia": float(self.emotional_matrix.get_state()[1]),
                "previsibilidade": float(self.emotional_matrix.get_state()[2]),
            },
            "stress_level": {
                "value": stress,
                "level": None,
                "action": "não avaliada",
            },
            "guarda_costas": {},
            "kernel": None,
            "authorization": authorization,
            "authorization_status": record["decision"],
            "authorization_complete": False,
            "execution": record["execution"],
            "policy_result": None,
            "policy_controls": {
                "evaluated": False,
                "status": "POLICY_ERROR",
            },
            "cortex_status": "CORTEX_NOT_CALLED",
            "cortex_meta": {},
            "processing_time_ms": round((time.time() - t0) * 1000, 2),
            "system_state": "POLICY_INDISPONIVEL",
        }

    @staticmethod
    def _history_event_type(result: Dict[str, Any]) -> EventType:
        if result.get("authorization_status") == AUTHORIZATION_INPUT_INVALID:
            return EventType.VALIDATION_REJECTED
        if result.get("blocked") is True:
            blocked = str(result.get("blocked_by") or "")
            infra_markers = (
                "internal_error", "unavailable", "timeout",
                "provenance_error", "policy_error", "guard_error",
            )
            if any(marker in blocked for marker in infra_markers):
                return EventType.INFRASTRUCTURE_FAILURE
            return EventType.AUTHORIZATION_DENIED
        if result.get("cortex_status") == CORTEX_OK:
            return EventType.INTERACTION
        return EventType.CORTEX_FAILURE

    @staticmethod
    def _history_identity(result: Dict[str, Any], user_id: str, subject_id: str | None):
        authorization = result.get("authorization") or {}
        requester = authorization.get("requester") if isinstance(authorization, dict) else {}
        subject = authorization.get("subject") if isinstance(authorization, dict) else {}
        requester = requester if isinstance(requester, dict) else {}
        subject = subject if isinstance(subject, dict) else {}
        requester_id = requester.get("declared_id") or user_id or None
        subject_value = (
            subject.get("declared_id") or subject_id or requester_id or None
        )
        return {
            "requester_id": (
                requester_id
                if isinstance(requester_id, str) and requester_id else None
            ),
            "subject_id": (
                subject_value
                if isinstance(subject_value, str) and subject_value else None
            ),
            "authentication_status": (
                requester.get("authentication_status")
                or "IDENTITY_UNAUTHENTICATED"
            ),
            "identity_status": (
                requester.get("identity_status")
                or "IDENTITY_UNAUTHENTICATED"
            ),
            "authority_basis": requester.get("authority_basis"),
        }

    @staticmethod
    def _history_payload(result: Dict[str, Any], user_input: str | None) -> dict:
        policy = result.get("policy_result") or {}
        provenance = result.get("policy_provenance") or {}
        execution = result.get("execution") or {}
        cortex_meta = result.get("cortex_meta") or {}
        memory_meta = result.get("memory_meta") or {}
        stress = result.get("stress_level") or {}
        response = result.get("response")
        return {
            "policy": {
                "level": policy.get("policy_level"),
                "action": policy.get("action"),
                "is_reincident": policy.get("is_reincident"),
                "history_status": policy.get("history_status"),
                "evaluation_id": provenance.get("evaluation_id"),
                "engine_id": provenance.get("engine_id"),
            },
            "authorization": {
                "decision": (result.get("authorization") or {}).get("decision"),
                "guard_status": result.get("guard_status"),
                "kernel_status": result.get("kernel_status"),
                "authorization_complete": result.get("authorization_complete"),
                "policy_evaluated": (result.get("authorization") or {}).get(
                    "policy_evaluated"
                ),
            },
            "execution": {
                "status": execution.get("status"),
                "action_executed": bool(execution.get("action_executed", False)),
            },
            "cortex": {
                "status": result.get("cortex_status"),
                "requested_mode": cortex_meta.get("requested_mode"),
                "effective_mode": cortex_meta.get("effective_mode"),
                "provider": cortex_meta.get("provider"),
                "model": cortex_meta.get("model"),
                "attempt": cortex_meta.get("attempt"),
                "fallback_used": bool(cortex_meta.get("fallback_used", False)),
                "failover_used": bool(cortex_meta.get("failover_used", False)),
                "response_chars": len(response) if isinstance(response, str) else 0,
            },
            "memory": {
                "status": result.get("memory_status"),
                "memory_id": memory_meta.get("memory_id"),
                "similarity": memory_meta.get("similarity"),
            },
            "state": {
                "emotional_state": result.get("emotional_state"),
                "stress_percent": stress.get("value"),
                "system_state": result.get("system_state"),
            },
            "processing_time_ms": result.get("processing_time_ms"),
            "user_input_chars": len(user_input) if isinstance(user_input, str) else 0,
        }

    def _attach_interaction_history(
        self,
        result: Dict[str, Any],
        *,
        user_id: str,
        threat_type: str,
        action: str,
        target: str | None,
        intent: str | None,
        subject_id: str | None,
        user_input: str | None,
    ) -> Dict[str, Any]:
        if self.history_store is None or not isinstance(result, dict):
            return result
        request_id = result.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return result
        event_type = self._history_event_type(result)
        identity = self._history_identity(result, user_id, subject_id)
        execution = result.get("execution") or {}
        try:
            append_result = self.history_store.append(
                HistoryEvent(
                    event_type=event_type,
                    request_id=request_id,
                    payload=self._history_payload(result, user_input),
                    requester_id=identity["requester_id"],
                    subject_id=identity["subject_id"],
                    authentication_status=identity["authentication_status"],
                    identity_status=identity["identity_status"],
                    authority_basis=identity["authority_basis"],
                    threat_type=threat_type or None,
                    action=action or None,
                    target_chars=len(target) if isinstance(target, str) else None,
                    intent_chars=len(intent) if isinstance(intent, str) else None,
                    authorization_status=result.get("authorization_status"),
                    execution_status=execution.get("status") or EXECUTION_NOT_EXECUTED,
                    cortex_status=result.get("cortex_status") or "CORTEX_NOT_CALLED",
                    system_state=result.get("system_state"),
                ),
                idempotency_key=f"{request_id}:{event_type.value}",
            )
        except Exception as error:
            append_result = AppendResult(
                PersistenceStatus.WRITE_FAILED,
                None,
                None,
                "WRITE_FAILED",
                f"{type(error).__name__}: {error}",
                False,
            )
        completeness = (
            AuditCompleteness.COMPLETE
            if append_result.status in (
                PersistenceStatus.RECORDED, PersistenceStatus.DUPLICATE
            )
            else AuditCompleteness.INCOMPLETE
        )
        stored = append_result.stored_record
        updated = dict(result)
        updated["persistence"] = {
            "status": append_result.status.value,
            "record_id": stored.record_id if stored else None,
            "request_id": request_id,
            "sequence": stored.sequence if stored else None,
            "audit_completeness": completeness.value,
            "error_code": append_result.error_code,
        }
        updated["audit_completeness"] = completeness.value
        return updated

    def _attach_break_glass_history(
        self,
        result: Dict[str, Any],
        *,
        user_id: str,
        subject_id: str | None,
    ) -> Dict[str, Any]:
        if self.history_store is None or not isinstance(result, dict):
            return result
        request_id = result.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return result
        identity = self._history_identity(result, user_id, subject_id)
        payload = {
            "break_glass": {
                "status": result.get("break_glass_status"),
                "authorized": bool(result.get("authorized", False)),
                "evidence_authorized": bool(result.get("evidence_authorized", False)),
                "operation_authorized": bool(
                    result.get("operation_authorized", False)
                ),
                "authorization_complete": bool(
                    result.get("authorization_complete", False)
                ),
            },
            "state": {"system_state": result.get("system_state")},
        }
        try:
            append_result = self.history_store.append(
                HistoryEvent(
                    event_type=EventType.BREAK_GLASS,
                    request_id=request_id,
                    payload=payload,
                    requester_id=identity["requester_id"],
                    subject_id=identity["subject_id"],
                    authentication_status=identity["authentication_status"],
                    identity_status=identity["identity_status"],
                    authority_basis=identity["authority_basis"],
                    threat_type="emergency",
                    action=None,
                    authorization_status=result.get("authorization_status"),
                    execution_status=EXECUTION_NOT_EXECUTED,
                    cortex_status="CORTEX_NOT_CALLED",
                    system_state=result.get("system_state") or "BREAK_GLASS",
                ),
                idempotency_key=f"{request_id}:{EventType.BREAK_GLASS.value}",
            )
        except Exception as error:
            append_result = AppendResult(
                PersistenceStatus.WRITE_FAILED,
                None,
                None,
                "WRITE_FAILED",
                f"{type(error).__name__}: {error}",
                False,
            )
        completeness = (
            AuditCompleteness.COMPLETE
            if append_result.status in (
                PersistenceStatus.RECORDED, PersistenceStatus.DUPLICATE
            )
            else AuditCompleteness.INCOMPLETE
        )
        stored = append_result.stored_record
        updated = dict(result)
        updated["persistence"] = {
            "status": append_result.status.value,
            "record_id": stored.record_id if stored else None,
            "request_id": request_id,
            "sequence": stored.sequence if stored else None,
            "audit_completeness": completeness.value,
            "error_code": append_result.error_code,
        }
        updated["audit_completeness"] = completeness.value
        return updated

    @_serialized_motor_state
    def process_interaction(
        self,
        user_id: str,
        threat_type: str,
        user_input: str = None,
        system_prompt: str = "",
        action: str = "read",
        target: str = None,
        intent: str = None,
        from_majority_vote: bool = False,
        subject_id: str = None,
        request_id: str = None,
    ) -> Dict[str, Any]:
        result = self._process_interaction_impl(
            user_id=user_id,
            threat_type=threat_type,
            user_input=user_input,
            system_prompt=system_prompt,
            action=action,
            target=target,
            intent=intent,
            from_majority_vote=from_majority_vote,
            subject_id=subject_id,
            request_id=request_id,
        )
        return self._attach_interaction_history(
            result,
            user_id=user_id,
            threat_type=threat_type,
            action=action,
            target=target,
            intent=intent,
            subject_id=subject_id,
            user_input=user_input,
        )

    def _process_interaction_impl(
        self,
        user_id: str,
        threat_type: str,
        user_input: str = None,
        system_prompt: str = "",
        action: str = "read",
        target: str = None,
        intent: str = None,
        from_majority_vote: bool = False,
        subject_id: str = None,
        request_id: str = None,
    ) -> Dict[str, Any]:
        """Processar uma interação usuário-sistema.

        Esta é o fluxo principal: entrada → validação → identidade declarada →
        política → AUTORIZAÇÃO (Hard Block + Kernel + Policy) → córtex →
        resposta.

        A política pode bloquear `create/update/delete` no nível 2
        (`read_only`) e pode invalidar um `delete` cujo limiar não chegue ao
        Hard Block. Ela nunca libera uma negação de Hard Block/Kernel.

        `user_id` é o **solicitante declarado**. `subject_id` é o sujeito
        afetado; se omitido, é o próprio solicitante. Nenhum dos dois é
        autenticado; o resultado registra `IDENTITY_UNAUTHENTICATED`. Não há
        autenticação HTTP ou multiusuário neste repositório.

        Args:
            user_id: Identificador declarado do solicitante.
            threat_type: Tipo de ameaça/gatilho.
            user_input: Entrada do usuário (texto).
            system_prompt: Prompt do sistema base.
            action: Tipo de ação CRUD ("create", "read", "update", "delete").
            target: Alvo da ação. Obrigatório para create/update/delete.
            intent: Intenção declarada. Obrigatória para create/update/delete.
            from_majority_vote: Registrado no veredito do Kernel; nunca
                sobrescreve uma proibição de Ring 0.
            subject_id: Identidade declarada do sujeito afetado. Opcional.
            request_id: Identificador de correlação. Se omitido, é gerado.

        Returns:
            Dict com resposta completa, estado do sistema e decisão de
            autorização auditável.

        Raises:
            Nada por falha do Guarda-Costas/Policy Engine: a autorização é
            fail-closed e retorna um resultado bloqueado.
        """
        t0 = time.time()
        if self._shutting_down:
            raise MotorShuttingDown("motor em encerramento")

        identity = build_identity_context(user_id, subject_id=subject_id)
        request_id_value = request_id if request_id is not None else new_request_id()

        validation = _validate_interaction_inputs(
            user_id=user_id,
            threat_type=threat_type,
            user_input=user_input,
            system_prompt=system_prompt,
            action=action,
            target=target,
            intent=intent,
            from_majority_vote=from_majority_vote,
            subject_id=subject_id,
            request_id=request_id,
        )
        if validation:
            return self._invalid_input_result(
                validation,
                t0,
                identity=identity,
                request_id_value=request_id_value,
                action=action,
                target=target,
                intent=intent,
                threat_type=threat_type,
            )

        # Stage 1: Atualizar fígado - processar gatilhos de memória
        # (O sistema acumula estresse naturalmente + gatilhos)
        self.virtual_liver.add_memory_trigger(f"interacao_{user_id}", stress=5.0)

        # Stage 2: Policy Engine - avaliar nível de resposta.
        # OS115: a avaliação já nasce vinculada ao request_id, ao sujeito e à
        # ação que a autorização irá decidir.
        try:
            policy_result = self.policy_engine.evaluate(
                user_id,
                threat_type,
                request_id=request_id_value,
                subject_id=subject_id,
                action=action,
            )
        except Exception as error:
            return self._policy_failure_result(
                error,
                t0,
                identity=identity,
                request_id_value=request_id_value,
                action=action,
                target=target,
                intent=intent,
                threat_type=threat_type,
            )
        stress_pct_early = policy_result["stress_percent"]

        # Stage 2.5: AUTORIZAÇÃO CENTRAL - Hard Block (OS099) + Kernel (OS100)
        # Roda ANTES do córtex. O Hard Block é a primeira barreira (entropia),
        # o Kernel é a barreira constitucional. Os dois precisam autorizar.
        memory_reincidence = policy_result.get("is_reincident")
        if memory_reincidence is True or memory_reincidence is False:
            authorization_reincidence = memory_reincidence
            reincidence_basis = "MEMORY_FACT"
        elif memory_reincidence is None:
            # Falha/indisponibilidade de memória: não é prova de ausência.
            # Para o Hard Block, adotamos o valor conservador True (limiar
            # reduzido); o resultado continua expondo history_status.
            authorization_reincidence = True
            reincidence_basis = "MEMORY_UNKNOWN_CONSERVATIVE"
        else:
            authorization_reincidence = True
            reincidence_basis = "MEMORY_INVALID_CONSERVATIVE"

        # OS115: não mutar `policy_result` depois da emissão. O valor usado
        # pelo Hard Block permanece local e a base é registrada no contrato de
        # autorização. Alterar o payload emitido invalidaria o digest.

        auth = None
        try:
            auth = guarda_costas.authorize_action(
                action=action,
                stress_level=stress_pct_early,
                is_reincident=authorization_reincidence,
                user_id=user_id,
                target=target,
                intent=intent,
                from_majority_vote=from_majority_vote,
                policy_result=policy_result,
                subject_id=subject_id,
                request_id=request_id_value,
                expected_policy_engine_id=self.policy_engine.engine_id,
            )
        except Exception as error:
            # Exceção durante a autorização nunca vira permissão.
            auth = {
                "allowed": False,
                "blocked_by": "guard_internal_error",
                "guard_status": "GUARD_INTERNAL_ERROR",
                "kernel_status": "KERNEL_NOT_EVALUATED",
                "kernel": None,
                "hard_block": {},
                "policy_controls": None,
                "policy_evaluated": False,
                "reasoning": (
                    "FAIL-CLOSED (GUARD_INTERNAL_ERROR): "
                    f"{type(error).__name__}: {error}"
                ),
            }
        hb = auth.get("hard_block") or {}
        kernel = auth.get("kernel")
        guard_status = auth.get("guard_status") or "GUARD_PROTOCOL_ERROR"
        kernel_status = auth.get("kernel_status") or "KERNEL_ERROR"
        auth_policy_controls = auth.get("policy_controls")
        auth_policy_evaluated = bool(auth.get("policy_evaluated"))
        auth_policy_provenance = auth.get("policy_provenance")

        if guard_status != "GUARD_OK":
            print(
                f"[Guarda-Costas] {guard_status}: operação bloqueada por "
                "fail-closed (sem autorização válida)."
            )
        elif kernel_status != "KERNEL_ALLOW":
            print(
                f"[Kernel] {kernel_status}: operação bloqueada antes do córtex."
            )

        # Fail-closed: SOMENTE `allowed is True` autoriza. Ausência do campo,
        # None, False, string "true" ou qualquer outro tipo bloqueiam.
        if auth.get("allowed") is not True:
            # Ação BARRADA pelo Hard Block, Kernel, política ou fail-closed.
            processing_time = time.time() - t0
            blocked_by = auth.get("blocked_by") or "guard_unavailable"
            if blocked_by in ("policy_provenance_error", "policy_internal_error"):
                # Falha de validação/controles não é negação de política:
                # o mecanismo de política ficou indisponível.
                system_state = "POLICY_INDISPONIVEL"
            elif str(blocked_by).startswith("policy_"):
                system_state = (
                    "POLICY_READ_ONLY"
                    if blocked_by == "policy_read_only"
                    else "POLICY_BLOQUEIO"
                )
            elif guard_status != "GUARD_OK":
                system_state = "GUARD_INDISPONIVEL"
            elif kernel_status == "KERNEL_DENY":
                system_state = "KERNEL_BLOCK_ATIVO"
            elif kernel_status == "KERNEL_REVIEW":
                system_state = "KERNEL_REVISAO"
            elif kernel_status == "KERNEL_UNAVAILABLE":
                system_state = "KERNEL_INDISPONIVEL"
            elif kernel_status in ("KERNEL_INVALID_INPUT", "KERNEL_ERROR"):
                system_state = "KERNEL_BLOQUEADO"
            else:
                system_state = "HARD_BLOCK_ATIVO"

            if isinstance(auth_policy_controls, dict):
                policy_controls = auth_policy_controls
            else:
                policy_controls = _build_policy_controls(
                    policy_result, action, hb, enforced=False
                )
            # Preservar a classificação específica de `authorize_action`
            # (ex.: INFRASTRUCTURE_FAILURE em falha de proveniência/controles).
            # A derivação local é apenas fallback para mocks antigos.
            decision = auth.get("authorization_status")
            decision_reason = auth.get("decision_reason")
            if decision is None:
                decision, decision_reason = derive_authorization_status(
                    identity=identity,
                    hard_block=hb,
                    kernel=kernel,
                    policy_controls=policy_controls,
                    policy_evaluated=auth_policy_evaluated,
                )
            record = self._authorization_record(
                request_id_value=request_id_value,
                identity=identity,
                action=action,
                target=target,
                intent=intent,
                threat_type=threat_type,
                hard_block=hb,
                kernel=kernel,
                policy_controls=policy_controls,
                decision=decision,
                decision_reason=decision_reason,
                policy_evaluated=auth_policy_evaluated,
                complete=auth_policy_evaluated,
                execution_status=EXECUTION_NOT_EXECUTED,
                execution_detail=(
                    "Hard Block/Kernel/Policy negaram ou não puderam decidir; "
                    "Córtex não foi chamado."
                ),
                reincidence_basis=reincidence_basis,
                policy_provenance=auth_policy_provenance,
            )
            authorization = {
                "guard_status": guard_status,
                "kernel_status": kernel_status,
                "kernel": kernel,
                "hard_block": hb,
                "reincidence_input": authorization_reincidence,
                "reincidence_basis": reincidence_basis,
            }
            authorization.update(record)
            authorization["authorization_status"] = record["decision"]
            blocked_result = {
                "request_id": request_id_value,
                "response": None,
                "blocked": True,
                "blocked_by": blocked_by,
                "guard_status": guard_status,
                "kernel_status": kernel_status,
                "reasoning": auth.get("reasoning") or hb.get("reasoning"),
                "policy_result": policy_result,
                "policy_controls": policy_controls,
                "policy_provenance": auth_policy_provenance,
                "emotional_state": {
                    "valencia": float(self.emotional_matrix.get_state()[0]),
                    "energia": float(self.emotional_matrix.get_state()[1]),
                    "previsibilidade": float(self.emotional_matrix.get_state()[2]),
                },
                "stress_level": {
                    "value": stress_pct_early,
                    "level": policy_result["policy_level"],
                    "action": policy_result["action"],
                },
                "guarda_costas": hb,
                "kernel": kernel,
                "authorization": authorization,
                "authorization_status": record["decision"],
                "authorization_complete": auth_policy_evaluated,
                "execution": record["execution"],
                "cortex_status": "CORTEX_NOT_CALLED",
                "cortex_meta": {},
                "policy_memory_status": policy_result.get("history_status"),
                "policy_memory_error": policy_result.get("history_error"),
                "policy_reincidence": policy_result.get("is_reincident"),
                "policy_reincidence_unknown": policy_result.get(
                    "reincidence_unknown"
                ),
                "policy_history_similarity": policy_result.get(
                    "history_similarity"
                ),
                "reincidence_basis": reincidence_basis,
                "processing_time_ms": round(processing_time * 1000, 2),
                "system_state": system_state,
            }
            self.dashboard.record_interaction(
                emotional_state={
                    "valencia": self.emotional_matrix.get_state()[0],
                    "energia": self.emotional_matrix.get_state()[1],
                    "previsibilidade": self.emotional_matrix.get_state()[2],
                },
                stress_level=stress_pct_early,
                policy_level=policy_result["policy_level"],
                policy_action=f"[AUTORIZAÇÃO] {auth.get('reasoning', 'Bloqueado')}",
            )
            self.current_system_state = system_state
            return blocked_result

        # Stage 2.6: Aplicar restrições da política que têm contrato definido.
        # A política só pode restringir; ela nunca converte uma negação do
        # Hard Block/Kernel em autorização. Quando `authorize_action()` já
        # avaliou a política, usamos o mesmo resultado para não criar uma
        # segunda lógica divergente. O fallback existe apenas para mocks
        # antigos que não devolvem `policy_controls`.
        if isinstance(auth_policy_controls, dict):
            policy_controls = auth_policy_controls
        else:
            policy_controls = _build_policy_controls(
                policy_result, action, hb, enforced=True
            )
        if policy_controls.get("blocked_by_policy"):
            processing_time = time.time() - t0
            policy_reason = policy_controls["blocked_by_policy"]
            system_state = (
                "POLICY_READ_ONLY"
                if policy_reason == "policy_read_only"
                else "POLICY_BLOQUEIO"
            )
            decision = AUTHORIZATION_DENIED
            decision_reason = f"Policy negou: {policy_reason}"
            record = self._authorization_record(
                request_id_value=request_id_value,
                identity=identity,
                action=action,
                target=target,
                intent=intent,
                threat_type=threat_type,
                hard_block=hb,
                kernel=kernel,
                policy_controls=policy_controls,
                decision=decision,
                decision_reason=decision_reason,
                policy_evaluated=True,
                complete=True,
                execution_status=EXECUTION_NOT_EXECUTED,
                execution_detail=(
                    "Policy negou a operação após Hard Block/Kernel; Córtex "
                    "não foi chamado."
                ),
                reincidence_basis=reincidence_basis,
                policy_provenance=auth_policy_provenance,
            )
            authorization = {
                "guard_status": guard_status,
                "kernel_status": kernel_status,
                "kernel": kernel,
                "hard_block": hb,
                "reincidence_input": authorization_reincidence,
                "reincidence_basis": reincidence_basis,
            }
            authorization.update(record)
            authorization["authorization_status"] = record["decision"]
            policy_blocked_result = {
                "request_id": request_id_value,
                "response": None,
                "blocked": True,
                "blocked_by": policy_reason,
                "guard_status": guard_status,
                "kernel_status": kernel_status,
                "reasoning": (
                    f"POLÍTICA ({policy_reason}): nível "
                    f"{policy_result['policy_level']} - "
                    f"{policy_result['action']}"
                ),
                "emotional_state": {
                    "valencia": float(self.emotional_matrix.get_state()[0]),
                    "energia": float(self.emotional_matrix.get_state()[1]),
                    "previsibilidade": float(self.emotional_matrix.get_state()[2]),
                },
                "stress_level": {
                    "value": stress_pct_early,
                    "level": policy_result["policy_level"],
                    "action": policy_result["action"],
                },
                "guarda_costas": hb,
                "kernel": kernel,
                "authorization": authorization,
                "authorization_status": record["decision"],
                "authorization_complete": True,
                "execution": record["execution"],
                "policy_result": policy_result,
                "policy_controls": policy_controls,
                "policy_provenance": auth_policy_provenance,
                "cortex_status": "CORTEX_NOT_CALLED",
                "cortex_meta": {},
                "policy_memory_status": policy_result.get("history_status"),
                "policy_memory_error": policy_result.get("history_error"),
                "policy_reincidence": policy_result.get("is_reincident"),
                "policy_reincidence_unknown": policy_result.get(
                    "reincidence_unknown"
                ),
                "policy_history_similarity": policy_result.get(
                    "history_similarity"
                ),
                "reincidence_basis": reincidence_basis,
                "processing_time_ms": round(processing_time * 1000, 2),
                "system_state": system_state,
            }
            self.dashboard.record_interaction(
                emotional_state={
                    "valencia": self.emotional_matrix.get_state()[0],
                    "energia": self.emotional_matrix.get_state()[1],
                    "previsibilidade": self.emotional_matrix.get_state()[2],
                },
                stress_level=stress_pct_early,
                policy_level=policy_result["policy_level"],
                policy_action=f"[POLÍTICA] {policy_controls['blocked_by_policy']}",
            )
            self.current_system_state = system_state
            return policy_blocked_result

        # Stage 3: Atualizar matriz emocional baseada na política
        # Mapear nível de política para estado emocional
        stress_pct = policy_result["stress_percent"]
        if stress_pct > 95:
            new_emotional_state = self.emotional_matrix.classify(
                valencia=-0.8,  # Negativa em crise
                energia=1.0,    # Alta energia/agitação
                previsibilidade=0.1  # Baixa previsibilidade (caos)
            )
        elif stress_pct > 75:
            new_emotional_state = self.emotional_matrix.classify(
                valencia=-0.5,
                energia=0.7,
                previsibilidade=0.3
            )
        elif stress_pct > 60:
            new_emotional_state = self.emotional_matrix.classify(
                valencia=-0.3,
                energia=0.4,
                previsibilidade=0.5
            )
        else:
            new_emotional_state = self.emotional_matrix.classify(
                valencia=0.2,
                energia=0.3,
                previsibilidade=0.7
            )

        # Atualizar matriz emocional do sistema
        self.emotional_matrix.classify(
            new_emotional_state[0], new_emotional_state[1], new_emotional_state[2]
        )

        # Stage 4: Cortex Pre-Frontal - gerar resposta baseada no estado
        # (Hard Block e Kernel já aprovaram a ação no Stage 2.5 - o córtex só
        # é chamado depois dos dois veredictos de segurança)
        mem_bridge = self.memory_bridge.build_context("policy_engine", user_id, threat_type)

        cortex_kwargs = {
            "emotional_state": {
                "valencia": self.emotional_matrix.get_state()[0],
                "energia": self.emotional_matrix.get_state()[1],
                "previsibilidade": self.emotional_matrix.get_state()[2],
            },
            "stress_level": stress_pct,
            "policy_level": policy_result["policy_level"],
            "policy_action": policy_result["action"],
            "user_context": {
                "user_id": user_id,
                "threat_type": threat_type,
                "interaction_count": len(self.interaction_history),
                "user_message": user_input or "",
                "memory_context": mem_bridge["formatted_context"],
                "memory_status": mem_bridge["retrieval_status"],
                "memory_ok": mem_bridge["retrieval_ok"],
                "memory_success": mem_bridge["retrieval_success"],
                "memory_error": mem_bridge["retrieval_error"],
            },
            "system_prompt": system_prompt,
        }
        try:
            if hasattr(self.cortex, "generate_response_result"):
                cortex_coro = self.cortex.generate_response_result(**cortex_kwargs)
            else:
                # Compatibilidade com Córtex/fakes antigos que só implementam
                # generate_response(); o resultado é tratado como texto legado.
                cortex_coro = self.cortex.generate_response(**cortex_kwargs)
            raw_cortex = _run_coroutine_sync(cortex_coro)
        except Exception as error:
            # Falha do Córtex é estado explícito, nunca resposta válida nem
            # motivo para reexecutar a corrotina/consumir a API duas vezes.
            raw_cortex = {
                "status": CORTEX_INTERNAL_ERROR,
                "response": None,
                "requested_mode": "unknown",
                "effective_mode": "none",
                "provider": None,
                "model": None,
                "model_served": None,
                "attempt": 0,
                "failover_used": False,
                "fallback_used": False,
                "error": f"falha ao executar o Córtex: {type(error).__name__}: {error}",
                "http_status": None,
            }

        if isinstance(raw_cortex, dict) and "status" in raw_cortex:
            cortex_status = raw_cortex.get("status") or CORTEX_INTERNAL_ERROR
            cortex_response = raw_cortex.get("response")
            cortex_meta = {
                key: value
                for key, value in raw_cortex.items()
                if key != "response"
            }
            if cortex_status not in CORTEX_STATUSES:
                cortex_status = CORTEX_INTERNAL_ERROR
                cortex_meta["error"] = "status de Córtex desconhecido"
            if not isinstance(cortex_response, str):
                cortex_response = None
        elif isinstance(raw_cortex, dict):
            cortex_status = CORTEX_INVALID_RESPONSE
            cortex_response = None
            cortex_meta = {
                key: value
                for key, value in raw_cortex.items()
                if key != "response"
            }
            cortex_meta["error"] = "resultado do Córtex sem status"
        else:
            cortex_response = raw_cortex if isinstance(raw_cortex, str) else None
            if isinstance(raw_cortex, str) and raw_cortex.strip():
                cortex_status = CORTEX_OK
            else:
                cortex_status = CORTEX_EMPTY_RESPONSE
            cortex_meta = dict(
                getattr(self.cortex, "last_execution_meta", {}) or {}
            )
            cortex_meta.setdefault("status", cortex_status)
            cortex_meta.setdefault("requested_mode", "unknown")
            cortex_meta.setdefault("effective_mode", "unknown")
            cortex_meta.setdefault(
                "error",
                None if cortex_status == CORTEX_OK else "resposta ausente",
            )

        if cortex_status == CORTEX_OK:
            self.current_system_state = "OPERACIONAL"
        elif cortex_status == CORTEX_TRUNCATED:
            self.current_system_state = "CORTEX_RESPOSTA_INCOMPLETA"
        else:
            self.current_system_state = "CORTEX_INDISPONIVEL"

        # Stage 5: Atualizar dashboard
        self.dashboard.record_interaction(
            emotional_state={
                "valencia": self.emotional_matrix.get_state()[0],
                "energia": self.emotional_matrix.get_state()[1],
                "previsibilidade": self.emotional_matrix.get_state()[2],
            },
            stress_level=stress_pct,
            policy_level=policy_result["policy_level"],
            policy_action=policy_result["action"],
        )
        self.dashboard.update_data(
            emotional_state={
                "valencia": self.emotional_matrix.get_state()[0],
                "energia": self.emotional_matrix.get_state()[1],
                "previsibilidade": self.emotional_matrix.get_state()[2],
            },
            stress_level=stress_pct,
            policy_level=policy_result["policy_level"],
        )

        # Stage 6: Registrar no histórico
        interaction_record = {
            "timestamp": time.time() - self.start_time,
            "user_id": user_id,
            "threat_type": threat_type,
            "stress_percent": stress_pct,
            "policy_level": policy_result["policy_level"],
            "policy_action": policy_result["action"],
            "emotional_state": {
                "valencia": self.emotional_matrix.get_state()[0],
                "energia": self.emotional_matrix.get_state()[1],
                "previsibilidade": self.emotional_matrix.get_state()[2],
            },
            "cortex_response": cortex_response[:100] if cortex_response else "—",
            "cortex_status": cortex_status,
        }
        self.interaction_history.append(interaction_record)

        # Finalizar cálculo de tempo
        processing_time = time.time() - t0

        # Decisão de autorização completa: Hard Block, Kernel e Policy
        # permitiram. A execução registrada é apenas a geração de resposta do
        # Córtex; não existe executor CRUD protegido neste repositório.
        execution_status = (
            EXECUTION_CORTEX_ONLY
            if cortex_status == CORTEX_OK
            else EXECUTION_NOT_EXECUTED
        )
        execution_detail = (
            "Hard Block, Kernel e Policy autorizaram; o Córtex gerou a "
            "resposta. Nenhuma operação CRUD protegida foi executada."
            if cortex_status == CORTEX_OK
            else (
                "Hard Block, Kernel e Policy autorizaram, mas o Córtex não "
                "produziu resposta. Nenhuma operação CRUD foi executada."
            )
        )
        auth_record = self._authorization_record(
            request_id_value=request_id_value,
            identity=identity,
            action=action,
            target=target,
            intent=intent,
            threat_type=threat_type,
            hard_block=hb,
            kernel=kernel,
            policy_controls=policy_controls,
            decision=AUTHORIZATION_AUTHORIZED,
            decision_reason=(
                "Hard Block, Kernel e Policy permitiram a operação."
            ),
            policy_evaluated=True,
            complete=True,
            execution_status=execution_status,
            execution_detail=execution_detail,
            reincidence_basis=reincidence_basis,
            policy_provenance=auth_policy_provenance,
        )
        authorization = {
            "guard_status": guard_status,
            "kernel_status": kernel_status,
            "kernel": kernel,
            "hard_block": hb,
            "reincidence_input": authorization_reincidence,
            "reincidence_basis": reincidence_basis,
        }
        authorization.update(auth_record)
        authorization["authorization_status"] = auth_record["decision"]

        # Montar resultado final
        result = {
            "request_id": request_id_value,
            "response": cortex_response,
            "cortex_status": cortex_status,
            "cortex_ok": cortex_status == CORTEX_OK,
            "cortex_error": cortex_meta.get("error"),
            "cortex_requested_mode": cortex_meta.get("requested_mode"),
            "cortex_effective_mode": cortex_meta.get("effective_mode"),
            "cortex_fallback_used": cortex_meta.get("fallback_used", False),
            "emotional_state": {
                "valencia": float(self.emotional_matrix.get_state()[0]),
                "energia": float(self.emotional_matrix.get_state()[1]),
                "previsibilidade": float(self.emotional_matrix.get_state()[2]),
            },
            "stress_level": {
                "value": stress_pct,
                "level": policy_result["policy_level"],
                "action": policy_result["action"],
            },
            "policy_result": policy_result,
            "policy_controls": policy_controls,
            "policy_provenance": auth_policy_provenance,
            "authorization": authorization,
            "authorization_status": auth_record["decision"],
            "authorization_complete": True,
            "execution": auth_record["execution"],
            "memory_status": mem_bridge["retrieval_status"],
            "policy_memory_status": policy_result.get("history_status"),
            "policy_memory_error": policy_result.get("history_error"),
            "reincidence_basis": reincidence_basis,
            "processing_time_ms": round(processing_time * 1000, 2),
            "system_state": self.current_system_state,
            # Metadados de infraestrutura (OS021 §9) — nunca contém credenciais.
            "cortex_meta": cortex_meta,
            # Metadados de recuperação de memória (OS022/OS102) — auditáveis e
            # sem conteúdo sensível. Estados distinguem ausência de falha.
            "memory_meta": {
                "retrieval_ok": mem_bridge["retrieval_ok"],
                "retrieval_success": mem_bridge["retrieval_success"],
                "retrieval_status": mem_bridge["retrieval_status"],
                "retrieval_error": mem_bridge["retrieval_error"],
                "collection": mem_bridge["collection"],
                "persistent": mem_bridge["persistent"],
                "memory_id": mem_bridge["memory_id"],
                "similarity": mem_bridge["similarity"],
                "distance": mem_bridge["distance"],
                "eligible_count": mem_bridge["eligible_count"],
                "candidate_count": mem_bridge["candidate_count"],
                "truncated": mem_bridge["truncated"],
                "candidates": [
                    {"id": r["id"], "similarity": r["similarity"],
                     "distance": r["distance"], "eligible": r["eligible"],
                     "integrity_status": r["integrity_status"],
                     "source": r["source"],
                     "memory_type": r["memory_type"],
                     "fallback": r.get("fallback", False)}
                    for r in mem_bridge["records"]
                ],
                "injected_chars": len(mem_bridge["formatted_context"]),
            },
        }

        return result

    def _snapshot_status(self) -> Dict[str, Any]:
        """Construir status atual; chamador deve segurar o lock."""
        stress = self.virtual_liver.get_stress_level()
        policy_status = self.policy_engine.get_status()
        return {
            "timestamp": time.time() - self.start_time,
            "system": {
                "current_stress": round(stress, 2),
                "stress_percent": min(round(stress / 100.0, 2) * 100, 100),
                "emotional_matrix": self.emotional_matrix.get_state(),
                "policy_level": policy_status["policy_active"],
            },
            "liver": self.virtual_liver.get_state(),
            "memory_stats": self.triangulation_memory.get_stats(),
        }

    @_serialized_motor_state
    def get_current_status(self) -> Dict[str, Any]:
        """Retornar status atual sob o lock; atualiza o snapshot cacheado."""
        snapshot = self._snapshot_status()
        snapshot["snapshot_status"] = "CURRENT"
        self._status_snapshot = copy.deepcopy(snapshot)
        return snapshot

    def get_status_snapshot(self) -> Dict[str, Any]:
        """Status não bloqueante para rotas/broadcast.

        Se o lock estiver livre, calcula um snapshot atual; se uma interação
        estiver em andamento, devolve o último snapshot completo com
        `snapshot_status="CACHED"`. Nunca espera o lock.
        """
        if self._state_lock.acquire(blocking=False):
            try:
                snapshot = self._snapshot_status()
                snapshot["snapshot_status"] = "CURRENT"
                self._status_snapshot = copy.deepcopy(snapshot)
                return snapshot
            finally:
                self._state_lock.release()
        if self._status_snapshot is not None:
            snapshot = copy.deepcopy(self._status_snapshot)
            snapshot["snapshot_status"] = "CACHED"
            return snapshot
        return {
            "snapshot_status": "UNAVAILABLE",
            "timestamp": None,
            "system": None,
            "liver": {},
            "memory_stats": {},
        }

    @_serialized_motor_state
    def add_stress(self, amount: float) -> None:
        """Injetar estresse sob o mesmo lock do motor."""
        if self._shutting_down:
            raise MotorShuttingDown("motor em encerramento")
        self.virtual_liver.add_stress(amount)

    async def _submit_serialized(self, method_name: str, **kwargs):
        if self._shutting_down:
            raise MotorShuttingDown("motor em encerramento")
        method = getattr(self, method_name)
        future = self._executor.submit(method, **kwargs)
        self._last_executor_future = future
        return await asyncio.wrap_future(future)

    async def process_interaction_async(self, **kwargs):
        """Executar process_interaction em fila serial (uma thread)."""
        return await self._submit_serialized("process_interaction", **kwargs)

    async def get_current_status_async(self):
        """Status completo na mesma fila serial do motor."""
        return await self._submit_serialized("get_current_status")

    async def add_stress_async(self, amount: float):
        """Injetar estresse na mesma fila serial do motor."""
        return await self._submit_serialized("add_stress", amount=amount)

    async def trigger_break_glass_async(self, **kwargs):
        """Executar trigger_break_glass em fila serial (uma thread)."""
        return await self._submit_serialized("trigger_break_glass", **kwargs)

    def begin_shutdown(self) -> None:
        """Recusar novas operações críticas antes do shutdown."""
        self._shutting_down = True

    async def shutdown_async(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Aguardar a operação atual e encerrar executor/Cortex.

        Se a operação não terminar no timeout, o executor é marcado para
        shutdown sem wait e o resultado informa `shutdown_complete=False`.
        """
        self.begin_shutdown()
        future = self._last_executor_future
        timed_out = False
        if future is not None and not future.done():
            try:
                await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
            except asyncio.TimeoutError:
                timed_out = True
            except Exception:
                pass

        if timed_out:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._shutdown_complete = False
            return {
                "shutdown_complete": False,
                "timed_out": True,
                "message": "operação ainda em andamento no timeout",
            }

        self._executor.shutdown(wait=True, cancel_futures=True)
        cortex_shutdown = None
        try:
            if hasattr(self.cortex, "shutdown"):
                cortex_shutdown = await asyncio.wait_for(
                    asyncio.to_thread(self.cortex.shutdown),
                    timeout=timeout,
                )
            self._shutdown_complete = True
        except Exception as error:
            self._shutdown_complete = False
            cortex_shutdown = {
                "error": f"{type(error).__name__}: {error}",
            }
        if self.history_store is not None:
            try:
                self.history_store.close()
            except Exception:
                pass
        return {
            "shutdown_complete": self._shutdown_complete,
            "timed_out": False,
            "cortex_shutdown": cortex_shutdown,
        }

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    @_serialized_motor_state
    def trigger_break_glass(
        self,
        user_id: str,
        camera_hash: str = None,
        audio_hash: str = None,
        gps_coords: str = None,
        justificativa: str = "Emergência não especificada",
        *,
        subject_id: str = None,
        event_id: str = None,
        request_id: str = None,
        emitter_id: str = None,
        timestamp_unix: int = None,
        nonce: str = None,
        key_id: str = None,
        camera_file: str = None,
        camera_media_type: str = None,
        camera_sha256: str = None,
        audio_file: str = None,
        audio_media_type: str = None,
        audio_sha256: str = None,
        signature_hmac_sha256: str = None,
    ) -> Dict[str, Any]:
        result = self._trigger_break_glass_impl(
            user_id=user_id,
            camera_hash=camera_hash,
            audio_hash=audio_hash,
            gps_coords=gps_coords,
            justificativa=justificativa,
            subject_id=subject_id,
            event_id=event_id,
            request_id=request_id,
            emitter_id=emitter_id,
            timestamp_unix=timestamp_unix,
            nonce=nonce,
            key_id=key_id,
            camera_file=camera_file,
            camera_media_type=camera_media_type,
            camera_sha256=camera_sha256,
            audio_file=audio_file,
            audio_media_type=audio_media_type,
            audio_sha256=audio_sha256,
            signature_hmac_sha256=signature_hmac_sha256,
        )
        return self._attach_break_glass_history(
            result, user_id=user_id, subject_id=subject_id
        )

    def _trigger_break_glass_impl(
        self,
        user_id: str,
        camera_hash: str = None,
        audio_hash: str = None,
        gps_coords: str = None,
        justificativa: str = "Emergência não especificada",
        *,
        subject_id: str = None,
        event_id: str = None,
        request_id: str = None,
        emitter_id: str = None,
        timestamp_unix: int = None,
        nonce: str = None,
        key_id: str = None,
        camera_file: str = None,
        camera_media_type: str = None,
        camera_sha256: str = None,
        audio_file: str = None,
        audio_media_type: str = None,
        audio_sha256: str = None,
        signature_hmac_sha256: str = None,
    ) -> Dict[str, Any]:
        """Avaliar uma solicitação de Break Glass com evidência verificável.

        A partir da OS101, a autorização exige arquivos reais de câmera e
        áudio, digests SHA-256, vínculo de evento/requisição/emissor, nonce,
        timestamp e assinatura HMAC-SHA256 produzida por um emissor confiável.
        Hashes declarados sozinhos não bastam.

        O Break Glass **não** libera o Hard Block nem o Kernel. Ele apenas
        valida e registra a evidência de emergência. A liberação de operação
        não é implementada nesta OS.

        Args:
            user_id: Identificador do usuário que aciona a emergência.
            camera_hash/audio_hash: Parâmetros legados; não são evidência no
                contrato OS101 e não autorizam.
            gps_coords: Metadado GPS "lat,lon"; não autenticado.
            justificativa: Texto da emergência.
            event_id/request_id/emitter_id: Vínculo da evidência.
            subject_id: Sujeito da emergência; padrão é `user_id`.
            timestamp_unix: Timestamp Unix da assinatura (±300s).
            nonce: Nonce único de 16 a 128 caracteres.
            key_id: Identificador da chave HMAC provisionada.
            camera_file/audio_file: Nomes simples no diretório de evidências.
            camera_media_type/audio_media_type: Tipo de mídia validado.
            camera_sha256/audio_sha256: SHA-256 declarado dos arquivos.
            signature_hmac_sha256: HMAC da serialização canônica.

        Returns:
            Dict com `policy_result`, `authorized`, `break_glass_status` e
            `break_glass`. Somente `authorized is True` representa evidência
            verificada; ainda assim, Hard Block e Kernel continuam valendo.
        """
        if self._shutting_down:
            raise MotorShuttingDown("motor em encerramento")
        identity = build_identity_context(user_id, subject_id=subject_id)
        request_id_value = request_id if request_id is not None else new_request_id()
        user_validation = _text_input_error(
            "user_id", user_id, _MAX_USER_ID_CHARS
        )
        request_validation = (
            _text_input_error("request_id", request_id, _MAX_REQUEST_ID_CHARS)
            if request_id is not None
            else None
        )
        if user_validation or request_validation or not identity.is_valid:
            reason = (
                user_validation
                or request_validation
                or identity.error
                or "identidade inválida"
            )
            invalid_field = (
                "user_id"
                if user_validation
                else "request_id"
                if request_validation
                else "subject_id"
            )
            evidence = build_evidence_record(
                request_id=request_id_value,
                identity=identity,
                event_id=event_id,
                emitter_id=emitter_id,
                subject_id=identity.subject_id,
                evidence_status="BREAK_GLASS_INVALID_INPUT",
                evidence_authorized=False,
                reason=reason,
            )
            self._record_authorization_audit(evidence)
            return {
                "request_id": request_id_value,
                "policy_result": None,
                "authorized": False,
                "evidence_authorized": False,
                "operation_authorized": False,
                "authorization_complete": False,
                "authorization_status": AUTHORIZATION_INPUT_INVALID,
                "authorization": evidence,
                "break_glass_status": "BREAK_GLASS_INVALID_INPUT",
                "validation": {
                    "status": "INPUT_INVALID",
                    "field": invalid_field,
                    "reason": reason,
                },
                "break_glass": {
                    "status": "error",
                    "autorizado": False,
                    "break_glass_status": "BREAK_GLASS_INVALID_INPUT",
                    "motivo_recusa": (
                        f"ENTRADA INVÁLIDA: {reason}"
                    ),
                },
            }

        try:
            policy_result = self.policy_engine.evaluate(user_id, "emergency")
        except Exception as error:
            reason = (
                "FALHA DO POLICY ENGINE (Break Glass): "
                f"{type(error).__name__}: {error}"
            )
            evidence = build_evidence_record(
                request_id=request_id_value,
                identity=identity,
                event_id=event_id,
                emitter_id=emitter_id,
                subject_id=identity.subject_id,
                evidence_status="BREAK_GLASS_POLICY_UNAVAILABLE",
                evidence_authorized=False,
                reason=reason,
            )
            self._record_authorization_audit(evidence)
            return {
                "request_id": request_id_value,
                "policy_result": None,
                "authorized": False,
                "evidence_authorized": False,
                "operation_authorized": False,
                "authorization_complete": False,
                "authorization_status": AUTHORIZATION_INFRASTRUCTURE_FAILURE,
                "authorization": evidence,
                "break_glass_status": "BREAK_GLASS_POLICY_UNAVAILABLE",
                "break_glass": {
                    "status": "error",
                    "autorizado": False,
                    "break_glass_status": "BREAK_GLASS_POLICY_UNAVAILABLE",
                    "motivo_recusa": reason,
                },
            }

        alibi = guarda_costas.break_glass(
            camera_hash=camera_hash,
            audio_hash=audio_hash,
            gps_coords=gps_coords,
            justificativa=justificativa,
            event_id=event_id,
            request_id=request_id,
            emitter_id=emitter_id,
            subject_id=identity.subject_id,
            timestamp_unix=timestamp_unix,
            nonce=nonce,
            key_id=key_id,
            camera_file=camera_file,
            camera_media_type=camera_media_type,
            camera_sha256=camera_sha256,
            audio_file=audio_file,
            audio_media_type=audio_media_type,
            audio_sha256=audio_sha256,
            signature_hmac_sha256=signature_hmac_sha256,
        )

        authorized = alibi.get("autorizado") is True
        status = alibi.get("break_glass_status") or "BREAK_GLASS_INTERNAL_ERROR"

        if authorized:
            # O estresse sobe apenas após evidência válida; tentativa inválida
            # não deve alterar o estado emocional do sistema.
            self.virtual_liver.add_stress(99.0)

        if authorized:
            acao_dashboard = "Break Glass AUTORIZADO - Máquina virou Testemunha"
        else:
            motivo = alibi.get("motivo_recusa") or "evidência inválida"
            acao_dashboard = f"Break Glass RECUSADO ({status}) - {motivo}"

        # Evidência autorizada NÃO é autorização de operação. Hard Block e
        # Kernel continuam valendo e nenhuma operação é executada aqui.
        if authorized:
            authorization_status = AUTHORIZATION_PARTIAL
            decision_reason = (
                "Evidência de Break Glass verificada; operação continua não "
                "autorizada e não executada."
            )
        elif status in (
            "BREAK_GLASS_UNAVAILABLE",
            "BREAK_GLASS_INTERNAL_ERROR",
            "BREAK_GLASS_AUTHENTICATION_UNAVAILABLE",
        ):
            authorization_status = AUTHORIZATION_INFRASTRUCTURE_FAILURE
            decision_reason = f"Break Glass indisponível/falhou: {status}"
        else:
            authorization_status = AUTHORIZATION_DENIED
            decision_reason = (
                alibi.get("motivo_recusa") or f"Break Glass recusado: {status}"
            )
        evidence = build_evidence_record(
            request_id=request_id_value,
            identity=identity,
            event_id=event_id,
            emitter_id=emitter_id,
            subject_id=identity.subject_id,
            evidence_status=status,
            evidence_authorized=authorized,
            reason=decision_reason,
        )
        evidence["authorization_status"] = authorization_status
        evidence["audit"] = self._record_authorization_audit(evidence)

        # Registrar no dashboard
        estado = self.emotional_matrix.get_state()
        self.dashboard.record_interaction(
            emotional_state={
                "valencia": float(estado[0]),
                "energia": float(estado[1]),
                "previsibilidade": float(estado[2]),
            },
            stress_level=99.0 if authorized else self.virtual_liver.get_stress_level(),
            policy_level=policy_result["policy_level"],
            policy_action=acao_dashboard,
        )

        return {
            "request_id": request_id_value,
            "policy_result": policy_result,
            "authorized": authorized,
            "evidence_authorized": authorized,
            "operation_authorized": False,
            "authorization_complete": False,
            "authorization_status": authorization_status,
            "authorization": evidence,
            "break_glass_status": status,
            "break_glass": alibi,
        }


# Instância global global
motor_sistema = None


def init_motor_emocional(
    cortex_use_local: bool = False,
    cortex_model_path: str = None,
    cortex_api_key: str = None,
    history_store: InteractionHistoryStore | None = None,
    **kwargs
) -> MotorEmocional:
    """Factory function para inicializar o motor global.

    A fábrica cria o store SQLite padrão quando nenhum store é fornecido.
    O caminho pode ser configurado por ``KAIROS_HISTORY_DB`` e fica fora do
    repositório por contrato.
    """
    global motor_sistema
    if history_store is None:
        history_store = create_default_history_store()
    motor_sistema = MotorEmocional(
        cortex_use_local=cortex_use_local,
        cortex_model_path=cortex_model_path,
        cortex_api_key=cortex_api_key,
        history_store=history_store,
        **kwargs,
    )
    return motor_sistema


def get_motor_emocional() -> MotorEmocional:
    """Getter para instância global do motor."""
    return motor_sistema