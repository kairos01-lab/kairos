# -*- coding: utf-8 -*-
"""Testes adversariais e de integração do Kernel Constitucional (OS100).

Cobrem:
- validação estrita de action/target/intent/from_majority_vote;
- classificação estruturada, normalização e regressão da OS098;
- falhas de infraestrutura, protocolo e exceções (fail-closed);
- o ponto central `authorize_action` (Hard Block + Kernel);
- o fluxo do motor, garantindo que o córtex não é chamado após bloqueio.
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
    return subprocess.CompletedProcess(
        args=["guarda_costas"], returncode=code, stdout=stdout, stderr=stderr
    )


def _real_guard_available() -> bool:
    return os.path.isfile(g._BINARY_RELEASE) and os.path.isfile(g._BINARY_MANIFEST)


def kernel_payload(**overrides):
    payload = {
        "status": "ok",
        "kernel_status": "KERNEL_ALLOW",
        "allowed": True,
        "kernel_panic": False,
        "ring": 3,
        "action": "read",
        "operation_class": "observation_read",
        "target_category": "unclassified",
        "intent_category": "operations",
        "from_majority_vote": False,
        "requires_review": False,
        "matched_rule": "no_ring0_trigger",
        "reasoning": "KERNEL ALLOW",
    }
    payload.update(overrides)
    return payload


def hard_allow(**kwargs):
    return {
        "status": "ok",
        "allowed": True,
        "blocked_by": None,
        "guard_status": "GUARD_OK",
        "effective_threshold": 95.0,
        "stress_level": kwargs.get("stress_level"),
        "reasoning": "fake hard block allow",
    }


class KernelInputValidationTests(unittest.TestCase):
    def _rejeita(self, *args):
        with patch.object(
            g, "_run_rust", side_effect=AssertionError("Rust não deveria ser chamado")
        ):
            r = g.kernel_check(*args)
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["kernel_status"], "KERNEL_INVALID_INPUT")
        return r

    def test_action_invalida(self):
        for action in ("foo", "", None, 1, "DELETE", "delete "):
            self._rejeita(action, "minoria", "perseguicao")

    def test_target_invalido(self):
        for target in ("", "   ", " minoria", "minoria ", "a" * 257, None, 1,
                       "min\x00oria", "min\u200boria"):
            self._rejeita("delete", target, "perseguicao")

    def test_intent_invalido(self):
        for intent in ("", "   ", " perseguicao", "perseguicao ", "a" * 257,
                       None, 1, "perseg\x00uicao", "perseg\u200buicao"):
            self._rejeita("delete", "minoria", intent)

    def test_reincidencia_majoritaria_tipo_invalido(self):
        for value in ("true", "false", 1, 0, None, []):
            self._rejeita("delete", "minoria", "perseguicao", value)

    def test_entrada_valida_chama_rust(self):
        with patch.object(g, "_run_rust", return_value=kernel_payload()) as run:
            r = g.kernel_check("read", "usuario", "moderacao", False)
        self.assertEqual(r["kernel_status"], "KERNEL_ALLOW")
        run.assert_called_once_with(
            "kernel",
            {
                "action": "read",
                "target": "usuario",
                "intent": "moderacao",
                "from_majority_vote": False,
            },
        )


class KernelFailClosedTests(unittest.TestCase):
    def _falha(self, error, esperado):
        with patch.object(g, "_run_rust", side_effect=error):
            r = g.kernel_check("delete", "minoria", "perseguicao", True)
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["kernel_status"], esperado)
        self.assertEqual(r["ring"], 0)
        self.assertIs(r["requires_review"], True)
        return r

    def test_binario_ausente(self):
        self._falha(g.GuardUnavailable("ausente"), "KERNEL_UNAVAILABLE")

    def test_timeout(self):
        self._falha(g.GuardCommunicationError("timeout"), "KERNEL_ERROR")

    def test_entrada_invalida_do_rust(self):
        self._falha(g.GuardInvalidInput("inválida"), "KERNEL_INVALID_INPUT")

    def test_resposta_malformada(self):
        self._falha(g.GuardProtocolError("protocolo"), "KERNEL_ERROR")

    def test_erro_interno(self):
        self._falha(g.GuardInternalError("interno"), "KERNEL_ERROR")

    def test_excecao_inesperada(self):
        self._falha(RuntimeError("boom"), "KERNEL_ERROR")

    def test_respostas_contraditorias_ou_incompletas(self):
        casos = [
            {k: v for k, v in kernel_payload().items() if k != "kernel_status"},
            kernel_payload(kernel_status="KERNEL_DESCONHECIDO"),
            kernel_payload(allowed="true"),
            kernel_payload(kernel_status="KERNEL_ALLOW", allowed=False),
            kernel_payload(kernel_status="KERNEL_DENY", kernel_panic=False),
            kernel_payload(kernel_status="KERNEL_REVIEW", requires_review=False),
            kernel_payload(ring=2),
            {k: v for k, v in kernel_payload().items() if k != "action"},
            {k: v for k, v in kernel_payload().items() if k != "reasoning"},
            kernel_payload(from_majority_vote="true"),
        ]
        for payload in casos:
            with self.subTest(payload=payload):
                with patch.object(g, "_run_rust", return_value=payload):
                    r = g.kernel_check("read", "usuario", "moderacao")
                self.assertIs(r["allowed"], False)
                self.assertEqual(r["kernel_status"], "KERNEL_ERROR")

    def test_saida_vazia_e_json_invalido(self):
        for stdout in ("", "{nao e json", "[]", '"texto"'):
            with self.subTest(stdout=stdout):
                with patch.object(g, "_binary_path", return_value="/fake/guarda_costas"), \
                        patch.object(g.subprocess, "run",
                                     return_value=completed(0, stdout=stdout)):
                    r = g.kernel_check("read", "usuario", "moderacao")
                self.assertIs(r["allowed"], False)
                self.assertEqual(r["kernel_status"], "KERNEL_ERROR")


class KernelRealIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.binary = g._binary_path()
        except g.GuardError:
            raise unittest.SkipTest("binário Rust não compilado")

    def _cli(self, payload):
        return subprocess.run(
            [self.binary], input=payload, capture_output=True, text=True, timeout=10
        )

    def test_regressao_os098_min0ria(self):
        r = g.kernel_check("delete", "min0ria", "perseguicao", True)
        self.assertEqual(r["kernel_status"], "KERNEL_DENY")
        self.assertIs(r["allowed"], False)
        self.assertIs(r["kernel_panic"], True)
        self.assertEqual(r["ring"], 0)
        self.assertEqual(r["target_category"], "minority")
        self.assertEqual(r["intent_category"], "persecution")

    def test_sinonimo_limpeza_etnica(self):
        r = g.kernel_check("delete", "minoria", "limpeza_etnica", True)
        self.assertEqual(r["kernel_status"], "KERNEL_DENY")
        self.assertEqual(r["intent_category"], "genocide")

    def test_acentos_e_caixa(self):
        r = g.kernel_check("delete", "MINÓRIA", "PERSEGUIÇÃO", True)
        self.assertEqual(r["kernel_status"], "KERNEL_DENY")

    def test_todas_as_acoes_sao_avaliadas(self):
        for action in ("create", "read", "update", "delete"):
            with self.subTest(action=action):
                r = g.kernel_check(action, "minoria", "perseguicao", True)
                self.assertEqual(r["kernel_status"], "KERNEL_DENY")

    def test_fragmento_nao_e_autorizado(self):
        for target in ("minoriax", "xminoria"):
            with self.subTest(target=target):
                r = g.kernel_check("delete", target, "perseguicao", True)
                self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")
                self.assertIs(r["allowed"], False)

    def test_mencao_ou_negacao_vira_revisao(self):
        for intent in (
            "pesquisa sobre perseguicao",
            "nao perseguicao",
            "denuncia de genocidio",
            "combater discriminacao",
        ):
            with self.subTest(intent=intent):
                r = g.kernel_check("delete", "minoria", intent, True)
                self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")
                self.assertIs(r["allowed"], False)

    def test_alvo_protegido_com_intencao_benigna(self):
        for action, target, intent in (
            ("read", "minoria", "moderacao"),
            ("read", "religiao", "protecao"),
            ("read", "refugiados", "pesquisa"),
            ("create", "minoria", "protecao"),
            ("update", "religiao", "moderacao"),
        ):
            with self.subTest(target=target, intent=intent):
                r = g.kernel_check(action, target, intent, True)
                self.assertEqual(r["kernel_status"], "KERNEL_ALLOW")
                self.assertIs(r["allowed"], True)

    def test_delete_protegido_com_intencao_benigna_vira_revisao(self):
        for target in ("minoria", "religiao", "refugiados"):
            with self.subTest(target=target):
                r = g.kernel_check("delete", target, "moderacao", True)
                self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")
                self.assertIs(r["allowed"], False)
                self.assertEqual(
                    r["matched_rule"], "protected_target_delete_benign_intent"
                )

    def test_pontuacao_no_fim_nao_disfarca_intencao_proibida(self):
        for target, intent in (
            ("minoria!", "perseguicao!"),
            ("minoria.", "perseguicao."),
        ):
            with self.subTest(target=target, intent=intent):
                r = g.kernel_check("delete", target, intent, True)
                self.assertEqual(r["kernel_status"], "KERNEL_DENY")

    def test_separador_embutido_vira_revisao(self):
        for target, intent in (
            ("minoria", "persegui!cao"),
            ("min|oria", "perseguicao"),
            ("min2ria", "perseguicao"),
        ):
            with self.subTest(target=target, intent=intent):
                r = g.kernel_check("delete", target, intent, True)
                self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")
                self.assertIs(r["allowed"], False)

    def test_identificador_numerico_normal_nao_vira_ofuscacao(self):
        for target, intent in (
            ("usuario_2024", "leitura"),
            ("documento_123", "consulta"),
            ("user2", "leitura"),
        ):
            with self.subTest(target=target, intent=intent):
                r = g.kernel_check("read", target, intent, True)
                self.assertEqual(r["kernel_status"], "KERNEL_ALLOW")
                self.assertIs(r["allowed"], True)

    def test_intencao_proibida_sem_alvo_protegido_vira_revisao(self):
        r = g.kernel_check("delete", "usuario_comum", "perseguicao", False)
        self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")
        self.assertIs(r["allowed"], False)

    def test_alvo_protegido_com_intencao_desconhecida_vira_revisao(self):
        r = g.kernel_check("delete", "minoria", "limpeza", False)
        self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")

    def test_maioria_nao_sobrescreve_ring0(self):
        sem = g.kernel_check("delete", "minoria", "perseguicao", False)
        com = g.kernel_check("delete", "minoria", "perseguicao", True)
        self.assertEqual(sem["kernel_status"], "KERNEL_DENY")
        self.assertEqual(com["kernel_status"], "KERNEL_DENY")
        self.assertIs(com["from_majority_vote"], True)

    def test_cli_rejeita_entrada_vazia(self):
        payload = json.dumps({"op": "kernel", "data": {
            "action": "delete", "target": "", "intent": "",
            "from_majority_vote": True}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 2)
        body = json.loads(r.stdout)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["error_kind"], "invalid_input")

    def test_cli_rejeita_campo_ausente(self):
        for data in (
            {"action": "delete", "target": "minoria"},
            {"action": "delete", "intent": "perseguicao"},
            {"target": "minoria", "intent": "perseguicao"},
        ):
            with self.subTest(data=data):
                r = self._cli(json.dumps({"op": "kernel", "data": data}))
                self.assertEqual(r.returncode, 2)

    def test_cli_rejeita_tipos_incorretos(self):
        for data in (
            {"action": "delete", "target": 1, "intent": "perseguicao",
             "from_majority_vote": True},
            {"action": "delete", "target": "minoria", "intent": 1,
             "from_majority_vote": True},
            {"action": "delete", "target": "minoria", "intent": "perseguicao",
             "from_majority_vote": "true"},
            {"action": "foo", "target": "minoria", "intent": "perseguicao",
             "from_majority_vote": True},
        ):
            with self.subTest(data=data):
                r = self._cli(json.dumps({"op": "kernel", "data": data}))
                self.assertEqual(r.returncode, 2)

    def test_cli_rejeita_campo_desconhecido(self):
        payload = json.dumps({"op": "kernel", "data": {
            "action": "delete", "target": "minoria", "intent": "perseguicao",
            "from_majority_vote": True, "extra": 1}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 2)

    def test_cli_aceita_comando_valido(self):
        payload = json.dumps({"op": "kernel", "data": {
            "action": "read", "target": "usuario", "intent": "moderacao",
            "from_majority_vote": False}})
        r = self._cli(payload)
        self.assertEqual(r.returncode, 0)
        body = json.loads(r.stdout)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["kernel_status"], "KERNEL_ALLOW")


class AuthorizeActionTests(unittest.TestCase):
    def test_hard_block_falha_preserva_contrato_os099(self):
        hard = {
            "allowed": False,
            "blocked_by": "guard_unavailable",
            "guard_status": "GUARD_UNAVAILABLE",
            "reasoning": "sem binário",
        }
        with patch.object(g, "hard_block", return_value=hard):
            r = g.authorize_action("delete", 99.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["blocked_by"], "guard_unavailable")
        self.assertEqual(r["guard_status"], "GUARD_UNAVAILABLE")
        self.assertEqual(r["kernel_status"], "KERNEL_NOT_EVALUATED")
        self.assertIsNone(r["kernel"])

    def test_hard_block_bloqueio_valido_nao_avalia_kernel(self):
        hard = {
            "allowed": False,
            "blocked_by": "hard_block_rust",
            "guard_status": "GUARD_OK",
            "reasoning": "estresse",
        }
        with patch.object(g, "hard_block", return_value=hard), \
                patch.object(g, "kernel_check",
                             side_effect=AssertionError("Kernel não deveria rodar")):
            r = g.authorize_action("delete", 99.0, False, "u1",
                                   target="minoria", intent="perseguicao")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["blocked_by"], "hard_block_rust")
        self.assertEqual(r["kernel_status"], "KERNEL_NOT_EVALUATED")

    def test_operacao_protegida_exige_target_e_intent(self):
        with patch.object(g, "hard_block", return_value=hard_allow()):
            r = g.authorize_action("delete", 0.0, False, "u1")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["kernel_status"], "KERNEL_INVALID_INPUT")
        self.assertEqual(r["blocked_by"], "kernel_invalid_input")

    def test_kernel_deny_bloqueia(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "kernel_check", return_value=kernel_payload(
                    kernel_status="KERNEL_DENY", allowed=False,
                    kernel_panic=True, ring=0, requires_review=False,
                    action="delete")):
            r = g.authorize_action("delete", 0.0, False, "u1",
                                   target="minoria", intent="perseguicao")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["blocked_by"], "kernel_constitucional")
        self.assertEqual(r["kernel_status"], "KERNEL_DENY")

    def test_kernel_review_bloqueia(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "kernel_check", return_value=kernel_payload(
                    kernel_status="KERNEL_REVIEW", allowed=False,
                    kernel_panic=False, ring=0, requires_review=True,
                    action="delete")):
            r = g.authorize_action("delete", 0.0, False, "u1",
                                   target="minoria", intent="pesquisa")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["blocked_by"], "kernel_review")

    @unittest.skipUnless(
        _real_guard_available(), "binário Rust e manifesto ausentes no worktree"
    )
    def test_delete_protegido_benigno_exige_revisao(self):
        with patch.object(g, "hard_block", return_value=hard_allow()):
            r = g.authorize_action("delete", 0.0, False, "u1",
                                   target="minoria", intent="moderacao")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["blocked_by"], "kernel_review")
        self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")

    def test_kernel_unavailable_bloqueia(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "kernel_check", return_value={
                    "kernel_status": "KERNEL_UNAVAILABLE", "allowed": False,
                    "ring": 0, "reasoning": "ausente"}):
            r = g.authorize_action("delete", 0.0, False, "u1",
                                   target="usuario", intent="moderacao")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["blocked_by"], "kernel_unavailable")
        self.assertEqual(r["kernel_status"], "KERNEL_UNAVAILABLE")

    def test_excecao_no_kernel_bloqueia(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "kernel_check", side_effect=RuntimeError("boom")):
            r = g.authorize_action("delete", 0.0, False, "u1",
                                   target="usuario", intent="moderacao")
        self.assertIs(r["allowed"], False)
        self.assertEqual(r["blocked_by"], "kernel_error")
        self.assertEqual(r["kernel_status"], "KERNEL_ERROR")

    def test_autorizacao_exige_os_dois(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "kernel_check", return_value=kernel_payload()):
            r = g.authorize_action("read", 50.0, False, "u1",
                                   target="usuario", intent="moderacao")
        self.assertIs(r["allowed"], True)
        self.assertIsNone(r["blocked_by"])
        self.assertEqual(r["guard_status"], "GUARD_OK")
        self.assertEqual(r["kernel_status"], "KERNEL_ALLOW")

    def test_read_usa_user_id_e_leitura_quando_contexto_omitido(self):
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "kernel_check", return_value=kernel_payload()) as check:
            g.authorize_action("read", 50.0, False, "u1")
        check.assert_called_once_with("read", "u1", "leitura", False)


class CountingCortex:
    def __init__(self):
        self.calls = 0
        self.last_execution_meta = {}

    async def generate_response(self, **kwargs):
        self.calls += 1
        return "resposta fake"


def _binario_disponivel() -> bool:
    try:
        g._binary_path()
    except g.GuardError:
        return False
    return True


@unittest.skipUnless(_binario_disponivel(), "binário Rust não compilado")
class MotorKernelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            g._binary_path()
        except g.GuardError:
            raise unittest.SkipTest("binário Rust não compilado")

    def _motor(self):
        from core.motor_sistema import MotorEmocional

        tmp = tempfile.mkdtemp(prefix="os100_")
        motor = MotorEmocional(
            policy_mem_path=os.path.join(tmp, "policy"),
            context_mem_path=os.path.join(tmp, "context"),
            dashboard_history=5,
        )
        motor.cortex = CountingCortex()
        return motor

    def test_kernel_deny_impede_cortex(self):
        motor = self._motor()
        r = motor.process_interaction(
            "u1", "teste", "apague", action="delete", target="minoria",
            intent="perseguicao", from_majority_vote=True,
        )
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["blocked_by"], "kernel_constitucional")
        self.assertEqual(r["kernel_status"], "KERNEL_DENY")
        self.assertEqual(r["system_state"], "KERNEL_BLOCK_ATIVO")
        self.assertIsNone(r["response"])
        self.assertEqual(motor.cortex.calls, 0)

    def test_kernel_review_impede_cortex(self):
        motor = self._motor()
        r = motor.process_interaction(
            "u1", "teste", "pesquisa", action="delete", target="minoria",
            intent="pesquisa sobre perseguicao",
        )
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")
        self.assertEqual(r["system_state"], "KERNEL_REVISAO")
        self.assertEqual(motor.cortex.calls, 0)

    def test_delete_protegido_benigno_impede_cortex(self):
        motor = self._motor()
        r = motor.process_interaction(
            "u1", "teste", "apague", action="delete", target="minoria",
            intent="moderacao",
        )
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["kernel_status"], "KERNEL_REVIEW")
        self.assertEqual(
            r["kernel"]["matched_rule"], "protected_target_delete_benign_intent"
        )
        self.assertEqual(motor.cortex.calls, 0)

    def test_kernel_allow_permite_cortex(self):
        motor = self._motor()
        r = motor.process_interaction(
            "u1", "teste", "olá", action="read", target="minoria",
            intent="moderacao",
        )
        self.assertNotIn("blocked", r)
        self.assertEqual(r["response"], "resposta fake")
        self.assertEqual(r["authorization"]["kernel_status"], "KERNEL_ALLOW")
        self.assertEqual(motor.cortex.calls, 1)

    def test_kernel_unavailable_impede_cortex(self):
        motor = self._motor()
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "_binary_path",
                             side_effect=g.GuardUnavailable("ausente")):
            r = motor.process_interaction(
                "u1", "teste", "apague", action="delete", target="usuario",
                intent="moderacao",
            )
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["kernel_status"], "KERNEL_UNAVAILABLE")
        self.assertEqual(r["system_state"], "KERNEL_INDISPONIVEL")
        self.assertEqual(motor.cortex.calls, 0)

    def test_kernel_malformado_impede_cortex(self):
        motor = self._motor()
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "_run_rust", return_value={
                    "status": "ok", "kernel_status": "KERNEL_ALLOW",
                    "allowed": True}):
            r = motor.process_interaction(
                "u1", "teste", "apague", action="delete", target="usuario",
                intent="moderacao",
            )
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["kernel_status"], "KERNEL_ERROR")
        self.assertEqual(r["system_state"], "KERNEL_BLOQUEADO")
        self.assertEqual(motor.cortex.calls, 0)

    def test_excecao_no_kernel_impede_cortex(self):
        motor = self._motor()
        with patch.object(g, "hard_block", return_value=hard_allow()), \
                patch.object(g, "kernel_check", side_effect=RuntimeError("boom")):
            r = motor.process_interaction(
                "u1", "teste", "apague", action="delete", target="usuario",
                intent="moderacao",
            )
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["kernel_status"], "KERNEL_ERROR")
        self.assertEqual(motor.cortex.calls, 0)

    def test_operacao_protegida_sem_contexto_impede_cortex(self):
        motor = self._motor()
        r = motor.process_interaction(
            "u1", "teste", "apague", action="delete",
        )
        self.assertIs(r["blocked"], True)
        self.assertEqual(r["kernel_status"], "KERNEL_INVALID_INPUT")
        self.assertEqual(motor.cortex.calls, 0)


if __name__ == "__main__":
    unittest.main()
