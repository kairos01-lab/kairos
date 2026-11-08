"""Dashboard do Motor Emocional - Visualização em Tempo Real.

Dashboard interativa com gráficos ao vivo do estado emocional,
nível de estresse, níveis de política e histórico do sistema.
"""
from typing import Dict, Any
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
import numpy as np
import time
from threading import Thread, Lock


class EmotionalDashboard:
    """Dashboard visual do motor emocional com animação."""

    def __init__(self, history_size: int = 50):
        """Inicializar dashboard.

        Args:
            history_size: Número de pontos históricos a manter
        """
        self.history_size = history_size
        self.lock = Lock()

        # Histórico circular para animação
        self.time_history = deque(maxlen=history_size)
        self.valencia_history = deque(maxlen=history_size)
        self.energia_history = deque(maxlen=history_size)
        self.previsibilidade_history = deque(maxlen=history_size)
        self.stress_history = deque(maxlen=history_size)
        self.policy_level_history = deque(maxlen=history_size)
        self.timestamps = deque(maxlen=history_size)

        # Tempo inicial
        self.start_time = time.time()

        # Configurar figura
        self.fig, self.axes = plt.subplots(4, 1, figsize=(10, 8), sharex=True)
        self.fig.suptitle('Motor Emocional - Painel de Controle', fontsize=14)

        # Configurar eixos
        self._setup_axes()

        # Linhas de plot
        self.lines = {
            'valencia': self.axes[0].plot([], [], 'g-', label='Valência', linewidth=2)[0],
            'energia': self.axes[0].plot([], [], 'b-', label='Energia', linewidth=2)[0],
            'previsibilidade': self.axes[0].plot([], [], 'r-', label='Previsibilidade', linewidth=2)[0],
        }

        # Eixo de estresse (separado)
        self.stress_line = self.axes[1].plot([], [], 'm-', label='Estresse', linewidth=2)[0]
        self.policy_line = self.axes[1].plot([], [], 'c-', label='Policy Level', linewidth=2)[0]

        # Configurar eixo 1 (estresse)
        self.axes[1].set_ylim(0, 110)
        self.axes[1].set_ylabel('Estresse (%)')
        self.axes[1].legend(loc='upper left')
        self.axes[1].axhline(y=60, color='orange', linestyle='--', alpha=0.5, label='Nível 1')
        self.axes[1].axhline(y=75, color='orange', linestyle='--', alpha=0.5)
        self.axes[1].axhline(y=95, color='red', linestyle='--', alpha=0.5, label='Nível 3')

        # Policy level markers
        self.policy_markers = []

        # Eixo 2 - Policy level
        self.axes[2].set_ylim(0, 4)
        self.axes[2].set_yticks([0, 1, 2, 3])
        self.axes[2].set_ylabel('Nível Policy')
        self.axes[2].set_ylabel('Nível de Política')

        # Histograma/área do policy
        self.policy_fill = self.axes[2].fill_between([], [], [], alpha=0.3)

        # Eixo 3 - Histórico
        self.axes[3].set_ylim(-1.1, 1.1)
        self.axes[3].set_xlabel('Tempo (s)')
        self.axes[3].set_ylabel('Estado')
        self.axes[3].set_title('Estado Emocional Normalizado')

        # Inicializar linhas vazias
        for line in self.lines.values():
            line.set_data([], [])
        self.stress_line.set_data([], [])
        self.policy_line.set_data([], [])

        # Flag de animação
        self._animating = False
        self._ani = None

    def _setup_axes(self):
        """Configurar visualização dos eixos."""
        # Eixo 0 - Matriz Emocional
        self.axes[0].set_ylim(-1.1, 1.1)
        self.axes[0].set_yticks([-1, -0.5, 0, 0.5, 1])
        self.axes[0].set_ylabel('Valência / Energia')
        self.axes[0].legend(loc='upper left', fontsize=8)
        self.axes[0].grid(True, alpha=0.3)
        self.axes[0].set_ylabel('Eixos Emocionais')

        # Formatar eixo X em todos
        for ax in self.axes:
            ax.grid(True, alpha=0.3)

    def update_data(
        self,
        emotional_state: Dict[str, float],
        stress_level: float,
        policy_level: int,
    ):
        """Atualizar dados no dashboard.

        Args:
            emotional_state: Dict com valência, energia, previsibilidade
            stress_level: Nível de estresse (0-100)
            policy_level: Nível da policy (0, 1, 2, 3)
        """
        with self.lock:
            now = time.time() - self.start_time
            self.time_history.append(now)
            self.valencia_history.append(emotional_state.get("valencia", 0))
            self.energia_history.append(emotional_state.get("energia", 0))
            self.previsibilidade_history.append(emotional_state.get("previsibilidade", 0))
            self.stress_history.append(stress_level)
            self.policy_level_history.append(policy_level)
            self.timestamps.append(now)

    def _update_plot(self, frame):
        """Função chamada pela animação para atualizar gráficos."""
        with self.lock:
            if len(self.time_history) < 2:
                return list(self.lines.values()) + [self.stress_line, self.policy_line]

            t = list(self.time_history)
            v = list(self.valencia_history)
            e = list(self.energia_history)
            p = list(self.previsibilidade_history)
            s = list(self.stress_history)
            pol = list(self.policy_level_history)

            # Atualizar matriz emocional (eixo 0)
            self.lines['valencia'].set_data(t, v)
            self.lines['energia'].set_data(t, e)
            self.lines['previsibilidade'].set_data(t, p)

            # Atualizar estresse e policy (eixo 1)
            self.stress_line.set_data(t, s)
            self.policy_line.set_data(t, pol)

            # Ajustar limites de x
            max_t = max(t[-1] + 1, self.history_size / 10)
            for ax in self.axes:
                ax.set_xlim(max(0, t[-1] - self.history_size), t[-1] + 1)

            # Colorir policy level no eixo 2
            self._color_policy_level(pol[-1] if pol else 0)

            # Eixo 2 - policy fill
            pol_t = list(range(len(pol)))
            self.policy_fill.set_xdata(pol_t)
            self.policy_fill.set_ydata(pol)

            # Retornar todas as linhas atualizadas
            return list(self.lines.values()) + [self.stress_line, self.policy_line, self.policy_fill]

    def _color_policy_level(self, level: int):
        """Colorir o indicador do nível de política."""
        colors = ['green', 'yellow', 'orange', 'red']
        # Remover marcadores anteriores
        for m in self.policy_markers:
            m.remove()
        self.policy_markers = []

        if 0 <= level <= 3:
            # Desenhar seta/indicador
            x_range = list(range(len(self.time_history) or [1]))
            marker = self.axes[2].plot(
                x_range[-1:] if x_range else [0],
                [level],
                'D',
                color=colors[level],
                markersize=10,
                markeredgecolor='white',
                linewidth=2,
            )[0]
            self.policy_markers.append(marker)

    def start_animation(self, interval: int = 200):
        """Iniciar animação do dashboard."""
        if self._animating:
            return

        self._animating = True
        self._ani = animation.FuncAnimation(
            self.fig,
            self._update_plot,
            interval=interval,
            blit=True,
            cache_frame_data=False,
        )
        print("▶️ Dashboard animando...")
        plt.tight_layout()
        plt.show()

    def start_animation_thread(self, interval: int = 200):
        """Iniciar animação em thread separada (não-bloqueante)."""
        def run_anim():
            plt.show()

        self._thread = Thread(target=run_anim, daemon=True)
        self._thread.start()
        print("▶️ Dashboard em thread separada.")

    def record_interaction(
        self,
        emotional_state: Dict[str, float],
        stress_level: float,
        policy_level: int,
        policy_action: str = None,
    ):
        """Registrar interação no histórico e atualizar dashboard.

        Args:
            emotional_state: Estado emocional atual
            stress_level: Nível de estresse
            policy_level: Nível da policy
            policy_action: Descrição da ação tomada
        """
        # Print resumido no console
        v = emotional_state.get("valencia", 0)
        e = emotional_state.get("energia", 0)
        p = emotional_state.get("previsibilidade", 0)
        stress_str = f"{stress_level:.1f}%"

        # Determinar rótulo do nível
        level_names = {
            0: "Normal",
            1: "Fadiga",
            2: "Testemunha",
            3: "Break Glass"
        }
        level_name = level_names.get(policy_level, f"Nível {policy_level}")

        # Descritor emocional
        val_label = "Positiva" if v > 0 else "Negativa"
        ener_label = "Alta" if e > 0.5 else "Baixa"

        print(f"[DASH] | Estresse: {stress_str:6s} | Policy: {level_name:12s} | "
              f"Val: {val_label:7s} | Ener: {ener_label:5s} | Ação: {policy_action or '—'}")

    def save_figure(self, filepath: str = None):
        """Salvar figura atual."""
        if filepath is None:
            filepath = f"/tmp/motor_emocional_dashboard_{int(time.time())}.png"
        self.fig.savefig(filepath, dpi=150, bbox_inches='tight')
        print(f"[DASH] Figura salva em: {filepath}")


# Instância global
dashboard = None


def init_dashboard(history_size: int = 50) -> EmotionalDashboard:
    """Factory function para inicializar dashboard global."""
    global dashboard
    dashboard = EmotionalDashboard(history_size=history_size)
    return dashboard


def get_dashboard() -> EmotionalDashboard:
    """Getter para instância global do dashboard."""
    return dashboard