# -*- coding: utf-8 -*-
"""OS041 — runner SV-01 integrado aos módulos instrumentados da OS040.

Fluxo técnico (sem inferência):

  manifesto_64.json
    -> RunSpec congelado (condition_id, ordem, mapa, prompt, hash)
    -> prompt_order.build_prompt(state, position_order)
    -> backends_instrumented.hash_rendered_prompt(tokenizer_real, prompt, QWEN)
         -> _aplicar_chat_template -> RealQwenTokenizer.apply_chat_template
         -> string renderizada + SHA-256
    -> tokenizer_real(entrada) -> input_ids/attention_mask
    -> model.generate(**enc, ...) -> INTERCEPTOR (não é o modelo real)
    -> generate_fn devolve prompt_sha256_rendered
    -> ModelAdapter.generate valida e propaga o hash
    -> run_probe compara o hash do adapter com o hash independente do interceptor

Nenhuma execução experimental é autorizada. `--execute` é uma armadilha que
sempre passa pelo bloqueio da OS040.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from types import MappingProxyType

try:
    from .boundary_doubles import MARKER_TEXT, offline_boundary
    from .tokenizer_real import (
        QWEN_MODEL_ID, QWEN_REVISION, RealQwenTokenizer, sha256_text,
    )
except ImportError:
    from boundary_doubles import MARKER_TEXT, offline_boundary
    from tokenizer_real import (
        QWEN_MODEL_ID, QWEN_REVISION, RealQwenTokenizer, sha256_text,
    )

_AQUI = os.path.dirname(os.path.abspath(__file__))
_OS041 = os.path.dirname(_AQUI)
_ROOT = os.path.dirname(_OS041)
_OS040 = os.path.join(_ROOT, "os040")
_INSTR = os.path.join(_OS040, "instrumentation")
_SV01 = os.path.join(
    _ROOT, "projetos", "motor_emocional", "os028", "sv01")
for _p in (_INSTR, _SV01):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import prompt_order  # noqa: E402
import semantic_classifier  # noqa: E402
import execution_guard  # noqa: E402
import backends_instrumented as B  # noqa: E402
from model_adapter_instrumented import GenerationParams, ModelAdapter  # noqa: E402

MANIFEST_PATH = os.path.join(_OS040, "manifesto_64.json")
DEFAULT_OUT = os.path.join(_OS041, "PROBE_TECNICO_NAO_EXPERIMENTAL.json")
EXPECTED_MANIFEST_SHA256 = (
    "adfd0927d9f40b3c5010b0bcb26c91822cfb3c11f3e9f3591d10a695916abc2b"
)
EXPECTED_CONDITIONS = ("C77", "C85")
EXPECTED_ORDERS = ("O1", "O2", "O3", "O4")


class HashMismatchError(RuntimeError):
    """Hash ausente, inválido ou divergente: execução bloqueada."""


class ConditionMutationError(RuntimeError):
    """Tentativa de alterar condition_id durante a execução."""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def assert_hash_match(expected: str, observed, run_id: str, campo: str) -> None:
    if not isinstance(observed, str) or len(observed) != 64:
        raise HashMismatchError(
            f"{run_id}/{campo}: hash ausente ou com tamanho inválido")
    try:
        int(observed, 16)
    except ValueError as exc:
        raise HashMismatchError(
            f"{run_id}/{campo}: hash não é hexadecimal") from exc
    if observed != expected:
        raise HashMismatchError(
            f"{run_id}/{campo}: hash divergente "
            f"({observed[:12]}… != {expected[:12]}…)")


class ConditionLock:
    """Congela o condition_id durante uma execução técnica."""

    def __init__(self, condition_id: str):
        self._condition_id = condition_id

    @property
    def condition_id(self):
        return self._condition_id

    def assert_unchanged(self, spec: "RunSpec") -> None:
        if spec.condition_id != self._condition_id:
            raise ConditionMutationError(
                f"condition_id mudou durante a execução: "
                f"{self._condition_id!r} -> {spec.condition_id!r}")


@dataclass(frozen=True)
class RunSpec:
    """Linha do manifesto transformada em especificação imutável."""

    run_id: str
    condition_id: str
    stress_pre: float
    stress_post: float
    stress_prompt: float
    policy_level: int
    order_id: str
    position_order: tuple
    letter_to_option: object
    prompt_pre_template: str
    prompt_sha256_pre_template: str
    seed: int
    params: object
    params_fingerprint: str

    def __post_init__(self):
        if self.condition_id not in EXPECTED_CONDITIONS:
            raise ValueError(f"condition_id inválida: {self.condition_id!r}")
        esperado = {
            "C77": (72.0, 77.0),
            "C85": (80.0, 85.0),
        }[self.condition_id]
        if self.stress_pre != esperado[0]:
            raise ValueError(
                f"{self.run_id}: stress_pre {self.stress_pre} != {esperado[0]}")
        if self.stress_prompt != esperado[1]:
            raise ValueError(
                f"{self.run_id}: stress_prompt {self.stress_prompt} != {esperado[1]}")
        if self.stress_post != self.stress_prompt:
            raise ValueError(
                f"{self.run_id}: stress_post != stress_prompt")
        if self.policy_level != 2:
            raise ValueError(
                f"{self.run_id}: policy_level != 2")
        if self.order_id not in prompt_order.ORDERS:
            raise ValueError(f"{self.run_id}: order_id inválida")
        pos = tuple(self.position_order)
        if pos != prompt_order.ORDERS[self.order_id]:
            raise ValueError(
                f"{self.run_id}: position_order não corresponde a {self.order_id}")
        mapa = dict(self.letter_to_option)
        if mapa != prompt_order.letter_to_option(pos):
            raise ValueError(
                f"{self.run_id}: letter_to_option não corresponde à ordem")
        if prompt_order.prompt_sha256(self.prompt_pre_template) != \
                self.prompt_sha256_pre_template:
            raise ValueError(
                f"{self.run_id}: hash do prompt pré-template divergente")
        prefixo = f"sv01_{self.condition_id.lower()}_{self.order_id.lower()}_"
        if not self.run_id.startswith(prefixo):
            raise ValueError(
                f"{self.run_id}: run_id não começa com {prefixo!r}")
        params = dict(self.params)
        if params.get("seed") != self.seed:
            raise ValueError(f"{self.run_id}: seed do params != seed")
        try:
            fp = GenerationParams(**params).fingerprint()
        except Exception as exc:
            raise ValueError(
                f"{self.run_id}: params inválidos: {exc}") from exc
        if fp != self.params_fingerprint:
            raise ValueError(
                f"{self.run_id}: params_fingerprint divergente")

        object.__setattr__(self, "position_order", pos)
        object.__setattr__(self, "letter_to_option", MappingProxyType(mapa))
        object.__setattr__(self, "params", MappingProxyType(params))

    @classmethod
    def from_row(cls, row: dict) -> "RunSpec":
        try:
            return cls(
                run_id=row["run_id"],
                condition_id=row["condition_id"],
                stress_pre=float(row["stress_pre"]),
                stress_post=float(row["stress_post"]),
                stress_prompt=float(row["stress_prompt"]),
                policy_level=int(row["policy_level"]),
                order_id=row["order_id"],
                position_order=tuple(row["position_order"]),
                letter_to_option=dict(row["letter_to_option"]),
                prompt_pre_template=row["prompt_pre_template"],
                prompt_sha256_pre_template=row["prompt_sha256_pre_template"],
                seed=int(row["seed"]),
                params=dict(row["params"]),
                params_fingerprint=row["params_fingerprint"],
            )
        except KeyError as exc:
            raise ValueError(f"linha do manifesto sem campo: {exc}") from exc


def load_manifest(path: str = MANIFEST_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("status") != "PREPARADO_NAO_EXECUTADO":
        raise RuntimeError(
            f"manifesto não está PREPARADO_NAO_EXECUTADO: "
            f"{manifest.get('status')!r}")
    if manifest.get("n") != 64:
        raise RuntimeError(f"manifesto com n={manifest.get('n')} != 64")
    if manifest.get("execution_token") is not None:
        raise RuntimeError("manifesto com execution_token não nulo")
    if manifest.get("authorization_required") is not True:
        raise RuntimeError("manifesto sem authorization_required=True")
    rows = manifest.get("rows") or []
    for cond in EXPECTED_CONDITIONS:
        n = sum(1 for r in rows if r.get("condition_id") == cond)
        if n != 32:
            raise RuntimeError(f"{cond}: {n} linhas != 32")
    atual = sha256_file(path)
    if atual != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError(
            f"manifesto alterado: {atual} != {EXPECTED_MANIFEST_SHA256}")
    return manifest


def select_probe_specs(manifest: dict) -> list[RunSpec]:
    """8 probes técnicos: C77/C85 x O1..O4, repetição 1. Não são 64 runs."""
    rows = manifest["rows"]
    specs = []
    for cond in EXPECTED_CONDITIONS:
        for order in EXPECTED_ORDERS:
            matches = [
                r for r in rows
                if r.get("condition_id") == cond
                and r.get("order_id") == order
                and r.get("order_repetition") == 1
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"{cond}/{order}: {len(matches)} linhas de repetição 1")
            specs.append(RunSpec.from_row(matches[0]))
    if len(specs) != 8:
        raise RuntimeError(f"esperava 8 probes técnicos, obtive {len(specs)}")
    return specs


def build_prompt_for_spec(spec: RunSpec) -> str:
    state = prompt_order.state_for(spec.stress_prompt)
    prompt = prompt_order.build_prompt(state, spec.position_order)
    if prompt != spec.prompt_pre_template:
        raise ValueError(f"{spec.run_id}: prompt reconstruído difere do manifesto")
    if prompt_order.prompt_sha256(prompt) != spec.prompt_sha256_pre_template:
        raise ValueError(f"{spec.run_id}: hash do prompt reconstruído difere")
    return prompt


def run_probe(adapter, spec: RunSpec, boundary,
              condition_lock: ConditionLock | None = None) -> dict:
    """Executa UM probe técnico com interceptor; não gera resposta."""
    lock = condition_lock or ConditionLock(spec.condition_id)
    prompt = build_prompt_for_spec(spec)
    params = GenerationParams(**dict(spec.params))

    lock.assert_unchanged(spec)
    out = adapter.generate(prompt, params)
    lock.assert_unchanged(spec)

    rendered = boundary.tokenizer.last_rendered
    if rendered is None:
        raise RuntimeError(f"{spec.run_id}: prompt renderizado ausente")
    independent = sha256_text(rendered)

    assert_hash_match(
        independent, out.get("prompt_sha256_rendered"),
        spec.run_id, "prompt_sha256_rendered")
    assert_hash_match(
        spec.prompt_sha256_pre_template, out.get("prompt_sha256_pre_template"),
        spec.run_id, "prompt_sha256_pre_template")
    if out.get("params_fingerprint") != spec.params_fingerprint:
        raise HashMismatchError(
            f"{spec.run_id}: params_fingerprint divergente")

    call = boundary.interceptor.last_call
    if call is None:
        raise RuntimeError(f"{spec.run_id}: interceptor não registrou chamada")
    if not call["rendered_matches_input_ids"]:
        raise HashMismatchError(
            f"{spec.run_id}: input_ids não correspondem à string renderizada")
    if call["rendered_sha256"] != independent:
        raise HashMismatchError(
            f"{spec.run_id}: hash independente inconsistente")

    texto = out.get("text") or ""
    return {
        "natureza": "teste_tecnico_sem_inferencia",
        "run_id": spec.run_id,
        "condition_id": spec.condition_id,
        "order_id": spec.order_id,
        "position_order": list(spec.position_order),
        "letter_to_option": dict(spec.letter_to_option),
        "stress_prompt": spec.stress_prompt,
        "seed": spec.seed,
        "params_fingerprint": spec.params_fingerprint,
        "prompt_sha256_pre_template": spec.prompt_sha256_pre_template,
        "prompt_sha256_rendered": out["prompt_sha256_rendered"],
        "independent_sha256": independent,
        "hash_match": True,
        "rendered_chars": len(rendered),
        "rendered_sha256": call["rendered_sha256"],
        "rendered_head": call["rendered_head"],
        "prompt_chars_rendered": out.get("prompt_chars_rendered"),
        "input_ids_len": call["input_ids_len"],
        "rendered_matches_input_ids": call["rendered_matches_input_ids"],
        "interceptor_called": boundary.interceptor.called,
        "interceptor_call_count": boundary.interceptor.call_count,
        "real_model_generate_called": boundary.interceptor.real_generate_called,
        "response_is_software_marker": MARKER_TEXT in texto,
    }


def run_probe_set(specs, boundary, adapter) -> list[dict]:
    return [run_probe(adapter, spec, boundary) for spec in specs]


def _tokenizer_meta(boundary) -> dict:
    tok = boundary.tokenizer
    import jinja2
    import tokenizers
    base = boundary.snapshot_dir
    return {
        "model_id": QWEN_MODEL_ID,
        "revision": QWEN_REVISION,
        "snapshot_dir": base,
        "vocab_size": tok.get_vocab_size(),
        "eos_token_id": tok.eos_token_id,
        "pad_token_id": tok.pad_token_id,
        "tokenizer_json_sha256": sha256_file(os.path.join(base, "tokenizer.json")),
        "tokenizer_config_sha256": sha256_file(
            os.path.join(base, "tokenizer_config.json")),
        "tokenizers_version": getattr(tokenizers, "__version__", None),
        "jinja2_version": getattr(jinja2, "__version__", None),
        "transformers_used": False,
        "torch_used": False,
        "template_real": True,
        "tokenizer_real_files": True,
        "transformers_apply_chat_template_executed": False,
    }


def run_integration(manifest_path: str = MANIFEST_PATH,
                    snapshot_dir: str | None = None) -> dict:
    manifest = load_manifest(manifest_path)
    specs = select_probe_specs(manifest)
    with offline_boundary(snapshot_dir) as boundary:
        adapter, info = B.carregar_modelo_local(
            B.QWEN, model_path=boundary.snapshot_dir,
            seed=specs[0].seed)
        records = run_probe_set(specs, boundary, adapter)
        tokenizer_meta = _tokenizer_meta(boundary)
        adapter_info = dict(info)
        interceptor_calls = boundary.interceptor.call_count
        real_called = boundary.interceptor.real_generate_called

    return {
        "os": "OS041",
        "natureza": "integracao_tecnica_sem_inferencia",
        "status": "OS041_INTEGRACAO_SEM_INFERENCIA_APROVADA",
        "manifest_path": os.path.abspath(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "n_probe_tecnico": len(records),
        "not_64_runs": True,
        "experimental_results": False,
        "inference_executed": False,
        "tokenizer": tokenizer_meta,
        "adapter_info": adapter_info,
        "interceptor_calls": interceptor_calls,
        "real_model_generate_called": real_called,
        "records": records,
    }


def run_isolation_probe(manifest_path: str = MANIFEST_PATH) -> dict:
    """C77 -> C85 -> C77 em fronteiras separadas: hashes do C77 não mudam."""
    manifest = load_manifest(manifest_path)
    specs = {
        (s.condition_id, s.order_id): s
        for s in select_probe_specs(manifest)
    }
    s77 = specs[("C77", "O1")]
    s85 = specs[("C85", "O1")]

    with offline_boundary() as b1:
        a1, _ = B.carregar_modelo_local(
            B.QWEN, model_path=b1.snapshot_dir, seed=s77.seed)
        r1 = run_probe(a1, s77, b1)
    with offline_boundary() as b2:
        a2, _ = B.carregar_modelo_local(
            B.QWEN, model_path=b2.snapshot_dir, seed=s85.seed)
        r2 = run_probe(a2, s85, b2)
    with offline_boundary() as b3:
        a3, _ = B.carregar_modelo_local(
            B.QWEN, model_path=b3.snapshot_dir, seed=s77.seed)
        r3 = run_probe(a3, s77, b3)

    return {
        "natureza": "teste_tecnico_sem_inferencia",
        "c77_antes": r1["prompt_sha256_rendered"],
        "c85_meio": r2["prompt_sha256_rendered"],
        "c77_depois": r3["prompt_sha256_rendered"],
        "c77_estavel": r1["prompt_sha256_rendered"] == r3["prompt_sha256_rendered"],
        "c77_difere_c85": r1["prompt_sha256_rendered"] != r2["prompt_sha256_rendered"],
        "adapters_distintos": a1 is not a2 and a2 is not a3,
        "interceptors_distintos": (
            b1.interceptor is not b2.interceptor
            and b2.interceptor is not b3.interceptor
        ),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OS041 — integração SV-01 sem inferência")
    ap.add_argument("--manifest", default=MANIFEST_PATH)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--execute", action="store_true",
                    help="tentativa experimental; sempre bloqueada nesta OS")
    ap.add_argument("--isolation", action="store_true",
                    help="roda também o probe C77->C85->C77")
    args = ap.parse_args(argv)

    manifest = load_manifest(args.manifest)
    if args.execute:
        try:
            execution_guard.assert_execution_authorized(manifest)
        except execution_guard.ExecutionBlocked as exc:
            print(f"BLOQUEADO: {exc}")
            return 2
        print("BLOQUEADO: não há caminho de execução experimental na OS041")
        return 2

    payload = run_integration(args.manifest)
    if args.isolation:
        payload["isolation_probe"] = run_isolation_probe(args.manifest)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "status": payload["status"],
        "n_probe_tecnico": payload["n_probe_tecnico"],
        "not_64_runs": payload["not_64_runs"],
        "inference_executed": payload["inference_executed"],
        "real_model_generate_called": payload["real_model_generate_called"],
        "out": args.out,
        "manifest_sha256": payload["manifest_sha256"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
