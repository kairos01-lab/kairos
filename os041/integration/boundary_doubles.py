# -*- coding: utf-8 -*-
"""OS041 — duplos de teste APENAS no limite de inferência.

O que é real:
  - `tokenizer.json` e `tokenizer_config.json` do Qwen3-8B no cache local;
  - template de chat real, renderizado por `RealQwenTokenizer`.

O que é duplo:
  - módulo `torch` (CUDA/VRAM/inference_mode);
  - módulo `transformers` (AutoTokenizer/AutoModelForCausalLM);
  - `model.generate`, substituído pelo `Interceptor`.

O `Interceptor` recebe os mesmos kwargs que `model.generate` receberia,
captura os `input_ids`, reconstrói o hash independente a partir da string
renderizada registrada pelo tokenizer real e devolve um marcador de software.
Nunca há pesos, GPU ou inferência.
"""
from __future__ import annotations

import hashlib
import sys
import types
from contextlib import contextmanager

try:
    from .tensor_doubles import FakeOutput
    from .tokenizer_real import (
        DEFAULT_SNAPSHOT, QWEN_REVISION, RealQwenTokenizer, sha256_text,
    )
except ImportError:
    from tensor_doubles import FakeOutput
    from tokenizer_real import (
        DEFAULT_SNAPSHOT, QWEN_REVISION, RealQwenTokenizer, sha256_text,
    )

MARKER_TEXT = "OS041_INTERCEPTED_NO_INFERENCE"


class Interceptor:
    """Substitui `model.generate` e captura a chamada sem gerar resposta."""

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.called = False
        self.call_count = 0
        self.real_generate_called = False
        self.calls = []

    @property
    def last_call(self):
        return self.calls[-1] if self.calls else None

    def __call__(self, **kwargs):
        self.called = True
        self.call_count += 1

        input_ids = kwargs.get("input_ids")
        if input_ids is None:
            raise RuntimeError("interceptor: input_ids ausente")
        ids = input_ids.tolist() if hasattr(input_ids, "tolist") else list(input_ids)

        rendered = self.tokenizer.last_rendered
        if rendered is None:
            raise RuntimeError(
                "interceptor: string renderizada ausente; não é possível "
                "calcular o hash independente"
            )
        independent = sha256_text(rendered)
        expected_ids = self.tokenizer.encode(rendered, add_special_tokens=True)

        generation_kwargs = {
            k: v for k, v in kwargs.items()
            if k not in ("input_ids", "attention_mask")
        }
        record = {
            "call_index": self.call_count,
            "input_ids_len": len(ids),
            "input_ids_head": ids[:12],
            "rendered_chars": len(rendered),
            "rendered_head": rendered[:160],
            "rendered_sha256": independent,
            "rendered_matches_input_ids": expected_ids == ids,
            "generation_kwargs": generation_kwargs,
            "pad_token_id": kwargs.get("pad_token_id"),
        }
        self.calls.append(record)

        # Marcador de software: nunca é resposta de modelo.
        marker_ids = self.tokenizer.encode(MARKER_TEXT, add_special_tokens=False)
        sequence = ids + marker_ids + [self.tokenizer.eos_token_id]
        return FakeOutput(sequence)


class FakeModel:
    """Modelo sem pesos. `generate` aponta para o interceptor."""

    def __init__(self, interceptor: Interceptor, revision: str):
        self.interceptor = interceptor
        self.device = "cpu"
        self.config = types.SimpleNamespace(_commit_hash=revision)
        self.generate = interceptor
        self.real_generate_called = False

    def eval(self):
        return self

    def parameters(self):
        return []

    def real_generate(self, *args, **kwargs):
        self.real_generate_called = True
        raise AssertionError(
            "model.generate real não pode ser chamado na OS041")


def _make_torch_module():
    class Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_properties(index):
            return types.SimpleNamespace(
                total_memory=24_000_000_000, major=8, minor=0)

        @staticmethod
        def memory_allocated():
            return 0

        @staticmethod
        def memory_reserved():
            return 0

    class InferenceMode:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    modulo = types.ModuleType("torch")
    modulo.cuda = Cuda()
    modulo.bfloat16 = "bfloat16"
    modulo.float16 = "float16"
    modulo.manual_seed = lambda seed: None
    modulo.inference_mode = lambda: InferenceMode()
    return modulo


def _make_transformers_module(tokenizer, model):
    modulo = types.ModuleType("transformers")

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(origem, revision=None, **kwargs):
            return tokenizer

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(origem, **kwargs):
            return model

    modulo.AutoTokenizer = AutoTokenizer
    modulo.AutoModelForCausalLM = AutoModelForCausalLM
    return modulo


class Boundary:
    def __init__(self, snapshot_dir, revision, tokenizer, interceptor, model,
                 torch_module, transformers_module):
        self.snapshot_dir = snapshot_dir
        self.revision = revision
        self.tokenizer = tokenizer
        self.interceptor = interceptor
        self.model = model
        self.torch_module = torch_module
        self.transformers_module = transformers_module


@contextmanager
def offline_boundary(snapshot_dir: str | None = None,
                     revision: str = QWEN_REVISION):
    """Instala os duplos de torch/transformers e o tokenizer real.

    Sai restaurando `sys.modules` exatamente como estava.
    """
    snapshot_dir = snapshot_dir or DEFAULT_SNAPSHOT
    tokenizer = RealQwenTokenizer(snapshot_dir, revision)
    interceptor = Interceptor(tokenizer)
    model = FakeModel(interceptor, revision)
    torch_module = _make_torch_module()
    transformers_module = _make_transformers_module(tokenizer, model)

    old_torch = sys.modules.get("torch")
    old_transformers = sys.modules.get("transformers")
    sys.modules["torch"] = torch_module
    sys.modules["transformers"] = transformers_module
    try:
        yield Boundary(
            snapshot_dir=snapshot_dir,
            revision=revision,
            tokenizer=tokenizer,
            interceptor=interceptor,
            model=model,
            torch_module=torch_module,
            transformers_module=transformers_module,
        )
    finally:
        if old_torch is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = old_torch
        if old_transformers is None:
            sys.modules.pop("transformers", None)
        else:
            sys.modules["transformers"] = old_transformers


def sha256_repr(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
