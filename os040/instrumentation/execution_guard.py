# -*- coding: utf-8 -*-
"""OS040 — bloqueio explícito de execução experimental.

O manifesto nasce em PREPARADO_NAO_EXECUTADO. Nenhuma execução pode ocorrer
sem uma autorização humana posterior, representada por status AUTHORIZED e
token correspondente. Em OS040 o token é None, então toda tentativa falha.
"""
from __future__ import annotations

STATUS_PREPARED = "PREPARADO_NAO_EXECUTADO"
STATUS_AUTHORIZED = "AUTHORIZED"

# Em OS040 não há autorização. Uma OS posterior deve definir o token/estado.
AUTHORIZATION_TOKEN = None


class ExecutionBlocked(RuntimeError):
    """Levantada quando se tenta executar sem autorização explícita."""


def assert_execution_authorized(manifest: dict, token: str | None = None) -> bool:
    status = (manifest or {}).get("status")
    if status != STATUS_AUTHORIZED:
        raise ExecutionBlocked(
            f"BLOQUEADO: manifesto em '{status}', não '{STATUS_AUTHORIZED}'."
        )
    if not AUTHORIZATION_TOKEN or token != AUTHORIZATION_TOKEN:
        raise ExecutionBlocked(
            "BLOQUEADO: token de autorização ausente ou inválido."
        )
    return True
