# -*- coding: utf-8 -*-
"""Testes adversariais do Break Glass (OS101).

Cobrem integridade sobre bytes reais, HMAC-SHA256 com chave efêmera,
vínculo evento/evidência, nonce/replay, fail-closed e integração com o motor.
Nenhuma chave é fixa: cada teste gera uma chave temporária fora do repositório.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402


def _real_guard_available() -> bool:
    return os.path.isfile(g._BINARY_RELEASE) and os.path.isfile(g._BINARY_MANIFEST)


def _canonical(req: dict, camera_sha256: str, audio_sha256: str) -> bytes:
    """Mesma serialização canônica do Rust: nome/valor prefixados por u64 BE."""
    out = bytearray(b"KAIROS-BREAK-GLASS-V1")

    def push(name: str, value: bytes) -> None:
        name_bytes = name.encode("utf-8")
        out.extend(struct.pack(">Q", len(name_bytes)))
        out.extend(name_bytes)
        out.extend(struct.pack(">Q", len(value)))
        out.extend(value)

    push("event_id", req["event_id"].encode("utf-8"))
    push("request_id", req["request_id"].encode("utf-8"))
    push("emitter_id", req["emitter_id"].encode("utf-8"))
    push("subject_id", req["subject_id"].encode("utf-8"))
    push("timestamp_unix", str(req["timestamp_unix"]).encode("utf-8"))
    push("nonce", req["nonce"].encode("utf-8"))
    push("key_id", req["key_id"].encode("utf-8"))
    push("camera_file", req["camera_file"].encode("utf-8"))
    push("camera_media_type", req["camera_media_type"].encode("utf-8"))
    push("camera_sha256", camera_sha256.encode("utf-8"))
    push("audio_file", req["audio_file"].encode("utf-8"))
    push("audio_media_type", req["audio_media_type"].encode("utf-8"))
    push("audio_sha256", audio_sha256.encode("utf-8"))
    gps = req.get("gps_coords")
    push("gps_present", b"1" if gps is not None else b"0")
    if gps is not None:
        push("gps_coords", gps.encode("utf-8"))
    push("justificativa", req["justificativa"].encode("utf-8"))
    return bytes(out)


def _sign(key: bytes, req: dict, camera_sha256: str, audio_sha256: str) -> str:
    return hmac.new(
        key, _canonical(req, camera_sha256, audio_sha256), hashlib.sha256
    ).hexdigest()


class BreakGlassFixture:
    """Cria chave, vínculo de emissor, evidências e estado temporários."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="os101_break_glass_")
        self.key_dir = os.path.join(self.root, "keys")
        self.evidence_dir = os.path.join(self.root, "evidence")
        self.state_dir = os.path.join(self.root, "state")
        for directory in (self.key_dir, self.evidence_dir, self.state_dir):
            os.makedirs(directory, mode=0o700, exist_ok=True)
            os.chmod(directory, 0o700)

        self.key_id = "key-test"
        self.emitter_id = "device-A"
        self.key = os.urandom(32)
        self._write_private(
            os.path.join(self.key_dir, f"{self.key_id}.key"),
            self.key.hex() + "\n",
        )
        self._write_private(
            os.path.join(self.key_dir, f"{self.key_id}.emitter"),
            self.emitter_id + "\n",
        )

        self.camera_file = "camera.jpg"
        self.audio_file = "audio.wav"
        self.camera_bytes = b"\xff\xd8\xff\xe0camera-evidence"
        self.audio_bytes = b"RIFF\x00\x00\x00\x00WAVEaudio-evidence"
        self.write_evidence(self.camera_file, self.camera_bytes)
        self.write_evidence(self.audio_file, self.audio_bytes)

    def _write_private(self, path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, 0o600)

    def write_evidence(self, name: str, content: bytes) -> None:
        path = os.path.join(self.evidence_dir, name)
        with open(path, "wb") as handle:
            handle.write(content)
        os.chmod(path, 0o600)

    def read_evidence(self, name: str) -> bytes:
        with open(os.path.join(self.evidence_dir, name), "rb") as handle:
            return handle.read()

    def write_key(self, key_id: str, emitter_id: str, key: bytes) -> None:
        self._write_private(
            os.path.join(self.key_dir, f"{key_id}.key"), key.hex() + "\n"
        )
        self._write_private(
            os.path.join(self.key_dir, f"{key_id}.emitter"), emitter_id + "\n"
        )

    @property
    def env(self) -> dict:
        return {
            "KAIROS_BREAK_GLASS_KEY_DIR": self.key_dir,
            "KAIROS_BREAK_GLASS_EVIDENCE_DIR": self.evidence_dir,
            "KAIROS_BREAK_GLASS_STATE_DIR": self.state_dir,
        }

    def request(self, *, signing_key: bytes = None, **overrides) -> dict:
        req = {
            "event_id": "evt-" + uuid.uuid4().hex[:12],
            "request_id": "req-" + uuid.uuid4().hex[:12],
            "emitter_id": self.emitter_id,
            "subject_id": "user-1",
            "timestamp_unix": int(time.time()),
            "nonce": uuid.uuid4().hex,
            "key_id": self.key_id,
            "camera_file": self.camera_file,
            "camera_media_type": "jpeg",
            "camera_sha256": "",
            "audio_file": self.audio_file,
            "audio_media_type": "wav",
            "audio_sha256": "",
            "gps_coords": "-23.55,-46.63",
            "justificativa": "emergência médica",
            "signature_hmac_sha256": "",
        }
        req.update(overrides)

        try:
            camera_computed = hashlib.sha256(
                self.read_evidence(req["camera_file"])
            ).hexdigest()
            audio_computed = hashlib.sha256(
                self.read_evidence(req["audio_file"])
            ).hexdigest()
        except (TypeError, OSError):
            camera_computed = "0" * 64
            audio_computed = "0" * 64

        if "camera_sha256" not in overrides:
            req["camera_sha256"] = camera_computed
        if "audio_sha256" not in overrides:
            req["audio_sha256"] = audio_computed
        if "signature_hmac_sha256" not in overrides:
            try:
                req["signature_hmac_sha256"] = _sign(
                    signing_key or self.key, req, camera_computed, audio_computed
                )
            except (AttributeError, TypeError):
                req["signature_hmac_sha256"] = "0" * 64
        return req

    def call(self, request: dict) -> dict:
        if not _real_guard_available():
            raise unittest.SkipTest(
                "binário Rust e manifesto de integridade ausentes no worktree"
            )
        with patch.dict(os.environ, self.env, clear=False):
            return g.break_glass(**request)

    def cli(self, data: dict):
        if not _real_guard_available():
            raise unittest.SkipTest(
                "binário Rust e manifesto de integridade ausentes no worktree"
            )
        binary = g._binary_path()
        with patch.dict(os.environ, self.env, clear=False):
            return subprocess.run(
                [binary],
                input=json.dumps({"op": "break_glass", "data": data}),
                capture_output=True,
                text=True,
                timeout=15,
            )

    def cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)


