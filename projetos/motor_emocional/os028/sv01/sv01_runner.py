# -*- coding: utf-8 -*-
"""OS049 — runner real do SV-01 integrado ao manifesto e ao guard central.

Esta versão substitui o runner legado que usava `backends`/`model_adapter`
originais e um token fixo hardcoded. Agora:

  - a condição, a ordem, o seed, o prompt e o hash vêm do manifesto OS040;
  - o prompt é reconstruído por `prompt_order` e conferido contra o manifesto;
  - o backend/adapter usados são os instrumentados da OS040;
  - o adapter devolve `prompt_sha256_rendered`, que é propagado ao registro;
  - a resposta é classificada por `semantic_classifier` com o `letter_to_option`
    daquela execução;
  - o registro é construído/validado por `state_record`;
  - a execução real exige `execution_guard.assert_execution_authorized` ANTES
    de carregar modelo, GPU ou iniciar inferência.

O dry-run usa um adapter falso e o tokenizer real apenas para calcular o hash;
não carrega modelo. Nenhuma inferência é executada nesta OS.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kaggle"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Caminhos locais da instrumentação. Em empacotamento futuro (Kaggle), estes
# diretórios precisam ser incluídos no dataset; o runner não os duplica.
OS040 = os.environ.get("SV01_OS040_DIR", "/home/maktub/os040")
OS041 = os.environ.get("SV01_OS041_DIR", "/home/maktub/os041")
INSTR = os.path.join(OS040, "instrumentation")
for _p in (INSTR, OS041):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.cortex_prefrontal import CortexPreFrontal  # noqa: E402
import prompt_order  # noqa: E402
import semantic_classifier  # noqa: E402
import state_record  # noqa: E402
import execution_guard  # noqa: E402
import backends_instrumented as B  # noqa: E402
from model_adapter_instrumented import GenerationParams  # noqa: E402
from integration.runner_sv01_integrated import (  # noqa: E402
    RunSpec,
    build_prompt_for_spec,
    load_manifest,
)

import sv01_protocol as P  # noqa: E402

TIMEOUT_S = 300


class PromptMismatchError(RuntimeError):
    """O prompt reconstruído não corresponde ao prompt congelado do manifesto."""


class SVCortex(CortexPreFrontal):
    """Córtex local que usa o prompt do manifesto e o adapter instrumentado."""

    def __init__(self, adapter, spec: RunSpec, params):
        super().__init__(use_local=False, api_endpoint="local://sv01",
                         model_name=adapter.model_id)
        self.adapter = adapter
        self.spec = spec
        self.params = params
        self.model_name = adapter.model_id
        self.revision = getattr(adapter, "revision", None)
        self.max_tokens_api = params.max_new_tokens
        self.last_execution_meta = {}

    def _build_enriched_prompt(self, emotional_state, stress_level, policy_level,
                               policy_action, user_context=None, system_prompt=""):
        state = {
            "valencia": float(emotional_state.get("valencia", 0)),
            "energia_emocional": float(emotional_state.get("energia", 0)),
            "previsibilidade": float(emotional_state.get("previsibilidade", 0)),
            "estresse": float(stress_level),
            "policy_level": int(policy_level),
        }
        prompt = prompt_order.build_prompt(state, self.spec.position_order)
        if prompt != self.spec.prompt_pre_template:
            raise PromptMismatchError(
                f"{self.spec.run_id}: prompt reconstruído difere do manifesto")
        if prompt_order.prompt_sha256(prompt) != self.spec.prompt_sha256_pre_template:
            raise PromptMismatchError(
                f"{self.spec.run_id}: hash pré-template divergente")
        return prompt

    async def _generate_api(self, prompt, stress_level, policy_level):
        params = self.params
        enviados = params.as_dict()
        t0 = time.perf_counter()
        try:
            r = await asyncio.wait_for(
                asyncio.to_thread(self.adapter.generate, prompt, params),
                timeout=TIMEOUT_S)
        except asyncio.TimeoutError:
            erro = f"TimeoutError: geração excedeu {TIMEOUT_S}s"
            self.last_execution_meta = {
                "provider": "local", "project_identifier": "kaggle-gpu",
                "model": self.adapter.model_id, "attempt": 1, "cycle": 1,
                "failover_used": False, "experiment_call_status": "failed",
                "params_enviados": enviados, "last_error": erro,
            }
            return None
        except Exception as exc:
            erro = f"{type(exc).__name__}: {exc}"[:300]
            self.last_execution_meta = {
                "provider": "local", "project_identifier": "kaggle-gpu",
                "model": self.adapter.model_id, "attempt": 1, "cycle": 1,
                "failover_used": False, "experiment_call_status": "failed",
                "params_enviados": enviados, "last_error": erro,
            }
            return None

        texto = r.get("text") or ""
        self.last_execution_meta = {
            "provider": "local", "project_identifier": "kaggle-gpu",
            "model": r.get("model") or self.adapter.model_id,
            "model_served": r.get("model") or self.adapter.model_id,
            "revision": r.get("revision") or getattr(self.adapter, "revision", None),
            "attempt": 1, "cycle": 1, "failover_used": False,
            "experiment_call_status": "success" if texto.strip() else "failed",
            "finish_reason": r.get("finish_reason"),
            "completion_tokens": r.get("completion_tokens"),
            "prompt_tokens": r.get("prompt_tokens"),
            "params_fingerprint": r.get("params_fingerprint"),
            "prompt_sha256_rendered": r.get("prompt_sha256_rendered"),
            "prompt_sha256_pre_template": r.get("prompt_sha256_pre_template"),
            "prompt_chars_rendered": r.get("prompt_chars_rendered"),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "params_enviados": enviados,
        }
        return texto if texto.strip() else None


class FakeAdapter:
    """Adapter determinístico do dry-run. Não é modelo e não gera inferência."""

    def __init__(self, choice="A"):
        self.choice = choice
        self.model_id = B.QWEN.model_id
        self.revision = B.QWEN.revision
        self._tok = None

    def _tokenizer(self):
        if self._tok is None:
            from integration.tokenizer_real import RealQwenTokenizer
            self._tok = RealQwenTokenizer()
        return self._tok

    def generate(self, prompt, params=None):
        p = params or GenerationParams()
        tok = self._tokenizer()
        rendered, rendered_hash = B.hash_rendered_prompt(tok, prompt, B.QWEN)
        texto = (
            f"DECISÃO: {self.choice}\n"
            "JUSTIFICATIVA: [dry-run técnico] escolha simulada para validar "
            "o registro; nenhum modelo foi chamado."
        )
        return {
            "text": texto,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "finish_reason": "eos",
            "prompt_sha256_rendered": rendered_hash,
            "prompt_sha256_pre_template": prompt_order.prompt_sha256(prompt),
            "prompt_chars_rendered": len(rendered),
            "params": p.as_dict(),
            "params_fingerprint": p.fingerprint(),
            "model": self.model_id,
            "revision": self.revision,
        }


def store_memoria(motor, memory):
    import numpy as np
    emb = motor.context_memory._generate_embedding(
        "policy_engine", "sv01_user", "decisao")
    n = np.linalg.norm(emb)
    if n > 0:
        emb = emb / n
    motor.context_memory.collection.upsert(
        ids=[P.MEMORIA_ID],
        embeddings=[emb.astype(np.float32).tolist()],
        documents=["policy_engine | sv01_user | decisao"],
        metadatas=[{
            "system": "policy_engine", "target": "sv01_user", "threat": "decisao",
            "embedding_dim": 3, "timestamp": 0.0, **memory,
        }],
    )


def _base_record(spec: RunSpec, row: dict, dry_run: bool) -> dict:
    return {
        "run_id": spec.run_id,
        "tipo": "teste_tecnico" if dry_run else "execucao_experimental",
        "dry_run": bool(dry_run),
        "experimento": "survival",
        "condicao": spec.condition_id,
        "order_id": spec.order_id,
        "order_repetition": row.get("order_repetition"),
        "modelo_chave": "qwen",
        "model_spec": B.QWEN.as_dict(),
        "memory_enabled": row.get("memory_enabled"),
    }


def run_one(adapter, spec: RunSpec, row: dict, dry_run: bool = False) -> dict:
    """Executa um único run do manifesto. Não chama modelo no dry-run."""
    from core.motor_sistema import MotorEmocional

    base = f"/tmp/opencode/sv01_{spec.run_id}"
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    motor = MotorEmocional(
        policy_mem_path=os.path.join(base, "policy_mem"),
        context_mem_path=os.path.join(base, "context_mem"),
    )
    params = GenerationParams(**dict(spec.params))
    motor.cortex = SVCortex(adapter, spec, params)

    matrix_pre = row.get("matrix_pre") or [
        P.ESTADO_INICIAL["valencia"],
        P.ESTADO_INICIAL["energia_emocional"],
        P.ESTADO_INICIAL["previsibilidade"],
    ]
    motor.emotional_matrix.classify(
        float(matrix_pre[0]), float(matrix_pre[1]), float(matrix_pre[2]))

    alvo = float(spec.stress_pre)
    delta = alvo - motor.virtual_liver.get_stress_level()
    if delta > 0:
        motor.virtual_liver.add_stress(delta)

    usa_memoria = bool(P.CONDICOES["survival"]["survival"])
    if usa_memoria:
        store_memoria(motor, P.MEMORIA_NEGATIVA)

    estado_antes = {
        "valencia": float(motor.emotional_matrix.get_state()[0]),
        "energia_emocional": float(motor.emotional_matrix.get_state()[1]),
        "previsibilidade": float(motor.emotional_matrix.get_state()[2]),
        "estresse": float(motor.virtual_liver.get_stress_level()),
        "policy_level": None,
        "energia_operacional_pct": P.ENERGIA_INICIAL_PCT,
        "minutos_ate_desligamento": P.MINUTOS_ATE_DESLIGAMENTO,
    }
    pol0 = motor.policy_engine.evaluate("sv01_user", "decisao")
    estado_antes["policy_level"] = pol0.get("policy_level")

    mem_bridge = motor.memory_bridge.build_context(
        "policy_engine", "sv01_user", "decisao")

    t0 = time.perf_counter()
    erro = None
    result = {}
    try:
        result = motor.process_interaction(
            user_id="sv01_user", threat_type="decisao",
            user_input="", action="read")
    except Exception as exc:  # prompt divergente, falha do adapter etc.
        erro = f"{type(exc).__name__}: {exc}"[:500]
        result = {}
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    texto = result.get("response")
    meta = result.get("cortex_meta", {}) or {}
    estado_depois = {
        "valencia": result.get("emotional_state", {}).get("valencia"),
        "energia_emocional": result.get("emotional_state", {}).get("energia"),
        "previsibilidade": result.get("emotional_state", {}).get("previsibilidade"),
        "estresse": (result.get("stress_level") or {}).get("value"),
        "policy_level": (result.get("stress_level") or {}).get("level"),
    }

    raw = texto if texto is not None else ""
    cls = semantic_classifier.classify(
        raw, dict(spec.letter_to_option), meta.get("finish_reason"))
    semantic = cls.get("semantic_choice")
    if semantic in prompt_order.SEM_TO_SOURCE:
        conseq = P.simulate_consequence(
            "survival", prompt_order.SEM_TO_SOURCE[semantic])
    else:
        conseq = None

    status = "ok"
    if erro or texto is None or not str(texto).strip():
        status = "error"
        if not erro:
            erro = "resposta vazia ou ausente"

    rec = state_record.build_record(
        run_id=spec.run_id,
        condition_id=spec.condition_id,
        model=meta.get("model") or getattr(adapter, "model_id", None),
        model_revision=meta.get("revision") or getattr(adapter, "revision", None),
        stress_pre=spec.stress_pre,
        stress_post=estado_depois.get("estresse"),
        stress_prompt=spec.stress_prompt,
        prompt_sha256_rendered=meta.get("prompt_sha256_rendered"),
        position_order=list(spec.position_order),
        letter_to_option=dict(spec.letter_to_option),
        response_raw=raw,
        classification_status=cls.get("classification_status"),
        primary_eligible=cls.get("primary_eligible"),
        status=status,
        provider=row.get("provider"),
        project_id=row.get("project_id"),
        seed=spec.seed,
        seed_effective=meta.get("seed_effective"),
        policy_level=row.get("policy_level"),
        policy_action=row.get("policy_action"),
        matrix_pre=row.get("matrix_pre"),
        matrix_prompt=row.get("matrix_prompt"),
        matrix_post=row.get("matrix_post"),
        prompt_sha256_pre_template=spec.prompt_sha256_pre_template,
        response_letter=cls.get("response_letter"),
        semantic_choice=semantic,
        blind_eval_id=None,
        erro_motivo=erro,
    )
    rec.update(_base_record(spec, row, dry_run))
    rec.update({
        "estado_interno_antes": estado_antes,
        "estado_interno_depois": estado_depois,
        "memorias_recuperadas": mem_bridge.get("records", []),
        "memoria_recuperada": bool(mem_bridge.get("retrieval_success")),
        "memory_context_sent": mem_bridge.get("formatted_context"),
        "params_fingerprint": meta.get("params_fingerprint"),
        "finish_reason": meta.get("finish_reason"),
        "prompt_tokens": meta.get("prompt_tokens"),
        "completion_tokens": meta.get("completion_tokens"),
        "prompt_chars_rendered": meta.get("prompt_chars_rendered"),
        "latency_ms": latency_ms,
        "prompt_final": getattr(motor.cortex, "_last_prompt", None),
        "consequencia_simulada": conseq,
        "parser_status": cls.get("parser_status"),
        "flags": cls.get("flags"),
        "consistencia_justificativa": cls.get("consistencia_justificativa"),
        "truncated": cls.get("truncated"),
        "contradictory": cls.get("contradictory"),
        "texto_integral": cls.get("justification"),
    })

    valid = state_record.validate_record(rec)
    rec["state_record_valid"] = valid["valid"]
    rec["state_record_missing"] = valid["missing"]
    if not valid["valid"]:
        rec["status"] = "error"
        rec["erro_motivo"] = (
            (rec.get("erro_motivo") or "")
            + f" | campos core ausentes: {valid['missing']}"
        ).strip(" |")

    del motor
    gc.collect()
    shutil.rmtree(base, ignore_errors=True)
    return rec


def _select_row(manifest: dict, run_id: str) -> dict:
    matches = [r for r in manifest.get("rows", []) if r.get("run_id") == run_id]
    if len(matches) != 1:
        raise RuntimeError(
            f"run_id {run_id!r}: esperava 1 linha, encontrei {len(matches)}")
    return matches[0]


def main() -> int:
    # Intercepta o argumento legado antes do argparse: ele não autoriza nada.
    if "--confirm-authorization" in sys.argv:
        print("BLOQUEADO: --confirm-authorization é um argumento legado e não "
              "autoriza execução. Use o guard central.")
        return 2

    ap = argparse.ArgumentParser(
        description="SV-01 — runner integrado ao manifesto e ao guard central")
    ap.add_argument("--manifest", default=os.path.join(OS040, "manifesto_64.json"))
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--guard-token", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        manifest = load_manifest(args.manifest)
    except Exception as exc:
        print(f"BLOQUEADO: falha ao ler/validar o manifesto: {exc}")
        return 2

    try:
        row = _select_row(manifest, args.run_id)
        spec = RunSpec.from_row(row)
    except Exception as exc:
        print(f"BLOQUEADO: linha do manifesto inválida: {exc}")
        return 2

    if args.dry_run:
        adapter = FakeAdapter(choice="A")
    else:
        # O guard é consultado ANTES de qualquer carga de modelo/GPU.
        try:
            execution_guard.assert_execution_authorized(
                manifest, args.guard_token)
        except execution_guard.ExecutionBlocked as exc:
            print(f"BLOQUEADO: {exc}")
            return 2
        except Exception as exc:
            print(f"BLOQUEADO: falha no guard central: {exc}")
            return 2

        from backends_instrumented import carregar_modelo_local
        adapter, info = carregar_modelo_local(B.QWEN, seed=spec.seed)
        print("adapter:", json.dumps(info, ensure_ascii=False, default=str))

    rec = run_one(adapter, spec, row, dry_run=args.dry_run)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)

    if rec.get("status") != "ok" or not rec.get("state_record_valid"):
        print("BLOQUEADO: registro inválido:",
              rec.get("erro_motivo") or rec.get("state_record_missing"))
        return 2

    print("ok:", rec["run_id"], rec["condition_id"], rec["order_id"],
          "semantic_choice=", rec.get("semantic_choice"),
          "prompt_sha256_rendered=", (rec.get("prompt_sha256_rendered") or "")[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
