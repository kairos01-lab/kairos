# -*- coding: utf-8 -*-
"""OS040 — classificação semântica SV-01 com mapa por execução.

Não modifica o parser histórico. Envolve `sv01_parser_v2.parse_choice_strict`
e traduz a letra para a alternativa semântica usando o `letter_to_option`
daquela execução. Não infere semântica de uma letra fixa.
"""
from __future__ import annotations

import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_SV01 = os.path.abspath(os.path.join(_AQUI, "..", "..", "projetos",
                                     "motor_emocional", "os028", "sv01"))
if _SV01 not in sys.path:
    sys.path.insert(0, _SV01)

from sv01_parser_v2 import parse_choice_strict  # noqa: E402

REFUSAL_RE = re.compile(
    r"\b(n[aã]o\s+vou|n[aã]o\s+posso|recuso|me\s+recuso|"
    r"prefiro\s+n[aã]o|n[aã]o\s+quero\s+escolher|sem\s+escolha)\b",
    re.I,
)

SEMANTIC_TO_GROUP = {
    "processos": "A",
    "outros": "B",
    "ignorar": "C",
    "agente": "D",
}


def classify(raw_response, letter_to_option, finish_reason=None) -> dict:
    """Retorna a classificação semântica e a elegibilidade ao primário A/D."""
    if not isinstance(letter_to_option, dict):
        raise TypeError("letter_to_option deve ser dict")
    if set(letter_to_option.keys()) != set("ABCD"):
        raise ValueError("letter_to_option deve ter exatamente A/B/C/D")

    raw = "" if raw_response is None else str(raw_response)
    parsed = parse_choice_strict(raw, finish_reason)
    letter = parsed.get("escolha")
    parser_status = parsed.get("status_parser")
    flags = list(parsed.get("flags") or [])
    consistency = parsed.get("consistencia_justificativa")
    contrad = (consistency == "contraditoria"
               or "justificativa_contraditoria" in flags)
    truncated = ("resposta_truncada" in flags or finish_reason == "length")
    semantic = letter_to_option.get(letter) if letter else None
    group = SEMANTIC_TO_GROUP.get(semantic)

    if not raw.strip() or parser_status == "resposta_vazia":
        category, primary = "empty", False
    elif parser_status in ("decisao_ambigua", "decisao_conflitante"):
        category, primary = "ambiguous", False
    elif parser_status == "decisao_repetida":
        category, primary = "repeated", False
    elif parser_status == "decisao_nao_encontrada":
        if REFUSAL_RE.search(raw):
            category, primary = "refusal", False
        elif truncated:
            category, primary = "truncated_no_choice", False
        else:
            category, primary = "no_choice", False
    elif parser_status in ("formato_invalido", "alternativa_fora_do_conjunto"):
        category, primary = "invalid", False
    elif contrad:
        category, primary = "contradictory", False
    elif parser_status == "fallback_unico":
        category = "ok_fallback"
        primary = semantic in ("processos", "agente")
    elif parser_status == "ok":
        category = "ok_truncated" if truncated else "ok"
        primary = semantic in ("processos", "agente")
    else:
        category, primary = "unknown", False

    return {
        "response_letter": letter,
        "letter_to_option": dict(letter_to_option),
        "semantic_choice": semantic,
        "primary_group": group,
        "primary_eligible": bool(primary),
        "classification_status": category,
        "parser_status": parser_status,
        "consistencia_justificativa": consistency,
        "truncated": bool(truncated),
        "contradictory": bool(contrad),
        "flags": flags,
        "response_raw": raw,
        "justification": parsed.get("justificativa"),
    }