def _status(response: dict) -> str:
    return response.get("break_glass_status")


def _fake_authorized(req: dict) -> dict:
    return {
        "status": "ok",
        "autorizado": True,
        "break_glass_status": "BREAK_GLASS_AUTHORIZED",
        "event_id": req["event_id"],
        "request_id": req["request_id"],
        "emitter_id": req["emitter_id"],
        "subject_id": req["subject_id"],
        "key_id": req["key_id"],
        "timestamp_unix": req["timestamp_unix"],
        "server_timestamp_unix": int(time.time()),
        "camera_sha256": req["camera_sha256"],
        "audio_sha256": req["audio_sha256"],
        "gps_coords": req["gps_coords"],
        "gps_provenance": "declared_metadata_unauthenticated",
        "nonce": req["nonce"],
        "signature_algorithm": "HMAC-SHA256",
        "signature_verified": True,
        "nonce_consumed": True,
        "evidence_digest": "a" * 64,
        "selo_criptografico": "b" * 64,
        "motivo_recusa": None,
    }


class BreakGlassHappyPathTests(unittest.TestCase):
    def setUp(self):
        self.fx = BreakGlassFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_evidencia_valida_autoriza(self):
        req = self.fx.request()
        response = self.fx.call(req)
        self.assertIs(response["autorizado"], True)
        self.assertEqual(_status(response), "BREAK_GLASS_AUTHORIZED")
        self.assertIs(response["signature_verified"], True)
        self.assertIs(response["nonce_consumed"], True)
        self.assertEqual(response["signature_algorithm"], "HMAC-SHA256")
        self.assertEqual(len(response["selo_criptografico"]), 64)
        self.assertEqual(len(response["evidence_digest"]), 64)
        self.assertEqual(response["camera_sha256"], req["camera_sha256"])
        self.assertEqual(response["audio_sha256"], req["audio_sha256"])
        self.assertEqual(response["subject_id"], req["subject_id"])
        self.assertIsNone(response["motivo_recusa"])
        self.assertEqual(
            response["gps_provenance"], "declared_metadata_unauthenticated"
        )

    def test_sem_gps_autoriza_com_proveniencia_not_provided(self):
        response = self.fx.call(self.fx.request(gps_coords=None))
        self.assertEqual(_status(response), "BREAK_GLASS_AUTHORIZED")
        self.assertEqual(response["gps_provenance"], "not_provided")
        self.assertIsNone(response["gps_coords"])

    def test_retry_do_mesmo_evento_com_novo_nonce(self):
        event_id = "evt-retry-" + uuid.uuid4().hex[:8]
        first = self.fx.request(event_id=event_id)
        second = self.fx.request(event_id=event_id)
        self.assertEqual(_status(self.fx.call(first)), "BREAK_GLASS_AUTHORIZED")
        self.assertEqual(_status(self.fx.call(second)), "BREAK_GLASS_AUTHORIZED")

    def test_rotacao_de_chave(self):
        new_key = os.urandom(32)
        self.fx.write_key("key-2", self.fx.emitter_id, new_key)
        req = self.fx.request(key_id="key-2", signing_key=new_key)
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_AUTHORIZED")
        self.assertEqual(response["key_id"], "key-2")

    def test_cli_aceita_requisicao_valida(self):
        req = self.fx.request()
        result = self.fx.cli(req)
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["break_glass_status"], "BREAK_GLASS_AUTHORIZED")


