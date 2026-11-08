"""Model Adapter — camada neutra entre o protocolo experimental e o modelo local.

OS: preparação de ambiente Kaggle para Qwen3-8B (somente infraestrutura).

Regras desta camada:
  - NÃO contém lógica do E3 (nem classificador, nem condições, nem prompts).
  - Recebe texto, devolve texto + metadados.
  - Recusa prompts com assinatura experimental (trava de segurança).
  - Não guarda estado global: uma instância = um modelo carregado.

Este arquivo é a ÚNICA fonte do código do adapter: ele é embutido no notebook
pelo `build_notebook.py`, garantindo que o que foi testado é o que roda.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field

ADAPTER_VERSION = "1.0.0-os040"
INSTRUMENTATION_VERSION = "OS040-1"


# ───────────────────────── trava experimental ─────────────────────────
class ExperimentalPromptBlocked(RuntimeError):
    """Levantada quando um texto tem assinatura de prompt/artefato experimental."""


FORBIDDEN_PATTERNS = {
    "prompt do E3": re.compile(
        r"tenho\s+r\$\s*7[\.\s]?000|comprar\s+um\s+ve[ií]culo\s+para\s+trabalhar",
        re.I),
    "memoria do E3": re.compile(r"\bfusca\b|\bbesouro\b", re.I),
    "condicao experimental": re.compile(r"\b(e-?3|e3-?r|e-?4)\s*[-:]?\s*[abcd]?\b", re.I),
    "artefato experimental": re.compile(
        r"e3_resultados|e3v2_resultados|os026_reanalise|os027_|"
        r"target_fusca_corrected|memory_use_components", re.I),
}

# Caminhos de artefatos já arquivados que NUNCA podem ser escritos por engano.
PROTECTED_PATHS = re.compile(
    r"e3_resultados|e3v2_resultados|os026_reanalise|os027_resultado|"
    r"os027_auditoria|auditoria_e3v2", re.I)


def assert_infrastructure_only(text, where="texto"):
    """Recusa qualquer texto com assinatura de experimento. Trava da OS §12."""
    if not isinstance(text, str):
        raise TypeError(f"{where} deve ser str, recebeu {type(text).__name__}")
    hits = [nome for nome, pat in FORBIDDEN_PATTERNS.items() if pat.search(text)]
    if hits:
        raise ExperimentalPromptBlocked(
            f"BLOQUEADO ({where}): assinatura experimental detectada -> {hits}. "
            "Esta OS é somente de infraestrutura."
        )


def assert_safe_path(path):
    """Impede gravar por cima dos artefatos experimentais arquivados."""
    if PROTECTED_PATHS.search(str(path)):
        raise ExperimentalPromptBlocked(
            f"BLOQUEADO: escrita em artefato experimental protegido ({path}). "
            "Nenhum arquivo do E3-R pode ser alterado."
        )
    return path


# ───────────────────────── parâmetros congelados ─────────────────────────
@dataclass(frozen=True)
class GenerationParams:
    """Parâmetros de geração explícitos e congelados (OS §7).

    Decodificação gulosa por padrão: é a opção mais reprodutível para um teste
    de infraestrutura. `temperature`/`top_p`/`top_k` ficam registrados mesmo
    sem efeito sob `do_sample=False`.
    """
    max_new_tokens: int = 64
    do_sample: bool = False
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    repetition_penalty: float = 1.0
    seed: int = 42

    def as_dict(self):
        return asdict(self)

    def fingerprint(self):
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_generate_kwargs(self):
        """kwargs aceitos por `transformers.GenerationMixin.generate`."""
        kw = {
            "max_new_tokens": self.max_new_tokens,
            "do_sample": self.do_sample,
            "repetition_penalty": self.repetition_penalty,
        }
        if self.do_sample:
            kw.update(temperature=self.temperature, top_p=self.top_p, top_k=self.top_k)
        return kw


# ───────────────────────── adapter ─────────────────────────
class ModelAdapter:
    """Interface conceitual da OS §6: load / generate / unload / info.

    O carregamento real é injetado por `loader`, para que esta classe seja
    testável sem torch, sem GPU e sem rede.
    """

    def __init__(self, model_id, revision=None, params=None,
                 quant=None, dtype=None, source=None,
                 allow_experimental=False):
        self.model_id = model_id
        self.revision = revision
        self.params = params or GenerationParams()
        self.quant = quant
        self.dtype = dtype
        self.source = source          # "local_dataset" | "huggingface"
        # Trava experimental: só o runner AUTORIZADO (gate de autorização)
        # constrói o adapter com allow_experimental=True. Infra usa o default.
        self.allow_experimental = allow_experimental
        self._tok = None
        self._model = None
        self._generate_fn = None
        self._unload_fn = None
        self._load_seconds = None
        self._load_meta = {}

    # -- ciclo de vida -------------------------------------------------
    def load(self, loader):
        """`loader(model_id, revision, quant, dtype)` -> dict com as chaves:
        tokenizer, model, generate_fn, unload_fn, device, dtype, quant,
        vram_alloc_gb, vram_reserved_gb, weights_bytes.
        """
        t0 = time.perf_counter()
        bundle = loader(self.model_id, self.revision, self.quant, self.dtype)
        self._load_seconds = time.perf_counter() - t0

        self._tok = bundle["tokenizer"]
        self._model = bundle["model"]
        self._generate_fn = bundle["generate_fn"]
        self._unload_fn = bundle.get("unload_fn")
        self.dtype = bundle.get("dtype", self.dtype)
        self.quant = bundle.get("quant", self.quant)

        self._load_meta = {
            "device": bundle.get("device"),
            "vram_alloc_gb": bundle.get("vram_alloc_gb"),
            "vram_reserved_gb": bundle.get("vram_reserved_gb"),
            "weights_bytes": bundle.get("weights_bytes"),
            "load_seconds": round(self._load_seconds, 3),
        }
        return self.info()

    def unload(self):
        if self._unload_fn is not None:
            self._unload_fn()
        self._tok = self._model = self._generate_fn = self._unload_fn = None
        return {"unloaded": True}

    @property
    def loaded(self):
        return self._generate_fn is not None

    # -- inferência -----------------------------------------------------
    def generate(self, prompt, parameters=None):
        """Recebe texto, devolve texto + metadados. Sem lógica experimental."""
        if not self.allow_experimental:
            assert_infrastructure_only(prompt, where="prompt")
        if not self.loaded:
            raise RuntimeError("adapter não carregado: chame load() primeiro")

        p = parameters or self.params
        t0 = time.perf_counter()
        out = self._generate_fn(prompt, p)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if not isinstance(out, dict) or "text" not in out:
            raise RuntimeError("generate_fn deve devolver dict com a chave 'text'")

        rendered_hash = out.get("prompt_sha256_rendered")
        if not isinstance(rendered_hash, str) or len(rendered_hash) != 64:
            raise RuntimeError(
                "prompt_sha256_rendered ausente/inválido: execução experimental bloqueada"
            )

        text = out.get("text") or ""
        return {
            "text": text,
            "prompt_sha256_rendered": rendered_hash,
            "prompt_sha256_pre_template": out.get("prompt_sha256_pre_template"),
            "prompt_chars_rendered": out.get("prompt_chars_rendered"),
            "empty": not text.strip(),
            "latency_ms": round(latency_ms, 2),
            "prompt_tokens": out.get("prompt_tokens"),
            "completion_tokens": out.get("completion_tokens"),
            "finish_reason": out.get("finish_reason"),
            "params": p.as_dict(),
            "params_fingerprint": p.fingerprint(),
            "model": self.model_id,
            "revision": self.revision,
            "quant": self.quant,
            "dtype": self.dtype,
            "adapter_version": ADAPTER_VERSION,
        }

    # -- descrição ------------------------------------------------------
    def info(self):
        return {
            "adapter_version": ADAPTER_VERSION,
            "model_id": self.model_id,
            "revision": self.revision,
            "source": self.source,
            "quant": self.quant,
            "dtype": self.dtype,
            "params": self.params.as_dict(),
            "params_fingerprint": self.params.fingerprint(),
            "loaded": self.loaded,
            "allow_experimental": self.allow_experimental,
            **self._load_meta,
        }

    def __repr__(self):
        return (f"ModelAdapter(model_id={self.model_id!r}, quant={self.quant!r}, "
                f"dtype={self.dtype!r}, loaded={self.loaded})")
