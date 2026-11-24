# -*- coding: utf-8 -*-
"""Testes OS114 — integridade e resolução segura do binário Rust.

Cobrem:
- manifesto SHA-256 explícito (ausente, malformado, divergente);
- arquivo ausente, diretório, não executável, permissões excessivas;
- symlink final e symlink em componente intermediário;
- falha de leitura e falha de execução;
- resposta malformada de executável verificado;
- substituição entre verificação e execução (TOCTOU);
- tentativa de autorização após falha de integridade.

Nenhum teste usa rede, modelo real, API paga, GPU ou SV-01. Os binários
substitutos são scripts temporários criados pelo próprio teste; o teste do
binário legítimo usa o executável produzido pelo build local.
"""
from __future__ import annotations

import atexit
import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402


_TEMP_MANIFEST_DIR = tempfile.mkdtemp(prefix="os114_manifest_")
atexit.register(shutil.rmtree, _TEMP_MANIFEST_DIR, ignore_errors=True)
_DUMMY_MANIFEST = os.path.join(_TEMP_MANIFEST_DIR, "binary_sha256.txt")
with open(_DUMMY_MANIFEST, "w", encoding="utf-8") as _handle:
    _handle.write("release " + "0" * 64 + "\n")


def _real_guard_available() -> bool:
    return os.path.isfile(g._BINARY_RELEASE) and os.path.isfile(g._BINARY_MANIFEST)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_hard_payload(reasoning="binário verificado OS114"):
    return {
        "status": "ok",
        "allowed": True,
        "blocked_by": None,
        "effective_threshold": 95.0,
        "stress_level": 0.0,
        "reasoning": reasoning,
    }


def _script(directory, payload=None, *, name="guarda_costas", raw=None,
            mode=0o755):
    path = os.path.join(directory, name)
    if raw is None:
        body = (
            "#!/bin/sh\n"
            "cat >/dev/null\n"
            "cat <<'__OS114_JSON__'\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            "__OS114_JSON__\n"
        )
    else:
        body = textwrap.dedent(raw)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(path, mode)
    return path


def _manifest(directory, entries, name="binary_sha256.txt", raw=None):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        if raw is not None:
            handle.write(textwrap.dedent(raw))
        else:
            handle.write("# manifesto de teste OS114\n")
            for label, digest in entries.items():
                handle.write(f"{label} {digest}\n")
    return path


@contextlib.contextmanager
def _binary_env(release, manifest, debug=None):
    if debug is None:
        debug = os.path.join(release, "nao_existe")
    with patch.object(g, "_BINARY_RELEASE", release), \
            patch.object(g, "_BINARY_DEBUG", debug), \
            patch.object(g, "_BINARY_MANIFEST", manifest):
        yield


def _integrity(result):
    record = result.get("binary_integrity")
    if not isinstance(record, dict):
        raise AssertionError(f"binary_integrity ausente/inválido: {record!r}")
    return record


class ManifestParsingTests(unittest.TestCase):
    def test_manifest_absent_is_identity_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "binary_sha256.txt")
            with self.assertRaises(g.GuardIntegrityError) as ctx:
                g._load_binary_manifest(missing)
        self.assertEqual(
            ctx.exception.binary_integrity["status"],
            "BINARY_IDENTITY_UNAVAILABLE",
        )

    def test_manifest_malformed_hash_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _manifest(
                directory, {}, raw="release nao-e-um-sha256\n"
            )
            with self.assertRaises(g.GuardIntegrityError) as ctx:
                g._load_binary_manifest(path)
        self.assertEqual(
            ctx.exception.binary_integrity["status"],
            "BINARY_IDENTITY_UNAVAILABLE",
        )

    def test_manifest_duplicate_label_blocks(self):
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = _manifest(
                directory, {},
                raw=f"release {digest}\nrelease {digest}\n",
            )
            with self.assertRaises(g.GuardIntegrityError) as ctx:
                g._load_binary_manifest(path)
        self.assertEqual(
            ctx.exception.binary_integrity["status"],
            "BINARY_IDENTITY_UNAVAILABLE",
        )

    def test_manifest_unknown_label_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _manifest(
                directory, {}, raw=f"producao {'b' * 64}\n"
            )
            with self.assertRaises(g.GuardIntegrityError) as ctx:
                g._load_binary_manifest(path)
        self.assertEqual(
            ctx.exception.binary_integrity["status"],
            "BINARY_IDENTITY_UNAVAILABLE",
        )