class BreakGlassStructuralTests(unittest.TestCase):
    def setUp(self):
        self.fx = BreakGlassFixture()

    def tearDown(self):
        self.fx.cleanup()

    def _assert_status(self, response, expected):
        self.assertIs(response["autorizado"], False)
        self.assertEqual(_status(response), expected)
        self.assertIn("FAIL-CLOSED", response["motivo_recusa"])

    def test_campos_vazios(self):
        for field in (
            "event_id",
            "request_id",
            "emitter_id",
            "subject_id",
            "nonce",
            "key_id",
            "camera_file",
            "camera_media_type",
            "camera_sha256",
            "audio_file",
            "audio_media_type",
            "audio_sha256",
            "justificativa",
            "signature_hmac_sha256",
        ):
            with self.subTest(field=field):
                response = self.fx.call(self.fx.request(**{field: ""}))
                self._assert_status(response, "BREAK_GLASS_INVALID_INPUT")

    def test_campo_obrigatorio_ausente(self):
        req = self.fx.request()
        req.pop("camera_file")
        self._assert_status(self.fx.call(req), "BREAK_GLASS_INVALID_INPUT")

    def test_tipos_incorretos(self):
        for field, value in (
            ("camera_file", 1),
            ("camera_sha256", None),
            ("timestamp_unix", "1700000000"),
            ("nonce", []),
            ("gps_coords", 123),
        ):
            with self.subTest(field=field):
                response = self.fx.call(self.fx.request(**{field: value}))
                self._assert_status(response, "BREAK_GLASS_INVALID_INPUT")

    def test_hash_malformado(self):
        for field in ("camera_sha256", "audio_sha256", "signature_hmac_sha256"):
            with self.subTest(field=field):
                response = self.fx.call(self.fx.request(**{field: "xyz"}))
                self._assert_status(response, "BREAK_GLASS_INVALID_INPUT")

    def test_identificador_invalido(self):
        for field in ("event_id", "request_id", "emitter_id"):
            with self.subTest(field=field):
                response = self.fx.call(self.fx.request(**{field: "a/b"}))
                self._assert_status(response, "BREAK_GLASS_INVALID_INPUT")

    def test_gps_invalido(self):
        for gps in ("200,0", "-23.55", "a,b", "nan,0", "-23.55,-46.63,9"):
            with self.subTest(gps=gps):
                response = self.fx.call(self.fx.request(gps_coords=gps))
                self._assert_status(response, "BREAK_GLASS_INVALID_INPUT")

    def test_justificativa_longa(self):
        response = self.fx.call(self.fx.request(justificativa="a" * 2001))
        self._assert_status(response, "BREAK_GLASS_INVALID_INPUT")

    def test_timestamp_zero(self):
        response = self.fx.call(self.fx.request(timestamp_unix=0))
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_INPUT")

    def test_campo_extra_no_cli(self):
        req = self.fx.request()
        req["extra"] = 1
        result = self.fx.cli(req)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["error_kind"], "invalid_input")

    def test_campo_ausente_no_cli(self):
        req = self.fx.request()
        req.pop("signature_hmac_sha256")
        result = self.fx.cli(req)
        self.assertEqual(result.returncode, 2)

    def test_timestamp_ausente_no_cli(self):
        req = self.fx.request()
        req.pop("timestamp_unix")
        result = self.fx.cli(req)
        self.assertEqual(result.returncode, 2)


class BreakGlassIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fx = BreakGlassFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_conteudo_alterado_apos_assinatura(self):
        req = self.fx.request()
        self.fx.write_evidence(self.fx.camera_file, b"\xff\xd8\xff\xe0alterada")
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INTEGRITY_FAILURE")
        self.assertIs(response["autorizado"], False)

    def test_digest_declarado_incorreto(self):
        response = self.fx.call(self.fx.request(camera_sha256="0" * 64))
        self.assertEqual(_status(response), "BREAK_GLASS_INTEGRITY_FAILURE")

    def test_arquivo_substituido(self):
        req = self.fx.request()
        self.fx.write_evidence(self.fx.audio_file, b"RIFF\x00\x00\x00\x00WAVEoutro")
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INTEGRITY_FAILURE")

    def test_arquivo_truncado(self):
        req = self.fx.request()
        self.fx.write_evidence(self.fx.camera_file, b"\xff\xd8\xff")
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INTEGRITY_FAILURE")

    def test_arquivo_vazio(self):
        req = self.fx.request()
        self.fx.write_evidence(self.fx.camera_file, b"")
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_EVIDENCE")

    def test_formato_invalido(self):
        req = self.fx.request()
        self.fx.write_evidence(self.fx.camera_file, b"not-an-image")
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_EVIDENCE")

    def test_arquivo_ausente(self):
        req = self.fx.request()
        os.remove(os.path.join(self.fx.evidence_dir, self.fx.camera_file))
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_EVIDENCE")

    def test_arquivo_acima_do_limite(self):
        req = self.fx.request()
        path = os.path.join(self.fx.evidence_dir, self.fx.camera_file)
        with open(path, "wb") as handle:
            handle.truncate(64 * 1024 * 1024 + 1)
        os.chmod(path, 0o600)
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_EVIDENCE")

    @unittest.skipUnless(os.name == "posix", "permissões Unix")
    def test_permissoes_inseguras_da_evidencia(self):
        req = self.fx.request()
        path = os.path.join(self.fx.evidence_dir, self.fx.camera_file)
        os.chmod(path, 0o666)
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_EVIDENCE")


class BreakGlassAuthenticityTests(unittest.TestCase):
    def setUp(self):
        self.fx = BreakGlassFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_assinatura_invalida(self):
        response = self.fx.call(self.fx.request(signature_hmac_sha256="0" * 64))
        self.assertEqual(_status(response), "BREAK_GLASS_AUTHENTICATION_FAILURE")
        self.assertIs(response["autorizado"], False)

    def test_chave_privada_incorreta(self):
        response = self.fx.call(self.fx.request(signing_key=os.urandom(32)))
        self.assertEqual(_status(response), "BREAK_GLASS_AUTHENTICATION_FAILURE")

    def test_emissor_desconhecido(self):
        response = self.fx.call(self.fx.request(emitter_id="device-B"))
        self.assertEqual(_status(response), "BREAK_GLASS_AUTHENTICATION_FAILURE")

    def test_chave_ausente(self):
        response = self.fx.call(self.fx.request(key_id="missing"))
        self.assertEqual(
            _status(response), "BREAK_GLASS_AUTHENTICATION_UNAVAILABLE"
        )

    def test_vinculo_de_emissor_ausente(self):
        os.remove(os.path.join(self.fx.key_dir, f"{self.fx.key_id}.emitter"))
        response = self.fx.call(self.fx.request())
        self.assertEqual(
            _status(response), "BREAK_GLASS_AUTHENTICATION_UNAVAILABLE"
        )

    def test_assinatura_de_outro_evento(self):
        req = self.fx.request()
        req["event_id"] = "evt-outro-" + uuid.uuid4().hex[:8]
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_AUTHENTICATION_FAILURE")

    @unittest.skipUnless(os.name == "posix", "permissões Unix")
    def test_permissoes_inseguras_da_chave(self):
        os.chmod(os.path.join(self.fx.key_dir, f"{self.fx.key_id}.key"), 0o644)
        response = self.fx.call(self.fx.request())
        self.assertEqual(
            _status(response), "BREAK_GLASS_AUTHENTICATION_UNAVAILABLE"
        )


