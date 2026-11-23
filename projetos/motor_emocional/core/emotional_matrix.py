"""Matriz RGB Emocional - Classifica interações em três eixos:
- Valência: Positiva (recompensa) ou Negativa (dor/alerta)
- Energia: Alta (fúria, euforia) ou Baixa (tristeza, letargia)
- Previsibilidade: Alta (rotina) ou Baixa (paranóia, surpresa)
"""
import math
import numbers

import numpy as np

_AXIS_LIMITS = (
    ("valencia", -1.0, 1.0),
    ("energia", 0.0, 1.0),
    ("previsibilidade", 0.0, 1.0),
)


def _validate_axis(name: str, value, lower: float, upper: float) -> float:
    """Validar um eixo antes de qualquer conversão para float32."""
    if value is None:
        raise ValueError(f"{name} não pode ser None")
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} deve ser numérico")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} deve ser finito")
    if not lower <= number <= upper:
        raise ValueError(
            f"{name} deve estar entre {lower:g} e {upper:g}"
        )
    return number


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

        Raises:
            ValueError: se algum eixo não for numérico, finito ou estiver fora
                da faixa documentada. O estado anterior é preservado.
        """
        # Validar os três eixos antes de atribuir: uma entrada inválida não
        # pode deixar o estado parcialmente atualizado.
        values = (
            _validate_axis("valencia", valencia, -1.0, 1.0),
            _validate_axis("energia", energia, 0.0, 1.0),
            _validate_axis("previsibilidade", previsibilidade, 0.0, 1.0),
        )
        self.state = np.array(values, dtype=np.float32)
        return self.state.copy()

    def get_state(self):
        return self.state.copy()

    def _validated_state(self) -> np.ndarray:
        """Devolver o estado como float64 ou falhar explicitamente."""
        if not isinstance(self.state, np.ndarray):
            raise ValueError(
                "estado emocional inválido: o estado não é um array NumPy"
            )
        if self.state.shape != (3,):
            raise ValueError(
                "estado emocional inválido: o estado deve ter três eixos"
            )
        if not np.issubdtype(self.state.dtype, np.floating):
            raise ValueError(
                "estado emocional inválido: o estado deve ser de ponto flutuante"
            )
        values = self.state.astype(np.float64, copy=False)
        for index, (name, lower, upper) in enumerate(_AXIS_LIMITS):
            value = float(values[index])
            if not math.isfinite(value):
                raise ValueError(
                    f"estado emocional inválido: {name} não é finito"
                )
            if not lower <= value <= upper:
                raise ValueError(
                    f"estado emocional inválido: {name} fora da faixa"
                )
        return values

    def describe(self):
        """Retornar descrição textual do estado emocional.

        Raises:
            ValueError: se o estado interno estiver corrompido ou fora do
                contrato. Não classificar estado inválido como normal.
        """
        v, e, p = self._validated_state()
        val = "positiva" if v > 0 else "negativa"
        ener = "alta" if e > 0.5 else "baixa"
        prec = "alta" if p > 0.5 else "baixa"
        return f"Emocional[{val}, {ener}, {prec}]"