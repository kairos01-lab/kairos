"""Web Dashboard Server - Motor Emocional.

Servidor FastAPI com WebSocket para dashboard em tempo real.
"""
import asyncio
import json
import math
import time
from pathlib import Path
from typing import Dict, Any, Optional, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .motor_sistema import (
    get_motor_emocional,
    MotorEmocional,
    MotorShuttingDown,
)

# Limites técnicos de transporte, não de autorização. Ver docs/os108.
MAX_HTTP_BODY_BYTES = 128 * 1024
MAX_JSON_DEPTH = 8
MAX_JSON_OBJECT_KEYS = 64
MAX_JSON_LIST_ITEMS = 100
MAX_JSON_STRING_CHARS = 32_768
MAX_WS_MESSAGE_CHARS = 4_096
MAX_WS_MESSAGE_BYTES = 8_192
MAX_WS_CONNECTIONS = 32
WS_SEND_TIMEOUT_SECONDS = 2.0


class ConnectionManager:
    """Gerencia conexões WebSocket ativas."""

    def __init__(
        self,
        max_connections: int = MAX_WS_CONNECTIONS,
        send_timeout: float = WS_SEND_TIMEOUT_SECONDS,
    ):
        self.active_connections: Set[WebSocket] = set()
        self.max_connections = max_connections
        self.send_timeout = send_timeout

    async def connect(self, websocket: WebSocket) -> bool:
        await websocket.accept()
        # Recheca após o await: duas conexões podem ter passado pelo limite
        # antes de ambas serem adicionadas.
        if len(self.active_connections) >= self.max_connections:
            await websocket.close(code=1013)
            return False
        self.active_connections.add(websocket)
        return True

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def close_all(self):
        """Encerrar conexões ativas no shutdown do servidor."""
        connections = list(self.active_connections)
        for websocket in connections:
            try:
                await asyncio.wait_for(
                    websocket.close(code=1001),
                    timeout=self.send_timeout,
                )
            except Exception:
                pass
        self.active_connections.clear()

    async def broadcast(self, message: Dict[str, Any]):
        """Enviar mensagem para todas as conexões ativas.

        Usa snapshot para não sofrer mutação do set durante o await e limita
        cada envio; um cliente lento não bloqueia os demais.
        """
        if not self.active_connections:
            return
        dead = set()
        for ws in list(self.active_connections):
            try:
                await asyncio.wait_for(
                    ws.send_json(message),
                    timeout=self.send_timeout,
                )
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
motor: Optional[MotorEmocional] = None
broadcast_task: Optional[asyncio.Task] = None


