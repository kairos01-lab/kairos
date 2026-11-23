"""Policy Engine 2.0 - Degradação Graciosa com Limiares Dinâmicos.

O motor emocional não responde apenas Sim/Não. Ele tem "fases" de reação
baseadas no nível de estresse e no histórico do usuário (via Vector DB).
Isso cria imprevisibilidade controlada que dá ilusão de "vida" ao sistema.

OS115: `evaluate()` emite um resultado com proveniência registrada. Quando
recebe contexto de vinculação (`request_id`, `subject_id`, `action`), o
resultado só pode ser consumido pela autorização da mesma solicitação. Sem
contexto, o resultado é marcado `UNBOUND` e nunca autoriza.
"""
import uuid

from .authorization_contract import validate_identifier
from .policy_provenance import _issue_policy_result
from .virtual_liver import VirtualLiver
from .triangulation_memory import TriangulationMemory
from .memory_contract import (
    MEMORY_FOUND,
    MEMORY_INTEGRITY_FAILURE,
    MEMORY_INTERNAL_ERROR,
    MEMORY_INVALID_DATA,
    MEMORY_NOT_FOUND,
    MEMORY_OK,
    MEMORY_STATUSES,
    MEMORY_UNAVAILABLE,
    safe_error,
    status_from_exception,
    validate_similarity,
)