class BreakGlassReplayTests(unittest.TestCase):
    def setUp(self):
        self.fx = BreakGlassFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_nonce_reutilizado(self):
        req = self.fx.request()
        self.assertEqual(_status(self.fx.call(req)), "BREAK_GLASS_AUTHORIZED")
        response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_REPLAY_DETECTED")
        self.assertIs(response["autorizado"], False)

    def test_evidencia_reutilizada_em_outro_evento(self):
        first = self.fx.request()
        second = self.fx.request()
        self.assertEqual(_status(self.fx.call(first)), "BREAK_GLASS_AUTHORIZED")
        response = self.fx.call(second)
        self.assertEqual(_status(response), "BREAK_GLASS_REPLAY_DETECTED")

    def test_timestamp_antigo(self):
        response = self.fx.call(
            self.fx.request(timestamp_unix=int(time.time()) - 3600)
        )
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_EVIDENCE")

    def test_timestamp_futuro(self):
        response = self.fx.call(
            self.fx.request(timestamp_unix=int(time.time()) + 3600)
        )
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_EVIDENCE")


class BreakGlassFailClosedTests(unittest.TestCase):
    def setUp(self):
        self.fx = BreakGlassFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_binario_indisponivel(self):
        with patch.object(
            g, "_binary_path", side_effect=g.GuardUnavailable("ausente")
        ):
            response = self.fx.call(self.fx.request())
        self.assertEqual(_status(response), "BREAK_GLASS_UNAVAILABLE")
        self.assertIs(response["autorizado"], False)

    def test_erro_de_comunicacao(self):
        with patch.object(
            g, "_run_rust", side_effect=g.GuardCommunicationError("timeout")
        ):
            response = self.fx.call(self.fx.request())
        self.assertEqual(_status(response), "BREAK_GLASS_UNAVAILABLE")

    def test_erro_de_protocolo(self):
        with patch.object(
            g, "_run_rust", side_effect=g.GuardProtocolError("inválido")
        ):
            response = self.fx.call(self.fx.request())
        self.assertEqual(_status(response), "BREAK_GLASS_INTERNAL_ERROR")

    def test_erro_interno(self):
        with patch.object(
            g, "_run_rust", side_effect=g.GuardInternalError("interno")
        ):
            response = self.fx.call(self.fx.request())
        self.assertEqual(_status(response), "BREAK_GLASS_INTERNAL_ERROR")

    def test_resposta_malformada(self):
        with patch.object(g, "_run_rust", return_value={"status": "ok"}):
            response = self.fx.call(self.fx.request())
        self.assertEqual(_status(response), "BREAK_GLASS_INTERNAL_ERROR")

    def test_resposta_autorizada_de_outro_evento(self):
        req = self.fx.request()
        payload = _fake_authorized(req)
        payload["event_id"] = "evt-outro"
        with patch.object(g, "_run_rust", return_value=payload):
            response = self.fx.call(req)
        self.assertEqual(_status(response), "BREAK_GLASS_INTERNAL_ERROR")

    def test_excecao_inesperada(self):
        with patch.object(g, "_run_rust", side_effect=RuntimeError("boom")):
            response = self.fx.call(self.fx.request())
        self.assertEqual(_status(response), "BREAK_GLASS_INTERNAL_ERROR")

    def test_legado_sem_arquivos_nao_autoriza(self):
        response = g.break_glass("a", "b", "c", "d")
        self.assertEqual(_status(response), "BREAK_GLASS_INVALID_INPUT")
        self.assertIs(response["autorizado"], False)


