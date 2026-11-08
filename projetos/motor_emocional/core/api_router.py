"""API Router - Google Gemini / Multi-project Failover & Load Balancing (OS021).

Camada PURA de transporte/seleção de credencial. Não altera:
- modelo        - prompt        - temperatura
- max_tokens    - parâmetros    - estado emocional
- PolicyEngine  - MemoryContextBridge

Responsabilidades:
1. Carregar N credenciais externamente (env var ou arquivo de segredo).
2. Rotação round-robin equilibrada.
3. Failover SOMENTE em erros recuperáveis (429/500/502/503/504).
4. Sanitizar chaves de qualquer log/exceção.
5. Expor metadados de auditoria (provider/projeto/tentativa/failover).
6. Abortar explicitamente se não houver credencial.
"""
import os
import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("ApiRouter")

# Versão explícita e fixa. NUNCA usar aliases "-latest": eles fazem drift
# (ex.: gemini-3.5-flash respondeu modelVersion=gemini-3.6-flash).
DEFAULT_MODEL = "gemini-3.1-flash-lite"

GEMINI_OPENAI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)
GEMINI_REST_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Códigos que autorizam failover para OUTRA credencial.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Códigos que NÃO devem ser repetidos: falha imediata e definitiva.
NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404})


class ApiRouter:
    """Roteador multi-projeto com balanceamento e failover seguro."""

    def __init__(
        self,
        provider: str = "google",
        model: str = DEFAULT_MODEL,
        keys: Optional[List[str]] = None,
        secret_file: str = "/home/maktub/.secret/segredos.env",
        require_all: bool = False,
        expected_projects: int = 4,
    ):
        self.provider = provider
        self.model = model
        self.projects: List[Dict[str, object]] = []
        self._current_index = 0

        loaded = list(keys or [])

        # 1. Variáveis de ambiente (preferencial)
        if not loaded:
            for idx in range(1, expected_projects + 1):
                for prefix in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
                    val = os.getenv(f"{prefix}_{idx}")
                    if val and val.strip():
                        loaded.append(val.strip())
                        break

        # 2. Arquivo de segredo fora do repositório
        if not loaded and secret_file and os.path.exists(secret_file):
            try:
                with open(secret_file, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            loaded.append(val)
            except Exception as exc:
                logger.warning("[ApiRouter] Falha ao ler arquivo de segredo: %s", type(exc).__name__)

        # Deduplicar preservando ordem
        seen, unique = set(), []
        for key in loaded:
            if key not in seen:
                seen.add(key)
                unique.append(key)

        for idx, key in enumerate(unique, start=1):
            self.projects.append({
                "id": f"google_project_{idx}",
                "key": key,
                "calls": 0,
                "failures": 0,
            })

        # Abortar explicitamente sem credenciais
        if not self.projects:
            raise RuntimeError(
                "[ApiRouter] ERRO CRÍTICO: nenhuma credencial configurada. "
                "Defina GOOGLE_API_KEY_1..N ou um arquivo de segredo. Abortando."
            )

        # Exigir o pool completo quando o experimento depende dele
        if require_all and len(self.projects) < expected_projects:
            raise RuntimeError(
                f"[ApiRouter] ERRO CRÍTICO: esperados {expected_projects} projetos, "
                f"encontrados {len(self.projects)}. Abortando."
            )

        logger.info("[ApiRouter] %d projeto(s) | modelo fixo: %s",
                    len(self.projects), self.model)

    # ------------------------------------------------------------------ #
    # Seleção
    # ------------------------------------------------------------------ #
    @property
    def total_projects(self) -> int:
        return len(self.projects)

    def get_next_project(self) -> Dict[str, object]:
        """Próximo projeto em rotação round-robin equilibrada."""
        if not self.projects:
            raise RuntimeError("[ApiRouter] Nenhum projeto disponível.")
        proj = self.projects[self._current_index % len(self.projects)]
        self._current_index = (self._current_index + 1) % len(self.projects)
        proj["calls"] += 1
        return proj

    def record_failure(self, project: Dict[str, object]) -> None:
        project["failures"] += 1

    # ------------------------------------------------------------------ #
    # Segurança
    # ------------------------------------------------------------------ #
    def mask_keys_in_text(self, text) -> str:
        """Remove qualquer ocorrência de chave de API de uma string."""
        if text is None:
            return ""
        sanitized = str(text)
        for proj in self.projects:
            raw = str(proj["key"])
            if raw and len(raw) > 4:
                sanitized = sanitized.replace(raw, f"***[{proj['id']}]***")
        return sanitized

    def public_config(self) -> Dict[str, object]:
        """Configuração segura (sem chaves) — a única forma que pode ir ao JSONL."""
        return {
            "provider": self.provider,
            "model": self.model,
            "projects": [p["id"] for p in self.projects],
        }

    def assert_no_leak(self, payload) -> None:
        """Garante que um objeto serializável não contém nenhuma chave."""
        blob = json.dumps(payload, ensure_ascii=False, default=str)
        for proj in self.projects:
            if str(proj["key"]) in blob:
                raise AssertionError(
                    f"[ApiRouter] VIOLAÇÃO: chave de {proj['id']} presente no payload."
                )

    # ------------------------------------------------------------------ #
    # Headers — formato depende do transporte real
    # ------------------------------------------------------------------ #
    def get_headers(self, key: str, use_openai_format: bool = True) -> Dict[str, str]:
        """Headers de autenticação.

        use_openai_format=True  -> endpoint /v1beta/openai (Bearer).
        use_openai_format=False -> REST nativo /v1beta/models (x-goog-api-key).
        Nunca enviar os dois: o endpoint OpenAI rejeita x-goog-api-key sozinho.
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MotorEmocional-ApiRouter/1.0",
        }
        if use_openai_format:
            headers["Authorization"] = f"Bearer {key}"
        else:
            headers["x-goog-api-key"] = key
        return headers

    # ------------------------------------------------------------------ #
    # Política de erro
    # ------------------------------------------------------------------ #
    @staticmethod
    def is_retryable_status(status_code: int) -> bool:
        """True apenas para erros operacionais transitórios."""
        return status_code in RETRYABLE_STATUS

    # ------------------------------------------------------------------ #
    # Auditoria
    # ------------------------------------------------------------------ #
    def distribution(self) -> Dict[str, int]:
        return {p["id"]: p["calls"] for p in self.projects}