async def broadcast_loop():
    """Loop que envia estado do motor para clientes conectados."""
    global motor
    while True:
        await asyncio.sleep(0.5)  # 2 Hz
        if motor is None or not manager.active_connections:
            continue
        try:
            status = _serialize_status(_status_data(motor))
            payload = {
                "type": "status",
                "timestamp": time.time(),
                "data": status,
            }
            await manager.broadcast(payload)
        except Exception as error:
            print(f"[WS] broadcast error: {type(error).__name__}: {error}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broadcast_task
    broadcast_task = asyncio.create_task(broadcast_loop())
    yield
    if broadcast_task:
        broadcast_task.cancel()
        try:
            await broadcast_task
        except asyncio.CancelledError:
            pass
    if motor is not None and hasattr(motor, "begin_shutdown"):
        motor.begin_shutdown()
    await manager.close_all()
    if motor is not None and hasattr(motor, "shutdown_async"):
        try:
            shutdown = await motor.shutdown_async()
            if not shutdown.get("shutdown_complete", False):
                print(f"[Motor] shutdown incompleto: {shutdown}")
        except Exception as error:
            print(f"[Motor] shutdown error: {type(error).__name__}: {error}")


def _serialize_status(status: Dict[str, Any]) -> Dict[str, Any]:
    """Converter numpy arrays para listas para serialização JSON."""
    import numpy as np
    out = {}
    for k, v in status.items():
        if isinstance(v, np.ndarray):
            out[k] = v.tolist()
        elif isinstance(v, dict):
            out[k] = _serialize_status(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [_serialize_status(i) if isinstance(i, dict) else (i.tolist() if isinstance(i, np.ndarray) else i) for i in v]
        else:
            out[k] = v
    return out


app = FastAPI(
    title="Motor Emocional - Web Dashboard",
    description="Dashboard em tempo real do estado emocional do sistema",
    version="1.0.0",
    lifespan=lifespan,
)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _json_shape_error(value, depth: int = 0):
    """Validar profundidade/tamanho de JSON já decodificado."""
    if depth > MAX_JSON_DEPTH:
        return f"JSON excede profundidade {MAX_JSON_DEPTH}"
    if isinstance(value, str):
        if len(value) > MAX_JSON_STRING_CHARS:
            return f"string JSON excede {MAX_JSON_STRING_CHARS} caracteres"
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return "JSON contém número não finito"
        return None
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return None
    if isinstance(value, dict):
        if len(value) > MAX_JSON_OBJECT_KEYS:
            return f"objeto JSON excede {MAX_JSON_OBJECT_KEYS} propriedades"
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                return "JSON contém chave inválida"
            error = _json_shape_error(item, depth + 1)
            if error:
                return error
        return None
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_JSON_LIST_ITEMS:
            return f"lista JSON excede {MAX_JSON_LIST_ITEMS} itens"
        for item in value:
            error = _json_shape_error(item, depth + 1)
            if error:
                return error
        return None
    return f"JSON contém tipo não suportado: {type(value).__name__}"


async def _json_object(request: Request):
    """Ler corpo JSON limitado; devolver (body, resposta_de_erro|None)."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except (TypeError, ValueError):
            return None, JSONResponse(
                {"error": "Content-Length inválido"}, status_code=400
            )
        if length < 0:
            return None, JSONResponse(
                {"error": "Content-Length inválido"}, status_code=400
            )
        if length > MAX_HTTP_BODY_BYTES:
            return None, JSONResponse(
                {"error": f"corpo excede {MAX_HTTP_BODY_BYTES} bytes"},
                status_code=413,
            )

    body = bytearray()
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_HTTP_BODY_BYTES:
                return None, JSONResponse(
                    {"error": f"corpo excede {MAX_HTTP_BODY_BYTES} bytes"},
                    status_code=413,
                )
    except Exception:
        return None, JSONResponse(
            {"error": "falha ao ler corpo"}, status_code=400
        )

    try:
        payload = json.loads(bytes(body))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, ValueError):
        return None, JSONResponse({"error": "JSON inválido"}, status_code=400)

    if not isinstance(payload, dict):
        return None, JSONResponse(
            {"error": "corpo deve ser objeto JSON"}, status_code=400
        )
    try:
        shape_error = _json_shape_error(payload)
    except RecursionError:
        shape_error = "JSON profundo demais"
    if shape_error:
        return None, JSONResponse({"error": shape_error}, status_code=400)
    return payload, None


def _status_data(motor_instance) -> Dict[str, Any]:
    """Snapshot não bloqueante; fallback apenas para doubles de teste."""
    snapshot = getattr(motor_instance, "get_status_snapshot", None)
    if snapshot is not None:
        return snapshot()
    return motor_instance.get_current_status()


async def _run_motor_async(motor_instance, async_name: str, sync_name: str, **kwargs):
    """Executar via fila dedicada; fallback síncrono só para doubles."""
    async_method = getattr(motor_instance, async_name, None)
    if async_method is not None:
        return await async_method(**kwargs)
    return getattr(motor_instance, sync_name)(**kwargs)


async def _ws_send(websocket, payload):
    """Enviar JSON com timeout; falha não bloqueia o loop indefinidamente."""
    await asyncio.wait_for(
        websocket.send_json(payload),
        timeout=WS_SEND_TIMEOUT_SECONDS,
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Página principal do dashboard."""
    return templates.TemplateResponse(request, "dashboard.html", {})


@app.get("/api/status")
async def api_status():
    """Estado completo na fila serial do motor (consistente, pode esperar)."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    try:
        status = await _run_motor_async(
            motor,
            "get_current_status_async",
            "get_current_status",
        )
        return _serialize_status(status)
    except MotorShuttingDown:
        return JSONResponse({"error": "Motor em encerramento"}, status_code=503)
    except Exception as error:
        print(f"[API] status error: {type(error).__name__}: {error}")
        return JSONResponse({"error": "Falha ao obter status"}, status_code=503)


@app.get("/api/health")
async def api_health():
    """Liveness independente; não espera o lock nem a fila do motor."""
    global motor
    return {
        "status": "ok",
        "motor_initialized": motor is not None,
        "motor_shutting_down": bool(
            getattr(motor, "is_shutting_down", False)
        ),
    }


@app.post("/api/interact")
async def api_interact(request: Request):
    """Processar interação via API."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    body, error_response = await _json_object(request)
    if error_response is not None:
        return error_response
    try:
        result = await _run_motor_async(
            motor,
            "process_interaction_async",
            "process_interaction",
            user_id=body.get("user_id", "web_user"),
            threat_type=body.get("threat_type", "web_interaction"),
            user_input=body.get("user_input"),
            system_prompt=body.get("system_prompt", ""),
            action=body.get("action", "read"),
            target=body.get("target"),
            intent=body.get("intent"),
            from_majority_vote=body.get("from_majority_vote", False),
            subject_id=body.get("subject_id"),
            request_id=body.get("request_id"),
        )
    except MotorShuttingDown:
        return JSONResponse({"error": "Motor em encerramento"}, status_code=503)
    except Exception as error:
        print(f"[API] interact error: {type(error).__name__}: {error}")
        return JSONResponse({"error": "Falha interna do motor"}, status_code=503)
    if result.get("blocked_by") in ("guard_invalid_input", "invalid_input"):
        return JSONResponse(result, status_code=400)
    if result.get("authorization_status") == "INPUT_INVALID":
        return JSONResponse(result, status_code=400)
    return result


@app.post("/api/stress")
async def api_stress(request: Request):
    """Injetar estresse manualmente (para demos/testes)."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    body, error_response = await _json_object(request)
    if error_response is not None:
        return error_response
    amount = body.get("amount", 50)
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(float(amount))
        or not 0.0 <= float(amount) <= 100.0
    ):
        return JSONResponse(
            {"error": "amount deve ser número finito entre 0 e 100"},
            status_code=400,
        )
    try:
        add_stress_async = getattr(motor, "add_stress_async", None)
        if add_stress_async is not None:
            await add_stress_async(float(amount))
        else:
            add_stress = getattr(motor, "add_stress", None)
            if add_stress is not None:
                add_stress(float(amount))
            else:
                motor.virtual_liver.add_stress(float(amount))
    except MotorShuttingDown:
        return JSONResponse({"error": "Motor em encerramento"}, status_code=503)
    except Exception as error:
        print(f"[API] stress error: {type(error).__name__}: {error}")
        return JSONResponse({"error": "Falha ao injetar estresse"}, status_code=503)
    status = _serialize_status(_status_data(motor))
    return {"injected": float(amount), "status": status}


@app.post("/api/break_glass")
async def api_break_glass(request: Request):
    """Acionar Break Glass via API."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    body, error_response = await _json_object(request)
    if error_response is not None:
        return error_response
    try:
        result = await _run_motor_async(
            motor,
            "trigger_break_glass_async",
            "trigger_break_glass",
            user_id=body.get("user_id", "web_user"),
            subject_id=body.get("subject_id"),
            gps_coords=body.get("gps_coords"),
            justificativa=body.get(
                "justificativa", "Acionado via Web Dashboard"
            ),
            event_id=body.get("event_id"),
            request_id=body.get("request_id"),
            emitter_id=body.get("emitter_id"),
            timestamp_unix=body.get("timestamp_unix"),
            nonce=body.get("nonce"),
            key_id=body.get("key_id"),
            camera_file=body.get("camera_file"),
            camera_media_type=body.get("camera_media_type"),
            camera_sha256=body.get("camera_sha256"),
            audio_file=body.get("audio_file"),
            audio_media_type=body.get("audio_media_type"),
            audio_sha256=body.get("audio_sha256"),
            signature_hmac_sha256=body.get("signature_hmac_sha256"),
        )
    except MotorShuttingDown:
        return JSONResponse({"error": "Motor em encerramento"}, status_code=503)
    except Exception as error:
        print(f"[API] break_glass error: {type(error).__name__}: {error}")
        return JSONResponse(
            {"error": "Falha interna do motor"}, status_code=503
        )
    if result.get("break_glass_status") == "BREAK_GLASS_INVALID_INPUT":
        return JSONResponse(result, status_code=400)
    if result.get("authorized") is not True:
        # Denúncia explícita no nível HTTP; o corpo mantém o estado detalhado.
        return JSONResponse(result, status_code=403)
    return result


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket de status/heartbeat com limites locais.

    Protocolo existente: envia status inicial, responde texto com `pong` e
    envia `ping` após 30s sem mensagem. Não há comandos JSON; não foram
    inventados. Texto vazio, binário e mensagens acima do limite são
    rejeitados explicitamente.
    """
    connected = await manager.connect(websocket)
    if not connected:
        return
    try:
        # Enviar estado inicial
        global motor
        if motor:
            status = _serialize_status(_status_data(motor))
            await _ws_send(websocket, {
                "type": "status",
                "timestamp": time.time(),
                "data": status,
            })
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), timeout=30.0
                )
            except asyncio.TimeoutError:
                await _ws_send(websocket, {
                    "type": "ping",
                    "timestamp": time.time(),
                })
                continue

            if message.get("type") == "websocket.disconnect":
                break

            text = message.get("text")
            binary = message.get("bytes")
            if text is None and binary is not None:
                await _ws_send(websocket, {
                    "type": "error",
                    "error": "mensagem binária não suportada",
                })
                await websocket.close(code=1003)
                break
            if text is None:
                await _ws_send(websocket, {
                    "type": "error",
                    "error": "mensagem inválida",
                })
                continue
            if not text.strip():
                await _ws_send(websocket, {
                    "type": "error",
                    "error": "mensagem vazia",
                })
                continue
            if (
                len(text) > MAX_WS_MESSAGE_CHARS
                or len(text.encode("utf-8")) > MAX_WS_MESSAGE_BYTES
            ):
                await _ws_send(websocket, {
                    "type": "error",
                    "error": "mensagem acima do limite",
                    "max_chars": MAX_WS_MESSAGE_CHARS,
                    "max_bytes": MAX_WS_MESSAGE_BYTES,
                })
                await websocket.close(code=1009)
                break
            await _ws_send(websocket, {"type": "pong", "echo": text})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Erro: {type(e).__name__}: {e}")
    finally:
        manager.disconnect(websocket)


def init_web_dashboard(motor_instance: MotorEmocional, host: str = "127.0.0.1", port: int = 8080):
    """Inicializar e rodar o servidor web."""
    global motor
    motor = motor_instance
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    # Para teste standalone
    from .motor_sistema import init_motor_emocional
    m = init_motor_emocional(cortex_use_local=False)
    init_web_dashboard(m)