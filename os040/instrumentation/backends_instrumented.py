# -*- coding: utf-8 -*-
"""OS028-SV-01 — backend local para Qwen3-8B e Mistral 7B Instruct.

Sem rede no import. O carregamento real exige torch/transformers/GPU e roda
apenas no Kaggle ou em máquina com GPU. O adapter é o mesmo `kaggle/model_adapter.py`
já validado para o Qwen; este módulo só fornece o loader e as especificações.
"""
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, asdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CANDIDATOS_ADAPTER = [
    os.path.dirname(os.path.abspath(__file__)),   # kernel Kaggle autocontido
    os.path.join(ROOT, "kaggle"),                 # repo local
]
for _p in _CANDIDATOS_ADAPTER:
    if os.path.isfile(os.path.join(_p, "model_adapter.py")):
        sys.path.insert(0, _p)
        break

from model_adapter_instrumented import ModelAdapter, GenerationParams  # noqa: E402

MIN_VRAM_GB = 20.0


@dataclass(frozen=True)
class ModelSpec:
    chave: str
    model_id: str
    revision: str | None
    licenca: str
    dtype: str
    quant: str | None
    chat_template: str
    enable_thinking: bool | None
    params_b: float
    contexto: int
    min_vram_gb: float
    fonte: str
    observacao: str

    def as_dict(self):
        return asdict(self)


QWEN = ModelSpec(
    chave="qwen",
    model_id="Qwen/Qwen3-8B",
    revision="b968826d9c46dd6066d109eabc6255188de91218",
    licenca="apache-2.0",
    dtype="float16",
    quant=None,
    chat_template="qwen",
    enable_thinking=False,
    params_b=8.2,
    contexto=32768,
    min_vram_gb=MIN_VRAM_GB,
    fonte="huggingface/kaggle-cache",
    observacao=("Validado na infraestrutura Kaggle: 2×T4, 31,28 GB, 10/10 gerações, "
                "fp16, sem quantização (relatório qwen3_infra_report.json)."),
)

MISTRAL = ModelSpec(
    chave="mistral",
    model_id="mistralai/Mistral-7B-Instruct-v0.3",
    revision="c170c708c41dac9275d15a8fff4eca08d52bab71",
    licenca="apache-2.0",
    dtype="float16",
    quant=None,
    chat_template="mistral",
    enable_thinking=None,
    params_b=7.25,
    contexto=32768,
    min_vram_gb=MIN_VRAM_GB,
    fonte="huggingface/kaggle-local",
    observacao=("Substitui o Gemini. Validado no Kaggle: 2×T4, 31,28 GB, "
                "fp16, sem quantização, 5/5 gerações; relatório mistral_infra_report.json."),
)

SPECS = {"qwen": QWEN, "mistral": MISTRAL}


def get_spec(chave: str) -> ModelSpec:
    if chave not in SPECS:
        raise ValueError(f"modelo inválido: {chave}")
    return SPECS[chave]


def params_padrao(seed: int = 42) -> GenerationParams:
    """Parâmetros congelados do SV-01 (novo protocolo, não CAL3)."""
    return GenerationParams(
        max_new_tokens=256,
        do_sample=True,
        temperature=0.7,
        top_p=0.95,
        top_k=40,
        repetition_penalty=1.0,
        seed=seed,
    )


def _aplicar_chat_template(tok, prompt: str, spec: ModelSpec) -> str:
    mensagens = [{"role": "user", "content": prompt}]
    kwargs = {"tokenize": False, "add_generation_prompt": True}
    if spec.chat_template == "qwen":
        try:
            return tok.apply_chat_template(
                mensagens, enable_thinking=bool(spec.enable_thinking), **kwargs)
        except TypeError:
            # tokenizer antigo sem o argumento enable_thinking
            return tok.apply_chat_template(mensagens, **kwargs)
    return tok.apply_chat_template(mensagens, **kwargs)


