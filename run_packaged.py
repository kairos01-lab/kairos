# -*- coding: utf-8 -*-
"""OS050 — launcher do pacote portátil do runner SV-01.

Define os caminhos internos do pacote para OS040/OS041 e chama o runner real
da OS049 sem alterar sua lógica. Não autoriza execução: o guard central
continua sendo consultado pelo runner e `AUTHORIZATION_TOKEN` continua None.
"""
from __future__ import annotations

import os
import sys

PKG = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.join(PKG, "projetos", "motor_emocional")
SV01 = os.path.join(PROJ, "os028", "sv01")

os.environ["SV01_OS040_DIR"] = os.path.join(PKG, "os040")
os.environ["SV01_OS041_DIR"] = os.path.join(PKG, "os041")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

for _p in (
    os.path.join(PKG, "os040", "instrumentation"),
    os.path.join(PKG, "os041"),
    PROJ,
    SV01,
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sv01_runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