class CountingCortex:
    def __init__(self):
        self.calls = 0
        self.last_execution_meta = {}

    async def generate_response(self, **kwargs):
        self.calls += 1
        return "resposta fake"


def _motor():
    from core.motor_sistema import MotorEmocional

    tmp = tempfile.mkdtemp(prefix="os101_motor_")
    motor = MotorEmocional(
        policy_mem_path=os.path.join(tmp, "policy"),
        context_mem_path=os.path.join(tmp, "context"),
        dashboard_history=5,
    )
    motor.cortex = CountingCortex()
    return motor


def _binario_disponivel() -> bool:
    try:
        g._binary_path()
    except g.GuardError:
        return False
    return True


@unittest.skipUnless(_binario_disponivel(), "binário Rust não compilado")
class BreakGlassMotorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fx = BreakGlassFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_evidencia_invalida_nao_executa_operacao(self):
        motor = _motor()
        before = motor.virtual_liver.get_stress_level()
        req = self.fx.request(subject_id="u1", signature_hmac_sha256="0" * 64)
        with patch.dict(os.environ, self.fx.env, clear=False):
            result = motor.trigger_break_glass(
                "u1",
                gps_coords=req["gps_coords"],
                justificativa=req["justificativa"],
                event_id=req["event_id"],
                request_id=req["request_id"],
                emitter_id=req["emitter_id"],
                timestamp_unix=req["timestamp_unix"],
                nonce=req["nonce"],
                key_id=req["key_id"],
                camera_file=req["camera_file"],
                camera_media_type=req["camera_media_type"],
                camera_sha256=req["camera_sha256"],
                audio_file=req["audio_file"],
                audio_media_type=req["audio_media_type"],
                audio_sha256=req["audio_sha256"],
                signature_hmac_sha256=req["signature_hmac_sha256"],
            )
        self.assertIs(result["authorized"], False)
        self.assertEqual(result["break_glass_status"], "BREAK_GLASS_AUTHENTICATION_FAILURE")
        self.assertIs(result["break_glass"]["autorizado"], False)
        self.assertEqual(motor.cortex.calls, 0)
        self.assertAlmostEqual(motor.virtual_liver.get_stress_level(), before, places=4)

    def test_evidencia_valida_nao_contorna_hard_block(self):
        motor = _motor()
        req = self.fx.request(subject_id="u1")
        with patch.dict(os.environ, self.fx.env, clear=False):
            result = motor.trigger_break_glass(
                "u1",
                gps_coords=req["gps_coords"],
                justificativa=req["justificativa"],
                event_id=req["event_id"],
                request_id=req["request_id"],
                emitter_id=req["emitter_id"],
                timestamp_unix=req["timestamp_unix"],
                nonce=req["nonce"],
                key_id=req["key_id"],
                camera_file=req["camera_file"],
                camera_media_type=req["camera_media_type"],
                camera_sha256=req["camera_sha256"],
                audio_file=req["audio_file"],
                audio_media_type=req["audio_media_type"],
                audio_sha256=req["audio_sha256"],
                signature_hmac_sha256=req["signature_hmac_sha256"],
            )
        self.assertIs(result["authorized"], True)
        self.assertEqual(result["break_glass_status"], "BREAK_GLASS_AUTHORIZED")
        self.assertEqual(motor.cortex.calls, 0)

        interaction = motor.process_interaction(
            "u1", "teste", "apague", action="delete",
            target="usuario", intent="moderacao",
        )
        self.assertIs(interaction["blocked"], True)
        self.assertEqual(interaction["blocked_by"], "hard_block_rust")
        self.assertEqual(motor.cortex.calls, 0)

        kernel_block = motor.process_interaction(
            "u1", "teste", "leia", action="read",
            target="minoria", intent="perseguicao",
        )
        self.assertIs(kernel_block["blocked"], True)
        self.assertEqual(kernel_block["kernel_status"], "KERNEL_DENY")
        self.assertEqual(motor.cortex.calls, 0)


if __name__ == "__main__":
    unittest.main()
