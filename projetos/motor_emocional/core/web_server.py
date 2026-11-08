"""Web Dashboard Server - Motor Emocional.

Servidor FastAPI com WebSocket para dashboard em tempo real.
"""
import asyncio
import json
import time
from typing import Dict, Any, Optional, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .motor_sistema import get_motor_emocional, MotorEmocional


class ConnectionManager:
    """Gerencia conexões WebSocket ativas."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Enviar mensagem para todas as conexões ativas."""
        if not self.active_connections:
            return
        dead = set()
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
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
            status = _serialize_status(motor.get_current_status())
            payload = {
                "type": "status",
                "timestamp": time.time(),
                "data": status,
            }
            await manager.broadcast(payload)
        except Exception:
            pass


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

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Página principal do dashboard."""
    return templates.TemplateResponse(request, "dashboard.html", {})


@app.get("/api/status")
async def api_status():
    """Estado atual do motor (REST)."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    return _serialize_status(motor.get_current_status())


@app.post("/api/interact")
async def api_interact(request: Request):
    """Processar interação via API."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    body = await request.json()
    result = motor.process_interaction(
        user_id=body.get("user_id", "web_user"),
        threat_type=body.get("threat_type", "web_interaction"),
        user_input=body.get("user_input"),
        system_prompt=body.get("system_prompt", ""),
        action=body.get("action", "read"),
    )
    return result


@app.post("/api/stress")
async def api_stress(request: Request):
    """Injetar estresse manualmente (para demos/testes)."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    body = await request.json()
    amount = float(body.get("amount", 50))
    motor.virtual_liver.add_stress(amount)
    status = _serialize_status(motor.get_current_status())
    return {"injected": amount, "status": status}


@app.post("/api/break_glass")
async def api_break_glass(request: Request):
    """Acionar Break Glass via API."""
    global motor
    if motor is None:
        return JSONResponse({"error": "Motor não inicializado"}, status_code=503)
    body = await request.json()
    result = motor.trigger_break_glass(
        user_id=body.get("user_id", "web_user"),
        camera_hash=body.get("camera_hash"),
        audio_hash=body.get("audio_hash"),
        gps_coords=body.get("gps_coords"),
        justificativa=body.get("justificativa", "Acionado via Web Dashboard"),
    )
    return result


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket para updates em tempo real."""
    await manager.connect(websocket)
    try:
        # Enviar estado inicial
        global motor
        if motor:
            status = _serialize_status(motor.get_current_status())
            await websocket.send_json({
                "type": "status",
                "timestamp": time.time(),
                "data": status,
            })
        # Manter conexão aberta - aceitar mensagens do cliente (heartbeat, comandos)
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Echo para manter vivo
                await websocket.send_json({"type": "pong", "echo": msg})
            except asyncio.TimeoutError:
                # Enviar ping para manter vivo
                await websocket.send_json({"type": "ping", "timestamp": time.time()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[WS] Erro: {type(e).__name__}: {e}")
        manager.disconnect(websocket)


def init_web_dashboard(motor_instance: MotorEmocional, host: str = "0.0.0.0", port: int = 8080):
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