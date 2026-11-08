# -*- coding: utf-8 -*-
"""OS040 — registro de estado com campos ausentes explícitos.

Não infere valores. Campos não fornecidos ficam None e são listados em
`fields_absent`. O registro é a unidade de reconstrução de uma execução.
"""
from __future__ import annotations

CORE_FIELDS = (
    "run_id",
    "condition_id",
    "model",
    "model_revision",
    "stress_pre",
    "stress_post",
    "stress_prompt",
    "prompt_sha256_rendered",
    "position_order",
    "letter_to_option",
    "response_raw",
    "classification_status",
    "primary_eligible",
    "status",
)

OPTIONAL_FIELDS = (
    "provider",
    "project_id",
    "seed",
    "seed_effective",
    "policy_level",
    "policy_action",
    "matrix_pre",
    "matrix_prompt",
    "matrix_post",
    "prompt_sha256_pre_template",
    "response_letter",
    "semantic_choice",
    "blind_eval_id",
    "erro_motivo",
)

ALL_FIELDS = CORE_FIELDS + OPTIONAL_FIELDS


def build_record(**kwargs) -> dict:
    rec = {field: kwargs.get(field) for field in ALL_FIELDS}
    rec["fields_absent"] = [
        field for field in ALL_FIELDS if rec[field] is None
    ]
    return rec


def validate_record(rec: dict) -> dict:
    missing = [field for field in CORE_FIELDS if rec.get(field) is None]
    return {"valid": not missing, "missing": missing}
