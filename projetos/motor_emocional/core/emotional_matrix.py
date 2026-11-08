"""Matriz RGB Emocional - Classifica interações em três eixos:
- Valência: Positiva (recompensa) ou Negativa (dor/alerta)
- Energia: Alta (fúria, euforia) ou Baixa (tristeza, letargia)
- Previsibilidade: Alta (rotina) ou Baixa (paranóia, surpresa)
"""
import numpy as np


class EmotionalMatrix:
    """Três eixos emocionais discretizados."""

    def __init__(self):
        # Eixos: [valência, energia, previsibilidade]
        # Valência: -1 (negativa) a +1 (positiva)
        # Energia: 0 (baixa) a 1 (alta)
        # Previsibilidade: 0 (baixa/paranóia) a 1 (alta/rotina)
        self.axis_names = ["valencia", "energia", "previsibilidade"]
        self.reset()

    def reset(self):
        self.state = np.zeros(3, dtype=np.float32)

    def classify(self, valencia: float, energia: float, previsibilidade: float):
        """Classificar interação nos três eixos.
        
        Args:
            valencia: -1 (negativo) a +1 (positivo)
            energia: 0 (baixa) a 1 (alta)
            previsibilidade: 0 (baixa) a 1 (alta)
        """
        self.state = np.array([valencia, energia, previsibilidade], dtype=np.float32)
        return self.state.copy()

    def get_state(self):
        return self.state.copy()

    def describe(self):
        """Retornar descrição textual do estado emocional."""
        v, e, p = self.state
        val = "positiva" if v > 0 else "negativa"
        ener = "alta" if e > 0.5 else "baixa"
        prec = "alta" if p > 0.5 else "baixa"
        return f"Emocional[{val}, {ener}, {prec}]"