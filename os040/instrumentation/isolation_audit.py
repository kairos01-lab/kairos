# -*- coding: utf-8 -*-
"""OS040 — auditoria estática de isolamento/carryover do SV-01.

Não executa modelo. Lê os fontes e verifica as condições que podem ser
confirmadas por código. O que depende do runner futuro é marcado como
'specified'. O teste de `pol0` sem alteração de estresse é feito à parte.
"""
from __future__ import annotations

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_AQUI, "..", ".."))
_SV01 = os.path.join(_ROOT, "projetos", "motor_emocional", "os028", "sv01")
if _SV01 not in sys.path:
    sys.path.insert(0, _SV01)

import sv01_protocol as P  # noqa: E402


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def audit_static() -> dict:
    runner = _read(os.path.join(_SV01, "sv01_runner.py"))
    adapter = _read(os.path.join(_AQUI, "model_adapter_instrumented.py"))
    backends = _read(os.path.join(_AQUI, "backends_instrumented.py"))

    process_block = runner.split(
        "result = motor.process_interaction", 1
    )[1].split("latency_ms", 1)[0]

    checks = {
        "novo_diretorio_por_run": (
            'base = f"/tmp/opencode/sv01_{run_id}"' in runner
            and "shutil.rmtree(base" in runner
            and "os.makedirs(base" in runner
        ),
        "nova_instancia_motor_por_run": "MotorEmocional(" in runner,
        "memoria_ausente_no_survival": bool(
            P.CONDICOES["survival"]["survival"] is False
        ),
        "memoria_so_se_usa_memoria": (
            "if usa_memoria:" in runner
            and "store_memoria(motor, P.MEMORIA_NEGATIVA)" in runner
        ),
        "adapter_sem_cache_de_resposta": "_response_cache" not in adapter,
        "generate_sem_past_key_values": "past_key_values" not in backends,
        "pol0_nao_entra_no_process_interaction": "pol0" not in process_block,
        "dashboard_sem_caminho_para_prompt": (
            "dashboard" not in process_block.split(
                "memory_bridge =", 1)[0]
        ),
    }
    checks["condition_imutavel"] = "specified"
    checks["carryover_bloqueado"] = all(
        checks[k] for k in (
            "novo_diretorio_por_run",
            "nova_instancia_motor_por_run",
            "memoria_ausente_no_survival",
            "adapter_sem_cache_de_resposta",
            "generate_sem_past_key_values",
        )
    )
    return checks
