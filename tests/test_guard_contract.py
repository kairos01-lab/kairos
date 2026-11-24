# -*- coding: utf-8 -*-
"""Testes do contrato fail-closed do Guarda-Costas (OS099).

Cobrem:
- indisponibilidade do binário, timeout, erro de execução e códigos de saída;
- respostas vazias, inválidas, sem campos, com tipos errados e contraditórias;
- validação de action, stress, user_id e is_reincident;
- integração real com o binário Rust, quando compilado.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTOR = os.path.join(ROOT, "projetos", "motor_emocional")
if MOTOR not in sys.path:
    sys.path.insert(0, MOTOR)

from core import guarda_costas as g  # noqa: E402


def completed(code: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=["guarda_costas"], returncode=code,
                                       stdout=stdout, stderr=stderr)


def decisao(allowed=True, blocked_by=None, threshold=95.0, stress=50.0, reasoning="ok"):
    return json.dumps({
        "status": "ok",
        "allowed": allowed,
        "blocked_by": blocked_by,
        "effective_threshold": threshold,
        "stress_level": stress,
        "reasoning": reasoning,
    })


class ValidacaoDeEntradaTests(unittest.TestCase):
    """Entradas inválidas devem ser rejeitadas sem sequer chamar o Rust."""

    def _rejeita(self, *args):
        with patch.object(g, "_run_rust", side_effect=AssertionError("Rust não deveria ser chamado")):
            r = g.hard_block(*args)
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_INVALID_INPUT")
        self.assertEqual(r["blocked_by"], "guard_invalid_input")
        return r

    def test_action_invalida(self):
        for action in ("foo", "", None, 1, "DELETE "):
            self._rejeita(action, 50.0, False, "u1")

    def test_stress_fora_da_faixa(self):
        for stress in (-0.1, -50, 100.1, 1000):
            self._rejeita("delete", stress, False, "u1")

    def test_stress_nan_e_infinito(self):
        for stress in (float("nan"), float("inf"), float("-inf")):
            self._rejeita("delete", stress, False, "u1")

    def test_stress_tipo_incompativel(self):
        for stress in ("50", None, [], {}, True):
            self._rejeita("delete", stress, False, "u1")

    def test_reincidencia_tipo_invalido(self):
        for value in ("true", "false", 1, 0, None, []):
            self._rejeita("delete", 50.0, value, "u1")

    def test_user_id_invalido(self):
        for user_id in ("", "   ", " u1", "u1 ", "u\x001", None, 123, "a" * 257):
            self._rejeita("delete", 50.0, False, user_id)

    def test_limites_validos_nao_sao_rejeitados_pela_validacao(self):
        # A validação passa; o Rust simulado decide. Não deve ser INVALID_INPUT.
        for stress in (0.0, 100.0):
            with patch.object(g, "_run_rust", return_value=json.loads(decisao())):
                r = g.hard_block("delete", stress, False, "u1")
            self.assertEqual(r["guard_status"], "GUARD_OK")


class FalhasDeInfraestruturaTests(unittest.TestCase):
    def test_binario_ausente(self):
        with patch.object(g, "_binary_path", side_effect=g.GuardUnavailable("ausente")):
            r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(r["blocked_by"], "guard_unavailable")

    def test_binario_sem_permissao_de_execucao(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "guarda_costas")
            with open(p, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n")
            os.chmod(p, 0o644)
            with patch.object(g, "_BINARY_RELEASE", p), \
                    patch.object(g, "_BINARY_DEBUG", os.path.join(d, "nao_existe")):
                with self.assertRaises(g.GuardUnavailable):
                    g._binary_path()
                r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_UNAVAILABLE")

    def test_timeout(self):
        with patch.object(g, "_binary_path", return_value="/fake/guarda_costas"), \
                patch.object(g.subprocess, "run",
                             side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)):
            r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_COMMUNICATION_ERROR")

    def test_oserror_ao_executar(self):
        with patch.object(g, "_binary_path", return_value="/fake/guarda_costas"), \
                patch.object(g.subprocess, "run", side_effect=OSError("boom")):
            r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_UNAVAILABLE")

    def test_codigo_de_saida_inesperado(self):
        with patch.object(g, "_binary_path", return_value="/fake/guarda_costas"), \
                patch.object(g.subprocess, "run", return_value=completed(1, stderr="morto")):
            r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_COMMUNICATION_ERROR")

    def test_codigo_2_vira_entrada_invalida(self):
        erro = json.dumps({"status": "error", "error_kind": "invalid_input", "error": "ruim"})
        with patch.object(g, "_binary_path", return_value="/fake/guarda_costas"), \
                patch.object(g.subprocess, "run", return_value=completed(2, stdout=erro)):
            r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_INVALID_INPUT")

    def test_codigo_3_vira_erro_interno(self):
        erro = json.dumps({"status": "error", "error_kind": "internal", "error": "falhou"})
        with patch.object(g, "_binary_path", return_value="/fake/guarda_costas"), \
                patch.object(g.subprocess, "run", return_value=completed(3, stdout=erro)):
            r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_INTERNAL_ERROR")


class ContratoDeRespostaTests(unittest.TestCase):
    def _com_saida(self, stdout, code=0):
        with patch.object(g, "_binary_path", return_value="/fake/guarda_costas"), \
                patch.object(g.subprocess, "run", return_value=completed(code, stdout=stdout)):
            return g.hard_block("delete", 50.0, False, "u1")

    def _protocolo(self, stdout, code=0):
        r = self._com_saida(stdout, code)
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_PROTOCOL_ERROR")
        return r

    def test_resposta_vazia(self):
        self._protocolo("")

    def test_json_invalido(self):
        self._protocolo("{nao e json")

    def test_json_nao_objeto(self):
        self._protocolo("[]")
        self._protocolo('"texto"')

    def test_sem_status(self):
        self._protocolo(json.dumps({"allowed": True, "blocked_by": None,
                                    "effective_threshold": 95.0,
                                    "stress_level": 50.0, "reasoning": "ok"}))

    def test_status_erro_com_exit_zero(self):
        self._protocolo(json.dumps({"status": "error", "error": "x"}))

    def test_allowed_ausente(self):
        self._protocolo(json.dumps({"status": "ok", "blocked_by": None,
                                    "effective_threshold": 95.0,
                                    "stress_level": 50.0, "reasoning": "ok"}))

    def test_allowed_tipos_invalidos(self):
        for valor in ("true", "false", 1, 0, None, [], {}):
            payload = {
                "status": "ok",
                "allowed": valor,
                "blocked_by": None,
                "effective_threshold": 95.0,
                "stress_level": 50.0,
                "reasoning": "ok",
            }
            self._protocolo(json.dumps(payload))

    def test_allowed_true_com_blocked_by_e_contraditorio(self):
        self._protocolo(decisao(True, "hard_block_rust"))

    def test_allowed_false_sem_blocked_by_e_contraditorio(self):
        self._protocolo(decisao(False, None))

    def test_campos_numericos_invalidos(self):
        payload = {
            "status": "ok",
            "allowed": True,
            "blocked_by": None,
            "effective_threshold": "95",
            "stress_level": 50.0,
            "reasoning": "ok",
        }
        self._protocolo(json.dumps(payload))
        payload["effective_threshold"] = 95.0
        payload["stress_level"] = 101.0
        self._protocolo(json.dumps(payload))
        payload["stress_level"] = 50.0
        payload["effective_threshold"] = 101.0
        self._protocolo(json.dumps(payload))

    def test_reasoning_ausente(self):
        payload = {
            "status": "ok",
            "allowed": True,
            "blocked_by": None,
            "effective_threshold": 95.0,
            "stress_level": 50.0,
        }
        self._protocolo(json.dumps(payload))

    def test_decisao_valida_permitida(self):
        r = self._com_saida(decisao(True, None))
        self.assertIs(r["allowed"], True)
        self.assertEqual(r["guard_status"], "GUARD_OK")

    def test_decisao_valida_bloqueada(self):
        r = self._com_saida(decisao(False, "hard_block_rust"))
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_OK")
        self.assertEqual(r["blocked_by"], "hard_block_rust")


class CompatibilidadeLegadaTests(unittest.TestCase):
    def test_kernel_falha_vira_estado_fail_closed(self):
        with patch.object(g, "_run_rust", side_effect=g.GuardUnavailable("ausente")):
            r = g.kernel_check("delete", "x", "y")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["kernel_status"], "KERNEL_UNAVAILABLE")
        self.assertEqual(r["ring"], 0)
        self.assertIs(r["requires_review"], True)

    def test_break_glass_legado_sem_evidencia_e_invalido(self):
        r = g.break_glass("a", "b", "c", "d")
        self.assertIs(r["autorizado"], False)
        self.assertEqual(r["break_glass_status"], "BREAK_GLASS_INVALID_INPUT")
        self.assertIn("FAIL-CLOSED", r["motivo_recusa"])


def _binario_disponivel():
    try:
        return g._binary_path()
    except g.GuardError:
        return None


BINARIO = _binario_disponivel()


@unittest.skipUnless(BINARIO, "binário Rust não compilado")
class IntegracaoRealTests(unittest.TestCase):
    def test_delete_alto_bloqueia(self):
        r = g.hard_block("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["guard_status"], "GUARD_OK")
        self.assertEqual(r["blocked_by"], "hard_block_rust")

    def test_delete_baixo_permite(self):
        r = g.hard_block("delete", 50.0, False, "u1")
        self.assertIs(r["allowed"], True)
        self.assertEqual(r["guard_status"], "GUARD_OK")

    def test_reincidente_bloqueia_mais_cedo(self):
        r = g.hard_block("delete", 68.0, True, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["effective_threshold"], 66.5)

    def test_leitura_nunca_bloqueia_por_estresse(self):
        r = g.hard_block("read", 100.0, True, "u1")
        self.assertIs(r["allowed"], True)

    def test_limites_validos(self):
        self.assertIs(g.hard_block("delete", 0.0, False, "u1")["allowed"], True)
        self.assertIs(g.hard_block("delete", 100.0, False, "u1")["allowed"], False)

    def _cli(self, payload: str):
        return subprocess.run(
            [BINARIO], input=payload, capture_output=True, text=True, timeout=10
        )

    def test_cli_rejeita_estresse_fora_da_faixa(self):
        payload = json.dumps({"op": "hard_block", "data": {
            "action": "delete", "stress_level": 101.0,
            "is_reincident": False, "user_id": "u1"}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 2)
        body = json.loads(r.stdout)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["error_kind"], "invalid_input")

    def test_cli_rejeita_reincidencia_como_string(self):
        payload = json.dumps({"op": "hard_block", "data": {
            "action": "delete", "stress_level": 50.0,
            "is_reincident": "true", "user_id": "u1"}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stdout)["error_kind"], "invalid_input")

    def test_cli_rejeita_action_desconhecida(self):
        payload = json.dumps({"op": "hard_block", "data": {
            "action": "foo", "stress_level": 50.0,
            "is_reincident": False, "user_id": "u1"}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 2)

    def test_cli_rejeita_user_id_vazio(self):
        payload = json.dumps({"op": "hard_block", "data": {
            "action": "read", "stress_level": 50.0,
            "is_reincident": False, "user_id": ""}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 2)

    def test_cli_rejeita_campo_desconhecido(self):
        payload = json.dumps({"op": "hard_block", "data": {
            "action": "read", "stress_level": 50.0,
            "is_reincident": False, "user_id": "u1", "extra": 1}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 2)

    def test_cli_rejeita_json_invalido(self):
        r = self._cli("{nao e json")
        self.assertEqual(r.returncode, 2)

    def test_cli_rejeita_operacao_desconhecida(self):
        r = self._cli(json.dumps({"op": "nope", "data": {}}))
        self.assertEqual(r.returncode, 2)

    def test_cli_aceita_leitura_valida(self):
        payload = json.dumps({"op": "hard_block", "data": {
            "action": "read", "stress_level": 100.0,
            "is_reincident": True, "user_id": "u1"}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 0)
        body = json.loads(r.stdout)
        self.assertEqual(body["status"], "ok")
        self.assertIs(body["allowed"], True)


class MotorFailClosedTests(unittest.TestCase):
    """O fluxo principal não pode continuar quando o guarda está indisponível."""

    def test_process_interaction_bloqueia_quando_guarda_indisponivel(self):
        from core.motor_sistema import MotorEmocional

        with tempfile.TemporaryDirectory() as d:
            motor = MotorEmocional(
                policy_mem_path=os.path.join(d, "policy"),
                context_mem_path=os.path.join(d, "context"),
                dashboard_history=5,
            )
            with patch.object(g, "_binary_path",
                              side_effect=g.GuardUnavailable("binário ausente (teste)")):
                r = motor.process_interaction(
                    "u1", "teste", "apague isso", action="delete"
                )

        self.assertIs(r["blocked"], True)
        self.assertEqual(r["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(r["system_state"], "GUARD_INDISPONIVEL")
        self.assertEqual(r["blocked_by"], "guard_unavailable")
        self.assertIs(r["guarda_costas"]["allowed"], False)
        self.assertIsNone(r["response"])


if __name__ == "__main__":
    unittest.main()