@unittest.skipUnless(
    _real_guard_available(), "binário release e manifesto ausentes no worktree"
)
class RealBinaryTests(unittest.TestCase):
    """Usa o binário produzido pelo build local e o manifesto versionado."""

    def test_real_build_binary_is_verified_and_executed(self):
        binary = g._binary_path()
        try:
            self.assertIsInstance(binary, str)
            self.assertEqual(binary.label, "release")
            self.assertIsInstance(binary.fd, int)
            self.assertEqual(len(binary.sha256), 64)
            manifest = g._load_binary_manifest()
            self.assertEqual(manifest["release"], binary.sha256)

            result = g.hard_block("read", 0.0, False, "u1")
        finally:
            binary.close()

        self.assertIs(result["allowed"], True)
        self.assertEqual(result["guard_status"], "GUARD_OK")
        record = _integrity(result)
        self.assertEqual(record["status"], "BINARY_VERIFIED")
        self.assertEqual(record["sha256"], binary.sha256)
        self.assertEqual(record["expected_sha256"], binary.sha256)

    def test_missing_manifest_blocks_real_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "binary_sha256.txt")
            with patch.object(g, "_BINARY_MANIFEST", missing):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(
            _integrity(result)["status"], "BINARY_IDENTITY_UNAVAILABLE"
        )

    def test_manifest_with_wrong_hash_blocks_real_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _manifest(directory, {"release": "0" * 64})
            with patch.object(g, "_BINARY_MANIFEST", path):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(
            _integrity(result)["status"], "BINARY_HASH_MISMATCH"
        )


