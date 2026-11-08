# -*- coding: utf-8 -*-
"""OS041 — tokenizer e template REAIS do Qwen3-8B, carregados do cache local.

Não usa `transformers` nem `torch` (ausentes neste ambiente). Usa:
  - `tokenizers` 0.23.1 sobre o `tokenizer.json` real;
  - `jinja2` 3.1.6 sobre o `chat_template` real do `tokenizer_config.json`.

O objetivo é produzir a string exata que o backend instrumentado da OS040
enviaria ao tokenizer, sem substituir o vocabulário/BPE por um tokenizer falso.

Limite declarado: `transformers.AutoTokenizer.apply_chat_template` NÃO foi
executado. A equivalência byte-a-byte com esse wrapper não é afirmada; o que se
verifica é o template real, o tokenizer real e o formato canônico do Qwen3.
"""
from __future__ import annotations

import hashlib
import json
import os

from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

try:  # pacote (`integration.tokenizer_real`)
    from .tensor_doubles import FakeBatch, FakeTensor
except ImportError:  # execução direta com o diretório no sys.path
    from tensor_doubles import FakeBatch, FakeTensor

QWEN_MODEL_ID = "Qwen/Qwen3-8B"
QWEN_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
DEFAULT_SNAPSHOT = os.path.expanduser(
    os.path.join(
        "~", ".cache", "huggingface", "hub",
        "models--Qwen--Qwen3-8B", "snapshots", QWEN_REVISION,
    )
)


class TokenizerUnavailable(RuntimeError):
    """O tokenizer/template real não está disponível localmente."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RealQwenTokenizer:
    """Wrapper mínimo com a interface que `backends_instrumented` usa.

    Interface exigida pelo backend:
      - `apply_chat_template(mensagens, tokenize=False,
         add_generation_prompt=True, enable_thinking=...) -> str`
      - `__call__(texto, return_tensors="pt") -> dict-like`
      - `decode(ids, skip_special_tokens=True) -> str`
      - `eos_token_id`, `padding_side`
    """

    def __init__(self, snapshot_dir: str | None = None,
                 revision: str = QWEN_REVISION):
        self.snapshot_dir = snapshot_dir or DEFAULT_SNAPSHOT
        self.revision = revision
        tok_path = os.path.join(self.snapshot_dir, "tokenizer.json")
        cfg_path = os.path.join(self.snapshot_dir, "tokenizer_config.json")
        if not os.path.isfile(tok_path):
            raise TokenizerUnavailable(f"tokenizer.json ausente: {tok_path}")
        if not os.path.isfile(cfg_path):
            raise TokenizerUnavailable(
                f"tokenizer_config.json ausente: {cfg_path}")
        try:
            self._tok = Tokenizer.from_file(tok_path)
            with open(cfg_path, encoding="utf-8") as fh:
                self._cfg = json.load(fh)
        except Exception as exc:
            raise TokenizerUnavailable(
                f"falha ao carregar tokenizer/template reais: {exc}") from exc

        self._template_text = self._cfg.get("chat_template")
        if not self._template_text:
            raise TokenizerUnavailable(
                "chat_template ausente no tokenizer_config.json real")
        self._template = ImmutableSandboxedEnvironment(
            trim_blocks=True, lstrip_blocks=True,
        ).from_string(self._template_text)

        self.padding_side = "left"
        self.eos_token_id = self._tok.token_to_id("<|im_end|>")
        self.pad_token_id = self._tok.token_to_id("<|endoftext|>")
        self.bos_token_id = None
        self.init_kwargs = {"_commit_hash": revision}

        # Estado da última chamada, para o interceptor independente.
        self.last_rendered = None
        self.last_rendered_sha256 = None
        self.last_input_ids = None
        self.last_call_kwargs = None

    # -- template ------------------------------------------------------
    def apply_chat_template(self, messages, tokenize: bool = False,
                            add_generation_prompt: bool = True,
                            enable_thinking: bool = False,
                            tools=None, **kwargs) -> str:
        if tokenize:
            raise NotImplementedError(
                "OS041 só exercita tokenize=False, como o backend da OS040")
        if kwargs.get("continue_final_message"):
            raise NotImplementedError(
                "continue_final_message não é usado pelo backend do SV-01")
        rendered = self._template.render(
            messages=messages,
            add_generation_prompt=add_generation_prompt,
            enable_thinking=enable_thinking,
            tools=tools,
            **kwargs,
        )
        rendered = str(rendered)
        self.last_rendered = rendered
        self.last_rendered_sha256 = sha256_text(rendered)
        return rendered

    # -- tokenização ---------------------------------------------------
    def __call__(self, text, return_tensors=None, **kwargs):
        if return_tensors != "pt":
            raise NotImplementedError(
                f"OS041 só exercita return_tensors='pt'; recebeu {return_tensors!r}")
        ids = self.encode(text, add_special_tokens=True)
        self.last_input_ids = list(ids)
        self.last_call_kwargs = {"return_tensors": return_tensors, **kwargs}
        return FakeBatch({
            "input_ids": FakeTensor(ids, shape=(1, len(ids))),
            "attention_mask": FakeTensor([1] * len(ids), shape=(1, len(ids))),
        })

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        return list(self._tok.encode(
            text, add_special_tokens=add_special_tokens).ids)

    def decode(self, ids, skip_special_tokens: bool = True) -> str:
        if isinstance(ids, FakeTensor):
            ids = ids.tolist()
        elif isinstance(ids, int):
            ids = [ids]
        else:
            ids = [int(x) for x in ids]
        return self._tok.decode(ids, skip_special_tokens=skip_special_tokens)

    def token_to_id(self, token: str):
        return self._tok.token_to_id(token)

    def get_vocab_size(self) -> int:
        return self._tok.get_vocab_size()

    def __repr__(self):
        return (
            f"RealQwenTokenizer(model={QWEN_MODEL_ID!r}, "
            f"revision={self.revision!r}, vocab={self.get_vocab_size()})"
        )
