# -*- coding: utf-8 -*-
"""OS156 — regressões de F1 (EmotionalMatrix) e F2 (GET /)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core.emotional_matrix import EmotionalMatrix  # noqa: E402
import core.web_server as web_server  # noqa: E402
import core.motor_sistema as motor_sistema  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class EmotionalMatrixValidationTests(unittest.TestCase):
    """F1 — contrato documentado de classify() e describe()."""

    def setUp(self):
        self.matrix = EmotionalMatrix()

    def test_initial_state(self):
        np.testing.assert_array_equal(
            self.matrix.get_state(), np.zeros(3, dtype=np.float32)
        )
        self.assertEqual(
            self.matrix.describe(),
            "Emocional[negativa, baixa, baixa]",
        )

    def test_valid_bounds_and_intermediate_values(self):
        cases = (
            (-1.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
            (0.25, 0.5, 0.75),
            (-0.5, 0.7, 0.3),
        )
        for values in cases:
            with self.subTest(values=values):
                state = self.matrix.classify(*values)
                np.testing.assert_allclose(state, values, rtol=0, atol=1e-6)
                np.testing.assert_allclose(
                    self.matrix.get_state(), values, rtol=0, atol=1e-6
                )

    def test_classify_returns_a_copy(self):
        state = self.matrix.classify(0.2, 0.3, 0.7)
        state[0] = 99.0
        self.assertAlmostEqual(float(self.matrix.get_state()[0]), 0.2, places=6)

    def test_accepts_numpy_numeric_scalars(self):
        # O motor passa np.float32 ao classificar o novo estado.
        self.matrix.classify(
            np.float32(-0.5), np.float64(0.7), np.int64(0)
        )
        np.testing.assert_allclose(
            self.matrix.get_state(), (-0.5, 0.7, 0.0), atol=1e-6
        )

    def test_rejects_none(self):
        with self.assertRaises(ValueError):
            self.matrix.classify(None, 0.5, 0.5)

    def test_rejects_booleans_even_though_bool_is_int(self):
        for index in range(3):
            values = [0.5, 0.5, 0.5]
            values[index] = True
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    self.matrix.classify(*values)

    def test_rejects_strings_and_other_non_numeric_types(self):
        for value in ("0.5", object(), [0.5]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.matrix.classify(value, 0.5, 0.5)

    def test_rejects_nan_and_infinities(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.matrix.classify(value, 0.5, 0.5)

    def test_rejects_values_outside_documented_ranges(self):
        cases = (
            (1.0001, 0.5, 0.5),
            (-1.0001, 0.5, 0.5),
            (0.5, -0.0001, 0.5),
            (0.5, 1.0001, 0.5),
            (0.5, 0.5, -0.0001),
            (0.5, 0.5, 1.0001),
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.matrix.classify(*values)

    def test_invalid_input_preserves_previous_state(self):
        self.matrix.classify(0.2, 0.3, 0.7)
        before = self.matrix.get_state().copy()
        invalid_cases = (
            (None, 0.5, 0.5),
            (True, 0.5, 0.5),
            ("x", 0.5, 0.5),
            (float("nan"), 0.5, 0.5),
            (2.0, 0.5, 0.5),
        )
        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.matrix.classify(*values)
                np.testing.assert_array_equal(self.matrix.get_state(), before)

    def test_describe_rejects_out_of_range_state(self):
        self.matrix.state = np.array([2.0, 0.5, 0.5], dtype=np.float32)
        with self.assertRaises(ValueError):
            self.matrix.describe()

    def test_describe_rejects_non_finite_state(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.matrix.state = np.array(
                    [0.0, value, 0.5], dtype=np.float32
                )
                with self.assertRaises(ValueError):
                    self.matrix.describe()

    def test_describe_rejects_invalid_internal_shape_or_dtype(self):
        self.matrix.state = np.array([0.0, 0.5], dtype=np.float32)
        with self.assertRaises(ValueError):
            self.matrix.describe()
        self.matrix.state = np.array([0, 1, 0], dtype=np.int64)
        with self.assertRaises(ValueError):
            self.matrix.describe()

    def test_describe_valid_boundaries(self):
        self.matrix.classify(-1.0, 0.0, 0.0)
        self.assertEqual(
            self.matrix.describe(), "Emocional[negativa, baixa, baixa]"
        )
        self.matrix.classify(1.0, 1.0, 1.0)
        self.assertEqual(
            self.matrix.describe(), "Emocional[positiva, alta, alta]"
        )


class DashboardRouteTests(unittest.TestCase):
    """F2 — GET / não pode depender do diretório corrente."""

    def setUp(self):
        self._old_motor = web_server.motor
        web_server.motor = None
        self.client = TestClient(web_server.app)

    def tearDown(self):
        self.client.close()
        web_server.motor = self._old_motor

    def test_template_directory_is_absolute_and_dashboard_exists(self):
        self.assertTrue(web_server._TEMPLATES_DIR.is_absolute())
        self.assertTrue(
            (web_server._TEMPLATES_DIR / "dashboard.html").is_file()
        )

    def test_dashboard_input_limit_matches_server(self):
        template = (web_server._TEMPLATES_DIR / "dashboard.html").read_text(
            encoding="utf-8"
        )
        self.assertEqual(motor_sistema._MAX_USER_INPUT_CHARS, 8192)
        self.assertIn('maxlength="8192"', template)
        self.assertIn("0 / 8192 caracteres", template)
        self.assertIn("Limite de", template)
        self.assertNotIn('maxlength="32768"', template)

    def test_get_root_returns_dashboard_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Kairós", response.text)
        self.assertIn("/api/status", response.text)
        self.assertIn("/api/interact", response.text)

    def test_get_root_works_from_different_cwd(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="os156_cwd_") as directory:
            os.chdir(directory)
            try:
                response = self.client.get("/")
            finally:
                os.chdir(original)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Kairós", response.text)

    def test_existing_api_and_websocket_remain_functional(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        status = self.client.get("/api/status")
        self.assertEqual(status.status_code, 503)

        interact = self.client.post("/api/interact", json={"user_id": "u1"})
        self.assertEqual(interact.status_code, 503)

        with self.client.websocket_connect("/ws") as websocket:
            websocket.send_text("ping")
            self.assertEqual(
                websocket.receive_json(),
                {"type": "pong", "echo": "ping"},
            )


if __name__ == "__main__":
    unittest.main()
