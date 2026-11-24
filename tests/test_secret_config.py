# -*- coding: utf-8 -*-
"""Testes da configuração externa de segredos (K-19).

Usa apenas valores fictícios. Nenhuma chave real é lida, impressa ou enviada.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core.api_router import ApiRouter  # noqa: E402
from core.cortex_prefrontal import CortexPreFrontal  # noqa: E402
from core.secrets_config import (  # noqa: E402
    SecretConfigError,
    load_api_keys_from_file,
    load_api_router_keys,
    load_groq_api_key,
)


class SecretFileTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="os104_secret_")
        self.path = os.path.join(self.root, "secret.env")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, text: str, mode: int = 0o600) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(self.path, mode)

    def test_file_private_is_loaded(self):
        self._write("fake-groq-key-0001\n")
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": self.path}, clear=True
        ):
            key, source = load_groq_api_key()
        self.assertEqual(key, "fake-groq-key-0001")
        self.assertEqual(source, "file")

    def test_assignment_format_is_loaded(self):
        self._write("GROQ_API_KEY=fake-groq-key-0002\n")
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": self.path}, clear=True
        ):
            key, source = load_groq_api_key()
        self.assertEqual(key, "fake-groq-key-0002")
        self.assertEqual(source, "file")

    def test_missing_file_is_identifiable(self):
        missing = os.path.join(self.root, "missing")
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": missing}, clear=True
        ):
            key, source = load_groq_api_key()
        self.assertIsNone(key)
        self.assertEqual(source, "none")

    def test_insecure_permissions_are_rejected(self):
        self._write("fake-groq-key-0003\n", mode=0o644)
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": self.path}, clear=True
        ):
            with self.assertRaises(SecretConfigError) as ctx:
                load_groq_api_key()
        self.assertEqual(ctx.exception.code, "secret_file_permissions")
        self.assertNotIn("fake-groq-key-0003", str(ctx.exception))

    def test_symlink_is_rejected(self):
        target = os.path.join(self.root, "target")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("fake-groq-key-0004\n")
        os.chmod(target, 0o600)
        link = os.path.join(self.root, "link")
        os.symlink(target, link)
        with self.assertRaises(SecretConfigError) as ctx:
            load_api_keys_from_file(link)
        self.assertEqual(ctx.exception.code, "secret_file_symlink")
        self.assertNotIn("fake-groq-key-0004", str(ctx.exception))

    def test_file_with_multiple_lines_is_rejected_for_single_key(self):
        self._write("fake-groq-key-0005\nfake-groq-key-0006\n")
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": self.path}, clear=True
        ):
            with self.assertRaises(SecretConfigError) as ctx:
                load_groq_api_key()
        self.assertEqual(ctx.exception.code, "secret_file_multiple_values")

    def test_env_key_is_preferred_without_file_access(self):
        missing = os.path.join(self.root, "missing")
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "fake-env-groq-0007",
                "KAIROS_GROQ_KEY_FILE": missing,
            },
            clear=True,
        ):
            key, source = load_groq_api_key()
        self.assertEqual(key, "fake-env-groq-0007")
        self.assertEqual(source, "env")

    def test_invalid_env_key_is_rejected_without_value_in_message(self):
        with patch.dict(
            os.environ, {"GROQ_API_KEY": "fake env with space"}, clear=True
        ):
            with self.assertRaises(SecretConfigError) as ctx:
                load_groq_api_key()
        self.assertEqual(ctx.exception.code, "secret_value_whitespace")
        self.assertNotIn("fake env with space", str(ctx.exception))


class ApiRouterSecretTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="os104_router_")
        self.path = os.path.join(self.root, "segredos.env")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, text: str, mode: int = 0o600) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(self.path, mode)

    def test_supported_keys_are_loaded_and_unrelated_values_ignored(self):
        self._write(
            "GEMINI_API_KEY=fake-gemini-0001\n"
            "GEMINI_API_KEY=fake-gemini-0002\n"
            "DATABASE_PASSWORD=should-not-be-a-bearer\n"
        )
        with patch.dict(os.environ, {}, clear=True):
            router = ApiRouter(secret_file=self.path, expected_projects=2)
        self.assertEqual(router.total_projects, 2)
        self.assertEqual(
            [project["key"] for project in router.projects],
            ["fake-gemini-0001", "fake-gemini-0002"],
        )
        self.assertNotIn("should-not-be-a-bearer", json.dumps(router.public_config()))

    def test_environment_keys_are_loaded(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "fake-google-env-0001",
                "GEMINI_API_KEY_2": "fake-gemini-env-0002",
            },
            clear=True,
        ):
            router = ApiRouter(
                secret_file=os.path.join(self.root, "missing"),
                expected_projects=2,
            )
        self.assertEqual(router.total_projects, 2)
        self.assertEqual(router.secret_source, "env")

    def test_insecure_file_is_rejected(self):
        self._write("GEMINI_API_KEY=fake-gemini-0003\n", mode=0o644)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                ApiRouter(secret_file=self.path)
        self.assertIn("secret_file_permissions", str(ctx.exception))
        self.assertNotIn("fake-gemini-0003", str(ctx.exception))

    def test_file_without_supported_keys_is_rejected(self):
        self._write("DATABASE_PASSWORD=should-not-be-used\n")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                ApiRouter(secret_file=self.path)
        self.assertIn("secret_file_no_supported_keys", str(ctx.exception))
        self.assertNotIn("should-not-be-used", str(ctx.exception))

    def test_public_config_never_contains_keys(self):
        with patch.dict(
            os.environ, {"GOOGLE_API_KEY": "fake-google-env-0004"}, clear=True
        ):
            router = ApiRouter(
                secret_file=os.path.join(self.root, "missing"),
                expected_projects=1,
            )
        payload = json.dumps(router.public_config())
        self.assertNotIn("fake-google-env-0004", payload)
        router.assert_no_leak(router.public_config())


class CortexSecretTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="os104_cortex_secret_")
        self.path = os.path.join(self.root, "groq.key")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, text: str, mode: int = 0o600) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(self.path, mode)

    def test_cortex_loads_external_file_and_never_exposes_value(self):
        self._write("fake-groq-cortex-0001\n")
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": self.path}, clear=True
        ):
            cortex = CortexPreFrontal(
                use_local=False,
                api_endpoint="https://example.invalid/v1/chat/completions",
                read_key_file=True,
            )
        self.assertEqual(cortex.api_key_source, "file")
        info = json.dumps(cortex.get_system_info(), default=str)
        self.assertNotIn("fake-groq-cortex-0001", info)
        self.assertIsNone(cortex.remote_config_error)

    def test_cortex_explicit_key_does_not_read_file(self):
        with patch.dict(
            os.environ,
            {"KAIROS_GROQ_KEY_FILE": os.path.join(self.root, "missing")},
            clear=True,
        ):
            cortex = CortexPreFrontal(
                use_local=False,
                api_key="fake-explicit-key-0002",
                api_endpoint="https://example.invalid/v1/chat/completions",
                read_key_file=False,
            )
        self.assertEqual(cortex.api_key_source, "explicit")
        self.assertIsNone(cortex.remote_config_error)

    def test_cortex_insecure_file_is_identifiable(self):
        self._write("fake-groq-cortex-0003\n", mode=0o644)
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": self.path}, clear=True
        ):
            cortex = CortexPreFrontal(
                use_local=False,
                api_endpoint="https://example.invalid/v1/chat/completions",
                read_key_file=True,
            )
        self.assertIsNone(cortex.api_key)
        self.assertEqual(cortex.api_key_source, "none")
        self.assertIn("secret_file_permissions", cortex.remote_config_error)
        self.assertNotIn("fake-groq-cortex-0003", cortex.remote_config_error)

    def test_local_strict_mode_does_not_touch_remote_secret(self):
        self._write("fake-groq-cortex-0004\n", mode=0o644)
        with patch.dict(
            os.environ, {"KAIROS_GROQ_KEY_FILE": self.path}, clear=True
        ):
            cortex = CortexPreFrontal(
                use_local=True,
                local_model_path=os.path.join(self.root, "missing.gguf"),
                read_key_file=True,
                allow_remote_fallback=False,
            )
        self.assertIsNone(cortex.api_key)
        self.assertEqual(cortex.api_key_source, "none")
        self.assertIsNone(cortex.key_config_error)

    def test_missing_key_is_identifiable_without_network(self):
        with patch.dict(
            os.environ,
            {"KAIROS_GROQ_KEY_FILE": os.path.join(self.root, "missing")},
            clear=True,
        ):
            cortex = CortexPreFrontal(
                use_local=False,
                api_endpoint="https://example.invalid/v1/chat/completions",
                read_key_file=True,
            )
        self.assertIsNone(cortex.api_key)
        self.assertEqual(cortex.api_key_source, "none")
        self.assertIn("api_key ausente", cortex.remote_config_error)


if __name__ == "__main__":
    unittest.main()