class PolicyEngine20:
    """Motor de políticas dinâmico com degradação graciosa.

    Em vez de bloqueios rígidos, o sistema tem "fases" de reação:
    - Nível 1 (Fadiva): 60-75% estresse - respostas reduzidas, latência aumentada
    - Nível 2 (Modo Testemunha): 76-95% estresse - somente leitura/ignore
    - Nível 3 (Break Glass): >95% estresse - corte de conexão com reincidente

    Contrato OS105:
    - `read_only=True` no nível 2 é uma restrição efetiva: o motor permite
      somente `action="read"`; `create`, `update` e `delete` são bloqueados
      pela política antes do Córtex.
    - `connection_cut` no nível 3 é calculado, mas o contrato existente não
      define qual conexão é afetada, quando, nem exceções. Ele permanece
      informativo e não é aplicado como corte de rede.
    - `adjusted_threshold` é derivado de `base_threshold * penalty` e, quando
      presente, é confrontado com o `effective_threshold` do Hard Block.
    """

    def __init__(self, liver: VirtualLiver, memory: TriangulationMemory,
                 reincident_threshold: float = 0.7, reincident_penalty: float = 0.7):
        """Inicializar Policy Engine.

        Args:
            liver: Instância do VirtualLiver (tem o estado de estresse atual)
            memory: Instância de TriangulationMemory (historico do usuario)
            reincident_threshold: Similaridade cosine para considerar usuario reincidente
            reincident_penalty: Multiplicador de limite para reincidentes (70% em vez de 95%)
        """
        self.liver = liver
        self.memory = memory
        # Identidade da instância para vinculação de proveniência (OS115).
        # Não é segredo nem credencial; distingue motores no mesmo processo.
        self.engine_id = f"policy_engine_{uuid.uuid4().hex}"
        self.reincident_threshold = validate_similarity(
            reincident_threshold, "reincident_threshold"
        )
        self.reincident_penalty = validate_similarity(
            reincident_penalty, "reincident_penalty"
        )
        if not 0.0 <= self.reincident_threshold <= 1.0:
            raise ValueError("reincident_threshold deve estar entre 0 e 1")
        if not 0.0 <= self.reincident_penalty <= 1.0:
            raise ValueError("reincident_penalty deve estar entre 0 e 1")

    def _get_user_history(self, user_id: str, threat_type: str) -> dict:
        """Consulta o histórico com estado explícito.

        Retorna `status`, `similarity` e `error`. Uma falha de memória **não**
        é convertida em similaridade 0.0; o chamador vê `MEMORY_UNAVAILABLE`
        (ou outro estado de falha) e `similarity=None`.
        """
        try:
            if hasattr(self.memory, "retrieve_with_status"):
                result = self.memory.retrieve_with_status(
                    system="policy_engine",
                    target=user_id,
                    threat=threat_type,
                    top_k=1,
                )
                if not isinstance(result, dict):
                    return {
                        "status": MEMORY_INVALID_DATA,
                        "similarity": None,
                        "error": "retrieve_with_status não devolveu objeto",
                    }
                status = result.get("status")
                if status not in MEMORY_STATUSES or status == MEMORY_OK:
                    return {
                        "status": MEMORY_INVALID_DATA,
                        "similarity": None,
                        "error": f"status inválido para recuperação: {status!r}",
                    }
                records = result.get("records") or []
                error = result.get("error")
            else:
                raw = self.memory.retrieve(
                    system="policy_engine",
                    target=user_id,
                    threat=threat_type,
                    top_k=1,
                )
                if not isinstance(raw, list):
                    return {
                        "status": MEMORY_INVALID_DATA,
                        "similarity": None,
                        "error": "retrieve devolveu tipo diferente de lista",
                    }
                status = MEMORY_FOUND if raw else MEMORY_NOT_FOUND
                records = raw
                error = None
        except Exception as exception:
            status = status_from_exception(exception)
            if status == MEMORY_INTERNAL_ERROR and not hasattr(
                self.memory, "retrieve_with_status"
            ):
                # Backends antigos só têm retrieve(); uma exceção genérica
                # nesse caminho é tratada como indisponibilidade, não como
                # dado interno confiável.
                status = MEMORY_UNAVAILABLE
            return {
                "status": status,
                "similarity": None,
                "error": safe_error(exception),
            }

        if status == MEMORY_NOT_FOUND:
            return {"status": MEMORY_NOT_FOUND, "similarity": None, "error": None}

        if status == MEMORY_FOUND:
            if not isinstance(records, list) or not records:
                return {
                    "status": MEMORY_INVALID_DATA,
                    "similarity": None,
                    "error": "MEMORY_FOUND sem registros",
                }
            first = records[0]
            if not isinstance(first, dict):
                return {
                    "status": MEMORY_INVALID_DATA,
                    "similarity": None,
                    "error": "registro de memória não é objeto",
                }
            memory = first.get("memory")
            if not isinstance(memory, dict) or not memory:
                # O contrato da OS102 exige envelope `memory` com integridade
                # e schema. Um backend não conforme não pode fornecer
                # similaridade "factual" sem registro verificável.
                return {
                    "status": MEMORY_INVALID_DATA,
                    "similarity": None,
                    "error": "MEMORY_FOUND sem envelope de memória verificável",
                }
            integrity_status = memory.get("integrity_status")
            schema_version = memory.get("schema_version")
            if integrity_status != "verified" or schema_version != 2:
                # Similaridade de registro legado/sem digest não pode
                # reduzir reincidência nem liberar decisão.
                return {
                    "status": MEMORY_INTEGRITY_FAILURE,
                    "similarity": None,
                    "error": "histórico sem integridade verificada",
                }
            try:
                similarity = validate_similarity(
                    first.get("similarity"), "similarity"
                )
            except Exception as exception:
                return {
                    "status": MEMORY_INVALID_DATA,
                    "similarity": None,
                    "error": safe_error(exception),
                }
            return {
                "status": MEMORY_FOUND,
                "similarity": similarity,
                "error": None,
            }

        # MEMORY_OK, MEMORY_UNAVAILABLE, TIMEOUT, INVALID_DATA, INTEGRITY,
        # STORAGE_ERROR, INTERNAL_ERROR.
        return {
            "status": status,
            "similarity": None,
            "error": error or "memória indisponível ou inválida",
        }

    def _get_user_similarity(self, user_id: str, threat_type: str) -> float:
        """Compatibilidade: similaridade ou `None` quando desconhecida.

        Não retorna 0.0 em falha. Código novo deve usar `_get_user_history`.
        """
        history = self._get_user_history(user_id, threat_type)
        if history["status"] == MEMORY_FOUND:
            return history["similarity"]
        return None

    def _is_reincident(self, user_id: str, threat_type: str):
        """`True`/`False` quando há fato; `None` quando a memória é incerta."""
        history = self._get_user_history(user_id, threat_type)
        if history["status"] == MEMORY_FOUND:
            return history["similarity"] >= self.reincident_threshold
        if history["status"] == MEMORY_NOT_FOUND:
            return False
        return None

    @staticmethod
    def _level_for_stress(stress_percent: float):
        """Nível e limiar base a partir do estresse normalizado 0..1.

        Fonte única para `evaluate()` e `get_status()`, evitando divergência
        entre a decisão e o status exibido.
        """
        if stress_percent > 0.95:
            return 3, 0.95
        if stress_percent > 0.76:
            return 2, 0.76
        if stress_percent > 0.60:
            return 1, 0.60
        return 0, 0.0

    def evaluate(
        self,
        user_id: str,
        threat_type: str,
        *,
        request_id: str = None,
        subject_id: str = None,
        action: str = None,
    ) -> dict:
        """Avaliar o nivel de resposta baseado em estresse e historico.

        Args:
            user_id: Identificador do usuario atual
            threat_type: Tipo de ameaca (ofensa verbal, spam, tentativa_perseguicao, etc)
            request_id: Identificador da solicitação que será autorizada.
            subject_id: Sujeito afetado; se omitido, é o próprio solicitante.
            action: Ação CRUD que a política deverá autorizar.

        O contexto de vinculação é opcional para inspeção direta, mas um
        resultado emitido sem ele é marcado `UNBOUND` e **nunca autoriza**.
        Se qualquer campo de vinculação for fornecido, `request_id` e `action`
        passam a ser obrigatórios; contexto incompleto é erro de avaliação,
        não compatibilidade.

        Returns:
            Dict com a decisao da policy, parametros aplicados e bloco
            `provenance` emitido pelo registro OS115.

        Raises:
            ValueError: se `user_id` ou `threat_type` não forem strings não
            vazias, ou se o contexto de vinculação estiver incompleto/inválido.
            O motor valida antes; esta checagem protege chamadas diretas e
            impede `threat_type` não hashável de chegar ao dicionário de ações.
        """
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id deve ser string não vazia")
        if not isinstance(threat_type, str) or not threat_type.strip():
            raise ValueError("threat_type deve ser string não vazia")

        binding_requested = any(
            value is not None for value in (request_id, subject_id, action)
        )
        normalized_subject = user_id if subject_id is None else subject_id
        if binding_requested:
            if request_id is None or action is None:
                raise ValueError(
                    "request_id e action são obrigatórios quando há contexto "
                    "de vinculação"
                )
            request_error = validate_identifier("request_id", request_id)
            if request_error is not None:
                raise ValueError(request_error)
            user_error = validate_identifier("user_id", user_id)
            if user_error is not None:
                raise ValueError(user_error)
            subject_error = validate_identifier("subject_id", normalized_subject)
            if subject_error is not None:
                raise ValueError(subject_error)
            if action not in ("create", "read", "update", "delete"):
                raise ValueError(
                    "action deve ser create, read, update ou delete"
                )

        stress_level = self.liver.get_stress_level()
        stress_percent = min(stress_level / 100.0, 1.0)  # Normalizar para 0-100%

        # Determinar nivel baseado em porcentagem de estresse
        level, base_threshold = self._level_for_stress(stress_percent)

        # Reincidência é factual somente se a memória respondeu com resultado.
        # Falha de memória => None (desconhecido), nunca False silencioso.
        history = self._get_user_history(user_id, threat_type)
        history_status = history["status"]
        if history_status == MEMORY_FOUND:
            is_reincident = history["similarity"] >= self.reincident_threshold
        elif history_status == MEMORY_NOT_FOUND:
            is_reincident = False
        else:
            is_reincident = None

        # Ajustar limite para reincidentes: 95% * 0,7 = 66,5%.
        # Apenas um fato True aplica o ajuste; None não vira permissão.
        if is_reincident is True and level >= 3:
            adjusted_threshold = base_threshold * self.reincident_penalty
            # Se o usuario e reincidente, o nivel sobe efectivamente
            # (o sistema fica mais sensivel)
            actual_level = min(level + 1, 3)
        else:
            adjusted_threshold = base_threshold
            actual_level = level

        # Aplicar politica de degradação graciosa
        result = {
            "stress_percent": round(stress_percent * 100, 2),
            "policy_level": actual_level,
            "base_threshold": base_threshold,
            "is_reincident": is_reincident,
            "history_status": history_status,
            "history_similarity": history.get("similarity"),
            "history_error": history.get("error"),
            "reincidence_unknown": is_reincident is None,
            "action": self._get_action(actual_level, threat_type),
            "modifiers": self._get_modifiers(actual_level, is_reincident),
        }

        # Aplicar o ajuste final se reincidente e no nivel 3
        if is_reincident is True and actual_level == 3:
            result["adjusted_threshold"] = round(adjusted_threshold * 100, 2)
            result["note"] = "Limite reduzido por historico de reincidencia"

        # OS115: a emissão é o único ponto que registra proveniência. Sem
        # contexto, o resultado é auditável mas não autorizável.
        return _issue_policy_result(
            engine_id=self.engine_id,
            payload=result,
            request_id=request_id if binding_requested else None,
            user_id=user_id,
            subject_id=normalized_subject,
            action=action if binding_requested else None,
            bound=binding_requested,
        )

    def _get_action(self, level: int, threat_type: str) -> str:
        """Retornar acao concreta baseada no nivel e tipo de ameaca.

        Args:
            level: Nivel da policy (0, 1, 2, 3)
            threat_type: Tipo de ameaca

        Returns:
            Descricao da acao a ser tomada
        """
        actions = {
            0: "Resposta normal - sistema operacional completo",
            1: "Modo Fadiga - respostas reduzidas, latencia aumentada",
            2: {
                "ofensa verbal": "Modo Testemunha - silencio relativo, tudo gravado para log",
                "spam": "Ignorar usuario por 5 minutos",
                "default": "Modo observador - respostas minimas"
            },
            3: {
                "ofensa verbal": "Break Glass - corte de conexao com geracao de alibi judicial",
                "spam": "Bloqueio temporario reforcado",
                "default": "Conexao cortada - protocolo emergencial"
            }
        }

        if level == 0:
            return actions[0]

        # Niveis 2 e 3
        level_actions = actions.get(level, {})
        if isinstance(level_actions, dict):
            return level_actions.get(threat_type, level_actions.get("default", "Acao padrao"))
        return level_actions

    def _get_modifiers(self, level: int, is_reincident):
        """Retornar modificadores de comportamento baseados no nivel e reincidencia.

        `read_only` tem semântica operacional no motor (somente `read`).
        `connection_cut` é apenas informativo nesta versão: falta contrato
        sobre escopo, direção e exceções de conectividade; o motor não corta
        rede com base nele.

        Args:
            level: Nivel da policy
            is_reincident: True/False/None (desconhecido por falha de memória)

        Returns:
            Dict com modificadores (latencia, comprimento, etc)
        """
        modifiers = {
            "latency_ms": 0,
            "max_words": None,
            "passive_aggressive": False,
            "read_only": False
        }

        if level == 0:
            # Operacao normal
            return modifiers

        if level == 1:
            # Nivel 1 - Fadiga
            modifiers.update({
                "latency_ms": 500,  # +500ms latencia proposital
                "max_words": 50,    # Limitar a 50 palavras
                "passive_aggressive": True
            })
            return modifiers

        if level == 2:
            # Nivel 2 - Modo Testemunha
            modifiers.update({
                "read_only": True,
                "latency_ms": 1000,
                "max_words": 20
            })
            # Diferenciar tipo de ameaca
            if is_reincident is True:
                modifiers["note"] = "Usuario reincidente - gravacao reforcada para boletim"
            return modifiers

        if level == 3:
            # Nivel 3 - Break Glass
            modifiers.update({
                "connection_cut": True,
                "max_words": 0,
                "judicial_alibi": True,
                "latency_ms": 2000
            })
            if is_reincident is True:
                modifiers["penalty_applied"] = "limite_cai_para_70%"
            return modifiers

        return modifiers

    def get_status(self) -> dict:
        """Retornar status resumido do Policy Engine.

        Returns:
            Dict com estado atual do sistema
        """
        stress = self.liver.get_stress_level()
        stress_percent = min(stress / 100.0, 1.0)
        level, _ = self._level_for_stress(stress_percent)
        return {
            "current_stress": round(stress, 2),
            "stress_percent": min(round(stress / 100.0, 2) * 100, 100),
            "policy_level": level,
            "policy_active": self._get_action(level, "default"),
        }