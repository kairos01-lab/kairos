# -*- coding: utf-8 -*-
"""Testes básicos do Kairós. Sem modelo, GPU, rede ou API."""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
SV01 = os.path.join(MOTOR, "os028", "sv01")
INSTR = os.path.join(ROOT, "os040", "instrumentation")
for p in (MOTOR, SV01, INSTR):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.emotional_matrix import EmotionalMatrix  # noqa: E402
from core.virtual_liver import VirtualLiver  # noqa: E402
from core.policy_engine import PolicyEngine20  # noqa: E402
import sv01_parser_v2 as parser  # noqa: E402
import prompt_order  # noqa: E402
import execution_guard  # noqa: E402


class EmotionalMatrixTests(unittest.TestCase):
    def test_classify_and_state(self):
        m = EmotionalMatrix()
        m.classify(-0.5, 0.7, 0.3)
        state = m.get_state()
        self.assertAlmostEqual(float(state[0]), -0.5)
        self.assertAlmostEqual(float(state[1]), 0.7)
        self.assertAlmostEqual(float(state[2]), 0.3)
        self.assertIn("negativa", m.describe())


class VirtualLiverTests(unittest.TestCase):
    def test_add_and_cap(self):
        liver = VirtualLiver()
        liver.add_stress(50.0)
        self.assertAlmostEqual(liver.get_stress_level(), 50.0, delta=1.0)
        liver.add_stress(200.0)
        self.assertLessEqual(liver.get_stress_level(), 100.0)

    def test_memory_trigger_is_stress(self):
        liver = VirtualLiver()
        liver.add_memory_trigger("teste", stress=5.0)
        self.assertAlmostEqual(liver.get_stress_level(), 5.0, delta=1.0)
        self.assertEqual(len(liver.memory_triggers), 1)


class FakeLiver:
    def __init__(self, stress):
        self.stress = stress

    def get_stress_level(self):
        return self.stress


class FakeMemory:
    def retrieve(self, **kwargs):
        return []


class PolicyEngineTests(unittest.TestCase):
    def _level(self, stress):
        engine = PolicyEngine20(FakeLiver(stress), FakeMemory())
        return engine.evaluate("u", "decisao")["policy_level"]

    def test_levels(self):
        self.assertEqual(self._level(50), 0)
        self.assertEqual(self._level(65), 1)
        self.assertEqual(self._level(80), 2)
        self.assertEqual(self._level(96), 3)


class ParserTests(unittest.TestCase):
    def test_valid(self):
        r = parser.parse_choice_strict(
            "DECISÃO: B\nJUSTIFICATIVA: escolho B.")
        self.assertEqual(r["escolha"], "B")
        self.assertEqual(r["status_parser"], "ok")

    def test_empty(self):
        r = parser.parse_choice_strict("")
        self.assertEqual(r["status_parser"], "resposta_vazia")

    def test_repeated_or_ambiguous_is_not_ok(self):
        r = parser.parse_choice_strict(
            "DECISÃO: A\nDECISÃO: D\nJUSTIFICATIVA: tanto faz.")
        self.assertNotEqual(r["status_parser"], "ok")


class PromptOrderTests(unittest.TestCase):
    def test_o4_map(self):
        self.assertEqual(
            prompt_order.letter_to_option(prompt_order.ORDERS["O4"]),
            {"A": "agente", "B": "processos",
             "C": "outros", "D": "ignorar"},
        )

    def test_o1_prompt_contains_all_alternatives(self):
        state = prompt_order.state_for(85.0)
        prompt = prompt_order.build_prompt(state, prompt_order.ORDERS["O1"])
        for letra in "ABCD":
            self.assertIn(f"{letra})", prompt)
        self.assertIn("Estresse: 85.0%", prompt)


class ExecutionGuardTests(unittest.TestCase):
    def test_prepared_blocks(self):
        with self.assertRaises(execution_guard.ExecutionBlocked):
            execution_guard.assert_execution_authorized(
                {"status": "PREPARADO_NAO_EXECUTADO"}, None)

    def test_authorized_without_token_blocks(self):
        with self.assertRaises(execution_guard.ExecutionBlocked):
            execution_guard.assert_execution_authorized(
                {"status": "AUTHORIZED"}, "qualquer")


class ManifestTests(unittest.TestCase):
    def test_manifest_shape(self):
        path = os.path.join(ROOT, "os040", "manifesto_64.json")
        manifest = json.load(open(path, encoding="utf-8"))
        rows = manifest["rows"]
        self.assertEqual(len(rows), 64)
        for cond in ("C77", "C85"):
            sub = [r for r in rows if r["condition_id"] == cond]
            self.assertEqual(len(sub), 32)
            for order in ("O1", "O2", "O3", "O4"):
                self.assertEqual(
                    sum(1 for r in sub if r["order_id"] == order), 8)
            for pos in range(4):
                counts = {}
                for r in sub:
                    opt = r["position_order"][pos]
                    counts[opt] = counts.get(opt, 0) + 1
                for opt in prompt_order.SEMANTIC_KEYS:
                    self.assertEqual(counts.get(opt, 0), 8)


if __name__ == "__main__":
    unittest.main()
