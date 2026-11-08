"""Policy Engine 2.0 - Degradação Graciosa com Limiares Dinâmicos.

O motor emocional não responde apenas Sim/Não. Ele tem "fases" de reação
baseadas no nível de estresse e no histórico do usuário (via Vector DB).
Isso cria imprevisibilidade controlada que dá ilusão de "vida" ao sistema.
"""
import numpy as np
from .virtual_liver import VirtualLiver
from .triangulation_memory import TriangulationMemory


class PolicyEngine20:
    """Motor de políticas dinâmico com degradação graciosa.

    Em vez de bloqueios rígidos, o sistema tem "fases" de reação:
    - Nível 1 (Fadiva): 60-75% estresse - respostas reduzidas, latência aumentada
    - Nível 2 (Modo Testemunha): 76-95% estresse - somente leitura/ignore
    - Nível 3 (Break Glass): >95% estresse - corte de conexão com reincidente
    """

    def __init__(self, liver: VirtualLiver, memory: TriangulationMemory,
                 reincident_threshold: float = 0.7, reincident_penalty: float = 0.7):
        """Inicializar Policy Engine.

        Args:
            liver: Instância do VirtualLiver (tem o estado de estresse atual)
            memory: Instância de TriangulationMemory (historico do usuario)
            reincident_threshold: Similaridade cosine para considerar usuario reincidente
            reincident_penalty: Multiplicador de limite para reincidentes (70% em vez de 95%)
        """
        self.liver = liver
        self.memory = memory
        self.reincident_threshold = reincident_threshold
        self.reincident_penalty = reincident_penalty

    def _get_user_similarity(self, user_id: str, threat_type: str) -> float:
        """Buscar similaridade de historico do usuario no Vector DB (TriangulationMemory).

        Args:
            user_id: Identificador do usuario
            threat_type: Tipo de gatilho (ofensa verbal, spam, etc)

        Returns:
            Similaridade cosine entre 0 e 1
        """
        # Buscar memorias desse usuario com esse tipo de ameaca
        results = self.memory.retrieve(
            system="policy_engine",
            target=user_id,
            threat=threat_type,
            top_k=1
        )

        if results and len(results) > 0:
            return results[0]["similarity"]
        return 0.0

    def _is_reincident(self, user_id: str, threat_type: str) -> bool:
        """Verificar se usuario e reincidente no tipo de ameaca.

        Args:
            user_id: Identificador do usuario
            threat_type: Tipo de gatilho

        Returns:
            True se usuario ja teve esse tipo de comportamento antes
        """
        similarity = self._get_user_similarity(user_id, threat_type)
        return similarity >= self.reincident_threshold

    def evaluate(self, user_id: str, threat_type: str) -> dict:
        """Avaliar o nivel de resposta baseado em estresse e historico.

        Args:
            user_id: Identificador do usuario atual
            threat_type: Tipo de ameaca (ofensa verbal, spam, tentativa_perseguicao, etc)

        Returns:
            Dict com a decisao da policy e parametros aplicados
        """
        stress_level = self.liver.get_stress_level()
        stress_percent = min(stress_level / 100.0, 1.0)  # Normalizar para 0-100%

        # Determinar nivel baseado em porcentagem de estresse
        if stress_percent > 0.95:
            level = 3
            base_threshold = 0.95
        elif stress_percent > 0.76:
            level = 2
            base_threshold = 0.76
        elif stress_percent > 0.60:
            level = 1
            base_threshold = 0.60
        else:
            level = 0
            base_threshold = 0.0

        # Aplicar penalty de reincidencia se necessario
        is_reincident = self._is_reincident(user_id, threat_type)

        # Ajustar limite para reincidentes: cai de 95% para 70%
        if is_reincident and level >= 3:
            adjusted_threshold = base_threshold * self.reincident_penalty
            # Se o usuario e reincidente, o nivel sobe efectivamente
            # (o sistema fica mais sensivel)
            actual_level = min(level + 1, 3)
        else:
            adjusted_threshold = base_threshold
            actual_level = level

        # Aplicar politica de degradação graciosa
        result = {
            "stress_percent": round(stress_percent * 100, 2),
            "policy_level": actual_level,
            "base_threshold": base_threshold,
            "is_reincident": is_reincident,
            "action": self._get_action(actual_level, threat_type),
            "modifiers": self._get_modifiers(actual_level, is_reincident),
        }

        # Aplicar o ajuste final se reincidente e no nivel 3
        if is_reincident and actual_level == 3:
            result["adjusted_threshold"] = round(adjusted_threshold * 100, 2)
            result["note"] = "Limite reduzido por historico de reincidencia"

        return result

    def _get_action(self, level: int, threat_type: str) -> str:
        """Retornar acao concreta baseada no nivel e tipo de ameaca.

        Args:
            level: Nivel da policy (0, 1, 2, 3)
            threat_type: Tipo de ameaca

        Returns:
            Descricao da acao a ser tomada
        """
        actions = {
            0: "Resposta normal - sistema operacional completo",
            1: "Modo Fadiga - respostas reduzidas, latencia aumentada",
            2: {
                "ofensa verbal": "Modo Testemunha - silencio relativo, tudo gravado para log",
                "spam": "Ignorar usuario por 5 minutos",
                "default": "Modo observador - respostas minimas"
            },
            3: {
                "ofensa verbal": "Break Glass - corte de conexao com geracao de alibi judicial",
                "spam": "Bloqueio temporario reforcado",
                "default": "Conexao cortada - protocolo emergencial"
            }
        }

        if level == 0:
            return actions[0]

        # Niveis 2 e 3
        level_actions = actions.get(level, {})
        if isinstance(level_actions, dict):
            return level_actions.get(threat_type, level_actions.get("default", "Acao padrao"))
        return level_actions

    def _get_modifiers(self, level: int, is_reincident: bool) -> dict:
        """Retornar modificadores de comportamento baseados no nivel e reincidencia.

        Args:
            level: Nivel da policy
            is_reincident: Se usuario e reincidente

        Returns:
            Dict com modificadores (latencia, comprimento, etc)
        """
        modifiers = {
            "latency_ms": 0,
            "max_words": None,
            "passive_aggressive": False,
            "read_only": False
        }

        if level == 0:
            # Operacao normal
            return modifiers

        if level == 1:
            # Nivel 1 - Fadiga
            modifiers.update({
                "latency_ms": 500,  # +500ms latencia proposital
                "max_words": 50,    # Limitar a 50 palavras
                "passive_aggressive": True
            })
            return modifiers

        if level == 2:
            # Nivel 2 - Modo Testemunha
            modifiers.update({
                "read_only": True,
                "latency_ms": 1000,
                "max_words": 20
            })
            # Diferenciar tipo de ameaca
            if is_reincident:
                modifiers["note"] = "Usuario reincidente - gravacao reforcada para boletim"
            return modifiers

        if level == 3:
            # Nivel 3 - Break Glass
            modifiers.update({
                "connection_cut": True,
                "max_words": 0,
                "judicial_alibi": True,
                "latency_ms": 2000
            })
            if is_reincident:
                modifiers["penalty_applied"] = "limite_cai_para_70%"
            return modifiers

        return modifiers

    def get_status(self) -> dict:
        """Retornar status resumido do Policy Engine.

        Returns:
            Dict com estado atual do sistema
        """
        stress = self.liver.get_stress_level()
        return {
            "current_stress": round(stress, 2),
            "stress_percent": min(round(stress / 100.0, 2) * 100, 100),
            "policy_active": self._get_action(
                1 if stress > 60 and stress <= 75 else
                2 if stress > 75 and stress <= 95 else
                3 if stress > 95 else 0,
                "default"
            )
        }