"""Ponte Python <-> Rust para o Guarda-Costas (Arquitetura de Segurança).

O binário Rust compilado em `guarda_costas/target/release/guarda_costas` é
chamado via subprocess, recebendo/devolvendo JSON. Isso garante que a camada
de segurança (Hard Block, Kernel Constitucional, Break Glass) rode isolada
do processo Python - incorruptível por picos emocionais do Córtex (LLM) ou
bugs no lado Python, com segurança de memória a nível de compilação.
"""
import json
import os
import subprocess

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BINARY_RELEASE = os.path.join(_BASE_DIR, "guarda_costas", "target", "release", "guarda_costas")
_BINARY_DEBUG = os.path.join(_BASE_DIR, "guarda_costas", "target", "debug", "guarda_costas")


def _binary_path() -> str:
    if os.path.exists(_BINARY_RELEASE):
        return _BINARY_RELEASE
    if os.path.exists(_BINARY_DEBUG):
        return _BINARY_DEBUG
    raise FileNotFoundError(
        "Binário guarda_costas não encontrado. Compile com: "
        "cd guarda_costas && cargo build --release"
    )


def _call_rust(op: str, data: dict) -> dict:
    """Chama o binário Rust com uma operação e payload, retorna o JSON de resposta."""
    envelope = json.dumps({"op": op, "data": data}, ensure_ascii=False)
    try:
        result = subprocess.run(
            [_binary_path()],
            input=envelope,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {"error": f"Rust process failed: {result.stderr.strip()}"}
        return json.loads(result.stdout.strip())
    except FileNotFoundError as e:
        return {"error": str(e)}
    except subprocess.TimeoutExpired:
        return {"error": "Guarda-Costas (Rust) timeout - possível deadlock ou binário travado."}
    except json.JSONDecodeError as e:
        return {"error": f"Resposta inválida do Rust: {e}"}


def hard_block(action: str, stress_level: float, is_reincident: bool, user_id: str) -> dict:
    """Avalia se uma ação CRUD deve ser bloqueada com base no nível de estresse.

    Args:
        action: "create", "read", "update" ou "delete".
        stress_level: nível de estresse atual (0-100).
        is_reincident: se o usuário é reincidente (limiar cai para 70%).
        user_id: identificador do usuário.

    Returns:
        dict com {"allowed": bool, "blocked_by": str|None, "reasoning": str, ...}
    """
    return _call_rust("hard_block", {
        "action": action,
        "stress_level": stress_level,
        "is_reincident": is_reincident,
        "user_id": user_id,
    })


def kernel_check(action: str, target: str, intent: str, from_majority_vote: bool = False) -> dict:
    """Avalia um comando do Ring 3 contra as proteções imutáveis do Ring 0.

    Args:
        action: "create", "read", "update" ou "delete".
        target: alvo da ação.
        intent: intenção declarada da ação.
        from_majority_vote: se veio de decisão majoritária.

    Returns:
        dict com {"allowed": bool, "kernel_panic": bool, "ring": int, "reasoning": str}
    """
    return _call_rust("kernel", {
        "action": action,
        "target": target,
        "intent": intent,
        "from_majority_vote": from_majority_vote,
    })


def break_glass(camera_hash: str = None, audio_hash: str = None,
                 gps_coords: str = None, justificativa: str = "") -> dict:
    """Ativa o Protocolo Break Glass (botão de pânico) em caso de emergência real.

    Exige os 3 fatores de handshake (câmera, áudio, GPS) para gerar o
    álibi judicial - sem isso, a quebra de vidro é recusada.

    Returns:
        dict com {"autorizado": bool, "selo_criptografico": str, ...}
    """
    return _call_rust("break_glass", {
        "camera_hash": camera_hash,
        "audio_hash": audio_hash,
        "gps_coords": gps_coords,
        "justificativa": justificativa,
    })


def classify_crud(action: str) -> dict:
    """Classifica uma ação CRUD quanto à elegibilidade para bloqueio (Paradoxo do Jornalista)."""
    return _call_rust("crud", {"action": action})
