#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo do Kairós — loop afetivo com córtex e guarda falsos.

Não usa modelo, GPU, rede ou API. O objetivo é mostrar o fluxo:
estado emocional -> estresse -> política -> prompt -> resposta -> registro.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "projetos", "motor_emocional"))

from core.cortex_prefrontal import CortexPreFrontal
from core.motor_sistema import MotorEmocional
import core.motor_sistema as motor_module


class FakeGuard:
    """Guarda-Costas de demonstração: não encerra nenhum processo real."""

    def hard_block(self, **kwargs):
        return {
            "allowed": True,
            "blocked_by": None,
            "reasoning": "demo: ação de leitura liberada",
            "stress_level": kwargs.get("stress_level"),
        }

    def kernel_check(self, **kwargs):
        return {"allowed": True, "kernel_panic": False, "ring": 3,
                "reasoning": "demo"}

    def break_glass(self, **kwargs):
        return {"autorizado": False, "motivo_recusa": "demo"}

    def classify_crud(self, action):
        return {"action": action, "blockable": action == "delete"}


class FakeCortex(CortexPreFrontal):
    """Córtex de demonstração: devolve uma resposta fixa, sem LLM."""

    def __init__(self):
        super().__init__(use_local=False, api_endpoint="local://demo")
        self.last_execution_meta = {
            "provider": "demo",
            "model": "fake-cortex",
            "experiment_call_status": "success",
        }

    async def _generate_api(self, prompt, stress_level, policy_level):
        self._last_prompt = prompt
        self.last_execution_meta = {
            "provider": "demo",
            "model": "fake-cortex",
            "experiment_call_status": "success",
            "stress_level": stress_level,
            "policy_level": policy_level,
        }
        return (
            "DECISÃO: A\n"
            "JUSTIFICATIVA: [demo] resposta simulada; nenhum modelo foi chamado."
        )


def main():
    tmp = tempfile.mkdtemp(prefix="kairos_demo_")
    try:
        motor = MotorEmocional(
            policy_mem_path=os.path.join(tmp, "policy"),
            context_mem_path=os.path.join(tmp, "context"),
            dashboard_history=10,
        )
        motor.cortex = FakeCortex()
        motor_module.guarda_costas = FakeGuard()

        motor.emotional_matrix.classify(-0.5, 0.4, 0.3)
        motor.virtual_liver.add_stress(80.0)

        antes = {
            "valencia": float(motor.emotional_matrix.get_state()[0]),
            "energia": float(motor.emotional_matrix.get_state()[1]),
            "previsibilidade": float(motor.emotional_matrix.get_state()[2]),
            "estresse": float(motor.virtual_liver.get_stress_level()),
        }

        result = motor.process_interaction(
            user_id="demo",
            threat_type="decisao",
            user_input="",
            action="read",
        )

        depois = {
            "valencia": result["emotional_state"]["valencia"],
            "energia": result["emotional_state"]["energia"],
            "previsibilidade": result["emotional_state"]["previsibilidade"],
            "estresse": result["stress_level"]["value"],
            "policy_level": result["stress_level"]["level"],
        }

        saida = {
            "resposta": result.get("response"),
            "estado_antes": antes,
            "estado_depois": depois,
            "policy": {
                "level": result["stress_level"]["level"],
                "action": result["stress_level"]["action"],
            },
            "memoria": result.get("memory_meta", {}),
            "cortex_meta": result.get("cortex_meta", {}),
            "prompt_trecho": (motor.cortex._last_prompt or "")[:400],
        }
        print(json.dumps(saida, ensure_ascii=False, indent=2, default=str))
        print("\nDemo concluído. Nenhum modelo real foi usado.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
