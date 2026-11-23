"""Fígado Virtual - Gestão de entropia e estresse.

O sistema acumula "estresse" e precisa de tempo para decair e esfriar.
Equação: S_t = S_0 * e^(-λ*t) + Σ(R_i)
- S_0: estresse inicial
- λ: taxa de decaimento (cooling rate)
- t: tempo decorrido
- R_i: gatilhos de memória (ruminação)
"""
import math

import numpy as np
import time


def _finite_non_negative(name: str, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve ser numérico")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} deve ser finito")
    if number < 0.0:
        raise ValueError(f"{name} não pode ser negativo")
    return number


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
        if isinstance(decay_rate, bool) or not isinstance(decay_rate, (int, float)):
            raise ValueError("decay_rate deve ser numérico")
        if not math.isfinite(float(decay_rate)) or not 0.0 < float(decay_rate) <= 1.0:
            raise ValueError("decay_rate deve estar em (0, 1]")
        if isinstance(stress_cap, bool) or not isinstance(stress_cap, (int, float)):
            raise ValueError("stress_cap deve ser numérico")
        if not math.isfinite(float(stress_cap)) or float(stress_cap) <= 0.0:
            raise ValueError("stress_cap deve ser finito e positivo")

        self.decay_rate = float(decay_rate)
        self.stress_cap = float(stress_cap)
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
            amount: Quantidade de estresse a adicionar (R_i gatilho), finita e
                não negativa. Valores negativos/NaN/infinitos são rejeitados;
                não são convertidos em zero nem em permissão.
            trigger: Identificador do gatilho de memória.
        """
        amount = _finite_non_negative("amount", amount)
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

        # Estado inválido não pode virar 0.0 silenciosamente: isso liberaria o
        # Hard Block. Em corrupção externa, adotamos o teto conservador.
        current = self.current_stress
        if (
            isinstance(current, bool)
            or not isinstance(current, (int, float))
            or not math.isfinite(float(current))
            or float(current) < 0.0
            or float(current) > self.stress_cap
        ):
            self.current_stress = self.stress_cap
        else:
            self.current_stress = float(current)

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