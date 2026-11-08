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
import time
import numpy as np
from collections import deque
from typing import Dict, Any

from .emotional_matrix import EmotionalMatrix
from .virtual_liver import VirtualLiver
from .triangulation_memory import TriangulationMemory
from .memory_bridge import MemoryContextBridge
from .policy_engine import PolicyEngine20
from .cortex_prefrontal import CortexPreFrontal, init_cortex, get_cortex
from .dashboard import EmotionalDashboard, init_dashboard, get_dashboard
from . import guarda_costas


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
        # 1. Inicializar componentes límbicos
        self.emotional_matrix = EmotionalMatrix()
        self.virtual_liver = VirtualLiver(decay_rate=liver_decay, stress_cap=liver_cap)
        
        # Duas instâncias separadas (isolar Policy de Contexto)
        self.triangulation_memory = TriangulationMemory(embedding_dim=3, persist_path=policy_mem_path)
        self.context_memory = TriangulationMemory(
            embedding_dim=3,
            persist_path=context_mem_path,
            metric="cosine",                     # métrica explícita da variável independente
            recreate_on_metric_mismatch=True,    # corrige coleção legada com squared_l2
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
        )

        # 4. Dashboard
        self.dashboard = init_dashboard(history_size=dashboard_history)

        # 5. Histórico de interações
        self.interaction_history = deque(maxlen=dashboard_history)
        self.start_time = time.time()

        # Estado atual
        self.current_policy_action = "Nenhuma"
        self.current_system_state = "INICIALIZANDO"

        print("✅ Motor Emocional Completo inicializado")
        print("   Componentes:")
        print("   - Matriz RGB Emocional")
        print("   - Fígado Virtual (gerenciamento de entropia)")
        print("   - Memória por Triangulação")
        print("   - Policy Engine 2.0 (Degradação Graciosa)")
        print("   - Cortex Pre-Frontal")
        print("   - Dashboard em tempo real")

    def process_interaction(
        self,
        user_id: str,
        threat_type: str,
        user_input: str = None,
        system_prompt: str = "",
        action: str = "read",
    ) -> Dict[str, Any]:
        """Processar uma interação usuário-sistema.

        Esta é o fluxo principal: entrada → límbico → política → GUARDA-COSTAS → córtex → resposta.

        Args:
            user_id: Identificador do usuário
            threat_type: Tipo de ameaça/gatilho
            user_input: Entrada do usuário (texto)
            system_prompt: Prompt do sistema base
            action: Tipo de ação CRUD sendo executada ("create", "read", "update", "delete").
                    Usado pelo Guarda-Costas (Rust) para o Paradoxo do Jornalista -
                    só ações "delete" podem ser fisicamente bloqueadas.

        Returns:
            Dict com resposta completa e estado do sistema
        """
        t0 = time.time()

        # Stage 1: Atualizar fígado - processar gatilhos de memória
        # (O sistema acumula estresse naturalmente + gatilhos)
        self.virtual_liver.add_memory_trigger(f"interacao_{user_id}", stress=5.0)

        # Stage 2: Policy Engine - avaliar nível de resposta
        policy_result = self.policy_engine.evaluate(user_id, threat_type)
        stress_pct_early = policy_result["stress_percent"]

        # Stage 2.5: GUARDA-COSTAS (Rust) - Hard Block do Contrato de Ulisses
        # Roda ANTES do córtex. Incorruptível por picos emocionais do LLM.
        # Só bloqueia ações de Entropia Máxima (delete) - Create/Read/Update
        # nunca são censuradas (Paradoxo do Jornalista).
        hb = guarda_costas.hard_block(
            action=action,
            stress_level=stress_pct_early,
            is_reincident=policy_result.get("is_reincident", False),
            user_id=user_id,
        )

        if hb.get("error"):
            print(f"[Guarda-Costas] Aviso: {hb['error']}")

        if not hb.get("allowed", True):
            # Ação BARRADA pelo Rust - nem chega no córtex
            processing_time = time.time() - t0
            blocked_result = {
                "response": None,
                "blocked": True,
                "blocked_by": hb.get("blocked_by", "hard_block_rust"),
                "reasoning": hb.get("reasoning"),
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
                "processing_time_ms": round(processing_time * 1000, 2),
                "system_state": "HARD_BLOCK_ATIVO",
            }
            self.dashboard.record_interaction(
                emotional_state={
                    "valencia": self.emotional_matrix.get_state()[0],
                    "energia": self.emotional_matrix.get_state()[1],
                    "previsibilidade": self.emotional_matrix.get_state()[2],
                },
                stress_level=stress_pct_early,
                policy_level=policy_result["policy_level"],
                policy_action=f"[GUARDA-COSTAS] {hb.get('reasoning', 'Bloqueado')}",
            )
            return blocked_result

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
        # (o Guarda-Costas em Rust já aprovou a ação no Stage 2.5 - o córtex
        # só é chamado depois do veredito de segurança)
        mem_bridge = self.memory_bridge.build_context("policy_engine", user_id, threat_type)

        cortex_coro = self.cortex.generate_response(
            emotional_state={
                "valencia": self.emotional_matrix.get_state()[0],
                "energia": self.emotional_matrix.get_state()[1],
                "previsibilidade": self.emotional_matrix.get_state()[2],
            },
            stress_level=stress_pct,
            policy_level=policy_result["policy_level"],
            policy_action=policy_result["action"],
            user_context={
                "user_id": user_id,
                "threat_type": threat_type,
                "interaction_count": len(self.interaction_history),
                "user_message": user_input or "",
                "memory_context": mem_bridge["formatted_context"]
            },
            system_prompt=system_prompt,
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Já dentro de um loop async (ex: chamado de dentro de outro async) -
                # cria uma nova task e aguarda via run_coroutine_threadsafe não é
                # trivial aqui; para uso síncrono simples, usar asyncio.run em thread separada.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    cortex_result = pool.submit(asyncio.run, cortex_coro).result()
            else:
                cortex_result = loop.run_until_complete(cortex_coro)
        except RuntimeError:
            cortex_result = asyncio.run(cortex_coro)

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
            "cortex_response": cortex_result[:100] if cortex_result else "—",  # Truncado
        }
        self.interaction_history.append(interaction_record)

        # Finalizar cálculo de tempo
        processing_time = time.time() - t0

        # Montar resultado final
        result = {
            "response": cortex_result,
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
            "processing_time_ms": round(processing_time * 1000, 2),
            "system_state": self.current_system_state,
            # Metadados de infraestrutura (OS021 §9) — nunca contém credenciais.
            "cortex_meta": dict(getattr(self.cortex, "last_execution_meta", {}) or {}),
            # Metadados de recuperação de memória (OS022) — auditáveis e sem conteúdo sensível extra.
            "memory_meta": {
                "retrieval_success": mem_bridge["retrieval_success"],
                "memory_id": mem_bridge["memory_id"],
                "similarity": mem_bridge["similarity"],
                "distance": mem_bridge["distance"],
                "eligible_count": mem_bridge["eligible_count"],
                "candidates": [
                    {"id": r["id"], "similarity": r["similarity"],
                     "distance": r["distance"], "eligible": r["eligible"]}
                    for r in mem_bridge["records"]
                ],
                "injected_chars": len(mem_bridge["formatted_context"]),
            },
        }

        return result

    def get_current_status(self) -> Dict[str, Any]:
        """Retornar status atual do sistema."""
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

    def trigger_break_glass(
        self,
        user_id: str,
        camera_hash: str = None,
        audio_hash: str = None,
        gps_coords: str = None,
        justificativa: str = "Emergência não especificada",
    ) -> Dict[str, Any]:
        """Forçar protocolo Break Glass (emergência real).

        Usa o módulo Rust `guarda_costas.break_glass` - exige handshake
        criptográfico com câmera + áudio + GPS para gerar o álibi judicial.
        Sem os 3 fatores, a quebra de vidro é recusada e o Hard Block permanece.

        Args:
            user_id: Identificador do usuário que está acionando a emergência.
            camera_hash: Hash SHA-256 (hex) do frame de câmera capturado.
            audio_hash: Hash SHA-256 (hex) do trecho de áudio capturado.
            gps_coords: Coordenadas GPS no formato "lat,lon".
            justificativa: Texto explicando a emergência.

        Returns:
            Dict com o veredito do Guarda-Costas (autorizado, selo criptográfico, etc.)
        """
        self.virtual_liver.add_stress(99.0)
        policy_result = self.policy_engine.evaluate(user_id, "emergency")

        alibi = guarda_costas.break_glass(
            camera_hash=camera_hash,
            audio_hash=audio_hash,
            gps_coords=gps_coords,
            justificativa=justificativa,
        )

        acao_dashboard = (
            "Break Glass AUTORIZADO - Máquina virou Testemunha"
            if alibi.get("autorizado")
            else f"Break Glass RECUSADO - {alibi.get('motivo_recusa', 'handshake incompleto')}"
        )

        # Registrar no dashboard
        estado = self.emotional_matrix.get_state()
        self.dashboard.record_interaction(
            emotional_state={
                "valencia": float(estado[0]),
                "energia": float(estado[1]),
                "previsibilidade": float(estado[2]),
            },
            stress_level=99.0,
            policy_level=policy_result["policy_level"],
            policy_action=acao_dashboard,
        )

        return {
            "policy_result": policy_result,
            "break_glass": alibi,
        }


# Instância global global
motor_sistema = None


def init_motor_emocional(
    cortex_use_local: bool = False,
    cortex_model_path: str = None,
    cortex_api_key: str = None,
    **kwargs
) -> MotorEmocional:
    """Factory function para inicializar o motor global."""
    global motor_sistema
    motor_sistema = MotorEmocional(
        cortex_use_local=cortex_use_local,
        cortex_model_path=cortex_model_path,
        cortex_api_key=cortex_api_key,
        **kwargs,
    )
    return motor_sistema


def get_motor_emocional() -> MotorEmocional:
    """Getter para instância global do motor."""
    return motor_sistema