def hash_rendered_prompt(tok, prompt: str, spec: ModelSpec) -> tuple[str, str]:
    """Renderiza e devolve (texto_renderizado, sha256_exato).

    Calculado antes de `model.generate`; não normaliza nem reformata.
    """
    rendered = _aplicar_chat_template(tok, prompt, spec)
    return rendered, hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def carregar_modelo_local(spec: ModelSpec, revision: str | None = None,
                          model_path: str | None = None,
                          seed: int = 42, max_new_tokens: int = 256,
                          temperature: float = 0.7, top_p: float = 0.95,
                          top_k: int = 40):
    """Carrega o modelo local e devolve (ModelAdapter, info).

    Exige GPU com VRAM >= spec.min_vram_gb. Não quantiza silenciosamente: se
    não houver VRAM, aborta (mesma política do Qwen validado).
    """
    try:
        import torch
    except Exception as exc:
        raise RuntimeError(
            "PyTorch indisponível neste ambiente. O backend local roda no Kaggle "
            "(GPU); não há fallback de modelo.") from exc
    from transformers import AutoTokenizer, AutoModelForCausalLM

    if not torch.cuda.is_available():
        raise RuntimeError("Nenhuma GPU visível para o PyTorch.")
    vram = sum(torch.cuda.get_device_properties(i).total_memory
               for i in range(torch.cuda.device_count())) / 1e9
    if vram < spec.min_vram_gb:
        raise RuntimeError(
            f"VRAM total {vram:.1f} GB < {spec.min_vram_gb:.1f} GB: não comporta "
            f"{spec.model_id} em fp16 sem quantização. Abortando (sem substituição).")

    bf16 = all(torch.cuda.get_device_properties(i).major >= 8
               for i in range(torch.cuda.device_count()))
    dtype = "bfloat16" if bf16 else "float16"

    origem = model_path or spec.model_id
    tok = AutoTokenizer.from_pretrained(origem, revision=revision or spec.revision)
    tok.padding_side = "left"
    kwargs = dict(revision=revision or spec.revision, low_cpu_mem_usage=True,
                  device_map="auto")
    try:
        model = AutoModelForCausalLM.from_pretrained(
            origem, dtype=getattr(torch, dtype), **kwargs)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            origem, torch_dtype=getattr(torch, dtype), **kwargs)
    model.eval()

    def loader(model_id, rev, quant, dtype_):
        def generate_fn(prompt, params):
            # Hash do prompt EXATO renderizado, antes de qualquer chamada ao modelo.
            # Nao normalizar, reformatar ou modificar a string antes do hash.
            entrada, prompt_sha256_rendered = hash_rendered_prompt(
                tok, prompt, spec)
            prompt_sha256_pre_template = hashlib.sha256(
                prompt.encode("utf-8")).hexdigest()
            enc = tok(entrada, return_tensors="pt").to(model.device)
            torch.manual_seed(params.seed)
            with torch.inference_mode():
                out = model.generate(**enc, **params.to_generate_kwargs(),
                                     pad_token_id=tok.eos_token_id)
            novos = out[0][enc["input_ids"].shape[1]:]
            texto = tok.decode(novos, skip_special_tokens=True).strip()
            terminou = bool(novos.numel()) and int(novos[-1]) == tok.eos_token_id
            return {"text": texto,
                    "prompt_tokens": int(enc["input_ids"].shape[1]),
                    "completion_tokens": int(novos.numel()),
                    "finish_reason": "eos" if terminou else "length",
                    "prompt_sha256_rendered": prompt_sha256_rendered,
                    "prompt_sha256_pre_template": prompt_sha256_pre_template,
                    "prompt_chars_rendered": len(entrada)}

        return {"tokenizer": tok, "model": model, "generate_fn": generate_fn,
                "unload_fn": None, "device": str(model.device),
                "dtype": dtype, "quant": quant,
                "vram_alloc_gb": round(torch.cuda.memory_allocated() / 1e9, 2),
                "vram_reserved_gb": round(torch.cuda.memory_reserved() / 1e9, 2),
                "weights_bytes": sum(p.numel() * p.element_size()
                                     for p in model.parameters())}

    params = params_padrao(seed)
    params = GenerationParams(max_new_tokens=max_new_tokens,
                              do_sample=True, temperature=temperature,
                              top_p=top_p, top_k=top_k,
                              repetition_penalty=1.0, seed=seed)
    adapter = ModelAdapter(spec.model_id, revision=revision or spec.revision,
                           params=params, quant=None, dtype=dtype,
                           source="kaggle-local", allow_experimental=True)
    info = adapter.load(loader)
    rev = getattr(getattr(model, "config", None), "_commit_hash", None) or revision
    rev_fonte = "config._commit_hash" if rev else ("argumento" if revision else None)
    if not rev:
        try:
            rev = (getattr(tok, "init_kwargs", {}) or {}).get("_commit_hash")
            if rev:
                rev_fonte = "tokenizer.init_kwargs"
        except Exception:
            pass
    if not rev:
        try:
            from huggingface_hub import HfApi
            rev = HfApi().model_info(spec.model_id).sha
            rev_fonte = "huggingface_hub"
        except Exception:
            rev_fonte = "nao_resolvida"
    adapter.revision = rev
    info = adapter.info()
    info["revision_fonte"] = rev_fonte
    info["model_spec"] = spec.as_dict()
    info["origem"] = origem
    info["vram_total_gb"] = round(vram, 2)
    return adapter, info


def info_planejada(spec: ModelSpec) -> dict:
    return {
        "model_spec": spec.as_dict(),
        "params_padrao": params_padrao().as_dict(),
        "params_fingerprint": params_padrao().fingerprint(),
        "min_vram_gb": spec.min_vram_gb,
    }