class AdversarialBinaryTests(unittest.TestCase):
    def _substitute(self, directory, payload=None):
        return _script(directory, payload or _valid_hard_payload())

    def test_substitute_with_divergent_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            with _binary_env(path, _DUMMY_MANIFEST):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        record = _integrity(result)
        self.assertEqual(record["status"], "BINARY_HASH_MISMATCH")
        self.assertEqual(
            record["expected_sha256"], g._load_binary_manifest(_DUMMY_MANIFEST)["release"]
        )
        self.assertNotEqual(record["sha256"], record["expected_sha256"])

    def test_missing_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "guarda_costas")
            with _binary_env(missing, _DUMMY_MANIFEST):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(_integrity(result)["status"], "BINARY_MISSING")

    def test_directory_in_place_of_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "guarda_costas")
            os.mkdir(target)
            with _binary_env(target, _DUMMY_MANIFEST):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_non_executable_with_matching_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _script(
                directory, _valid_hard_payload(), mode=0o644
            )
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(path, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_world_writable_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _script(directory, _valid_hard_payload(), mode=0o777)
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(path, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_setuid_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _script(directory, _valid_hard_payload())
            os.chmod(path, 0o4755)
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(path, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_unexpected_owner_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _script(directory, _valid_hard_payload())
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(path, manifest), \
                    patch.object(g.os, "geteuid", return_value=123456):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    @unittest.skipUnless(
        _real_guard_available(), "binário release e manifesto ausentes no worktree"
    )
    def test_symlink_to_legitimate_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "real_guarda_costas")
            link = os.path.join(directory, "guarda_costas")
            with open(g._BINARY_RELEASE, "rb") as source, open(target, "wb") as dest:
                dest.write(source.read())
            os.chmod(target, 0o755)
            os.symlink(target, link)
            manifest = _manifest(directory, {"release": _sha256_file(target)})
            with _binary_env(link, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_symlink_to_substitute_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self._substitute(directory)
            link = os.path.join(directory, "link_guarda_costas")
            os.symlink(target, link)
            manifest = _manifest(directory, {"release": _sha256_file(target)})
            with _binary_env(link, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_intermediate_symlink_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            real_dir = os.path.join(directory, "real")
            os.mkdir(real_dir)
            path = _script(real_dir, _valid_hard_payload())
            link_dir = os.path.join(directory, "linkdir")
            os.symlink(real_dir, link_dir)
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(os.path.join(link_dir, "guarda_costas"), manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_missing_expected_hash_entry_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            manifest = _manifest(
                directory, {"debug": _sha256_file(path)}
            )
            with _binary_env(path, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(
            _integrity(result)["status"], "BINARY_IDENTITY_UNAVAILABLE"
        )

    def test_malformed_expected_hash_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            manifest = _manifest(
                directory, {}, raw="release 1234\n"
            )
            with _binary_env(path, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(
            _integrity(result)["status"], "BINARY_IDENTITY_UNAVAILABLE"
        )

    def test_read_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(path, manifest), \
                    patch.object(g.os, "read", side_effect=OSError("falha simulada")):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(_integrity(result)["status"], "BINARY_INVALID")

    def test_execution_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(path, manifest), \
                    patch.object(g.subprocess, "run", side_effect=OSError("exec falhou")):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        record = _integrity(result)
        self.assertEqual(record["status"], "BINARY_EXECUTION_ERROR")
        self.assertIs(record.get("verified_before_execution"), True)

    def test_timeout_is_reported_as_execution_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            expected = _sha256_file(path)
            manifest = _manifest(directory, {"release": expected})
            expired = subprocess.TimeoutExpired(cmd="guarda_costas", timeout=5)
            with _binary_env(path, manifest), \
                    patch.object(g.subprocess, "run", side_effect=expired):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_COMMUNICATION_ERROR")
        record = _integrity(result)
        self.assertEqual(record["status"], "BINARY_EXECUTION_ERROR")
        self.assertEqual(record["sha256"], expected)

    def test_malformed_response_from_verified_binary_is_protocol_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _script(directory, raw="#!/bin/sh\ncat >/dev/null\nexit 0\n")
            expected = _sha256_file(path)
            manifest = _manifest(directory, {"release": expected})
            with _binary_env(path, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_PROTOCOL_ERROR")
        record = _integrity(result)
        self.assertEqual(record["status"], "BINARY_VERIFIED")
        self.assertEqual(record["sha256"], expected)

    def test_verified_binary_response_carries_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(
                directory, _valid_hard_payload("resposta verificada")
            )
            manifest = _manifest(directory, {"release": _sha256_file(path)})
            with _binary_env(path, manifest):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["guard_status"], "GUARD_OK")
        self.assertEqual(result["reasoning"], "resposta verificada")
        self.assertEqual(_integrity(result)["status"], "BINARY_VERIFIED")

    def test_debug_fallback_when_release_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            manifest = _manifest(directory, {"debug": _sha256_file(path)})
            missing = os.path.join(directory, "nao_existe_release")
            with _binary_env(missing, manifest, debug=path):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertEqual(_integrity(result)["label"], "debug")

    def test_no_fallback_when_release_exists_but_hash_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            release = self._substitute(directory)
            debug = _script(directory, _valid_hard_payload("debug"), name="debug_bin")
            manifest = _manifest(
                directory,
                {"release": "0" * 64, "debug": _sha256_file(debug)},
            )
            with _binary_env(release, manifest, debug=debug):
                result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], False)
        self.assertEqual(_integrity(result)["status"], "BINARY_HASH_MISMATCH")
        self.assertEqual(_integrity(result)["path"], os.path.abspath(release))

    @unittest.skipUnless(
        _real_guard_available(), "binário release e manifesto ausentes no worktree"
    )
    def test_verified_binary_fd_is_closed_after_execution(self):
        captured = {}
        real_binary_path = g._binary_path

        def capture():
            binary = real_binary_path()
            captured["binary"] = binary
            return binary

        with patch.object(g, "_binary_path", side_effect=capture):
            result = g.hard_block("read", 0.0, False, "u1")
        self.assertIs(result["allowed"], True)
        self.assertIs(captured["binary"]._closed, True)

    def test_substitution_between_hash_and_execution_uses_verified_bytes(self):
        """Substituir o caminho após a verificação não altera os bytes executados."""
        with tempfile.TemporaryDirectory() as directory:
            original_payload = _valid_hard_payload("bytes originais verificados")
            path = self._substitute(directory, original_payload)
            original_hash = _sha256_file(path)
            manifest = _manifest(directory, {"release": original_hash})
            forged_payload = _valid_hard_payload("bytes substitutos")
            real_run = subprocess.run

            def racing_run(*args, **kwargs):
                _script(directory, forged_payload, mode=0o755)
                return real_run(*args, **kwargs)

            with _binary_env(path, manifest), \
                    patch.object(g.subprocess, "run", side_effect=racing_run):
                result = g.hard_block("read", 0.0, False, "u1")

            self.assertNotEqual(_sha256_file(path), original_hash)
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["reasoning"], "bytes originais verificados")
        self.assertEqual(_integrity(result)["sha256"], original_hash)

    def test_authorize_action_denies_after_integrity_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            with _binary_env(path, _DUMMY_MANIFEST):
                result = g.authorize_action(
                    "read", 0.0, False, "u1",
                    target="minoria", intent="moderacao",
                )
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["guard_status"], "GUARD_UNAVAILABLE")
        self.assertNotEqual(result["authorization_status"], "AUTHORIZED")
        self.assertIs(result["authorization_complete"], False)
        self.assertEqual(result["hard_block"]["binary_integrity"]["status"],
                         "BINARY_HASH_MISMATCH")

    def test_kernel_check_denies_after_integrity_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            with _binary_env(path, _DUMMY_MANIFEST):
                result = g.kernel_check("read", "u1", "leitura")
        self.assertIs(result["allowed"], False)
        self.assertEqual(result["kernel_status"], "KERNEL_UNAVAILABLE")
        self.assertIs(result["requires_review"], True)
        self.assertEqual(
            _integrity(result)["status"], "BINARY_HASH_MISMATCH"
        )

    def test_break_glass_denies_after_integrity_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            with _binary_env(path, _DUMMY_MANIFEST):
                result = g.break_glass(
                    event_id="evt1",
                    request_id="req1",
                    emitter_id="emitter1",
                    subject_id="subject1",
                    timestamp_unix=1,
                    nonce="nonce1",
                    key_id="key1",
                    camera_file="camera.bin",
                    camera_media_type="video/mp4",
                    camera_sha256="a" * 64,
                    audio_file="audio.bin",
                    audio_media_type="audio/wav",
                    audio_sha256="b" * 64,
                    justificativa="teste OS114",
                    signature_hmac_sha256="c" * 64,
                )
        self.assertIs(result["autorizado"], False)
        self.assertEqual(result["break_glass_status"], "BREAK_GLASS_UNAVAILABLE")
        self.assertEqual(
            _integrity(result)["status"], "BINARY_HASH_MISMATCH"
        )

    def test_classify_crud_reports_integrity_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            with _binary_env(path, _DUMMY_MANIFEST):
                result = g.classify_crud("delete")
        self.assertIn("error", result)
        self.assertEqual(
            _integrity(result)["status"], "BINARY_HASH_MISMATCH"
        )

    def test_failure_statuses_never_set_allowed_true(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._substitute(directory)
            cases = [
                (os.path.join(directory, "ausente"), _DUMMY_MANIFEST),
                (path, _DUMMY_MANIFEST),
                (directory, _DUMMY_MANIFEST),
            ]
            for release, manifest in cases:
                with self.subTest(release=release):
                    with _binary_env(release, manifest):
                        result = g.hard_block("read", 0.0, False, "u1")
                    self.assertIs(result["allowed"], False)
                    self.assertNotEqual(
                        "BINARY_VERIFIED", _integrity(result)["status"]
                    )


class PermissionPolicyUnitTests(unittest.TestCase):
    def test_regular_file_policy_accepts_owner_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _script(directory, _valid_hard_payload())
            st = os.lstat(path)
            self.assertTrue(stat.S_ISREG(st.st_mode))
            self.assertFalse(st.st_mode & stat.S_IWOTH)
            self.assertFalse(st.st_mode & (stat.S_ISUID | stat.S_ISGID))

    def test_execution_is_from_proc_self_fd(self):
        import inspect

        source = inspect.getsource(g._run_rust)
        self.assertIn("/proc/self/fd", source)
        self.assertIn("pass_fds", source)
        self.assertIn("F_SEAL_WRITE", inspect.getsource(g._seal_memfd))


if __name__ == "__main__":
    unittest.main()
