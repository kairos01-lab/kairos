"""Fígado Virtual - Gestão de entropia e estresse.

O sistema acumula "estresse" e precisa de tempo para decair e esfriar.
Equação: S_t = S_0 * e^(-λ*t) + Σ(R_i)
- S_0: estresse inicial
- λ: taxa de decaimento (cooling rate)
- t: tempo decorrido
- R_i: gatilhos de memória (ruminação)
"""
import numpy as np
import time


class VirtualLiver:
    """Gerencia o acúmulo e decaimento de estresse (entropia)."""

    def __init__(self, decay_rate: float = 0.003, stress_cap: float = 100.0):
        """Inicializar fígado virtual.
        
        Args:
            decay_rate: λ taxa de decaimento (0 < λ <= 1). Maior = esfria mais rápido.
                        Default 0.003 → meia-vida de ~4 minutos (estresse persiste
                        o suficiente para afetar conversas, mas esfria lentamente).
            stress_cap: S_0 capacidade máxima de estresse.
        """
        self.decay_rate = decay_rate
        self.stress_cap = stress_cap
        self.current_stress = 0.0
        self.last_update = time.time()
        self.memory_triggers = []  # R_i - gatilhos de ruminação

    def add_stress(self, amount: float, trigger: str = None):
        """Adicionar estresse ao sistema.

        Eq: S_t = S_0 * e^(-λ·dt) + R_i
        - Primeiro decai o estresse acumulado (S_0) pelo tempo decorrido (dt)
        - Depois soma o gatilho (R_i). Ordem importa: inverte-la faz o
          dt grande (servidor de pé há horas) "evaporar" a injeção.

        Args:
            amount: Quantidade de estresse a adicionar (R_i gatilho).
            trigger: Identificador do gatilho de memória.
        """
        self._cool_down()
        self.current_stress = min(self.current_stress + amount, self.stress_cap)
        if trigger:
            self.memory_triggers.append({
                "trigger": trigger,
                "timestamp": time.time(),
                "stress_added": amount
            })

    def _cool_down(self, max_dt: float = 3.0):
        """Aplicar decaimento exponencial baseado no tempo decorrido.

        O dt é limitado a `max_dt` segundos para que leituras frequentes
        (ex: WebSocket a 2 Hz) decomponham o estresse suavemente em tempo
        real, em vez de "colapsar" tudo de uma vez após um período parado.

        Args:
            max_dt: Tempo máximo de decaimento por chamada (default 3s).
        """
        now = time.time()
        dt = min(now - self.last_update, max_dt)
        self.last_update = now

        # Equação: S_t = S_0 * e^(-λ*t) + Σ(R_i)
        # Decaimento exponencial do estresse atual
        self.current_stress = max(
            0.0,
            self.current_stress * np.exp(-self.decay_rate * dt)
        )

        # Limpar gatilhos antigos ou com baixo impacto
        self.memory_triggers = self.memory_triggers[-20:]

    def add_memory_trigger(self, trigger_id: str, stress: float = None):
        """Adicionar gatilho de memória (ruminação).
        
        Args:
            trigger_id: ID do gatilho/memória.
            stress: Estresse associado. Se None, usa valor padrão.
        """
        if stress is None:
            stress = 5.0  # valor padrão de ruminação
        self.add_stress(stress, trigger_id)

    def get_stress_level(self) -> float:
        """Retornar nível atual de estresse (S_t), aplicando decaimento contínuo."""
        self._cool_down()
        return float(self.current_stress)

    def get_state(self) -> dict:
        """Retornar estado completo do fígado virtual."""
        return {
            "stress_level": self.get_stress_level(),
            "decay_rate": self.decay_rate,
            "stress_cap": self.stress_cap,
            "memory_triggers_count": len(self.memory_triggers),
            "last_update": self.last_update
        }

    def reset(self):
        """Resetar o fígado virtual."""
        self.current_stress = 0.0
        self.memory_triggers = []
        self.last_update = time.time()