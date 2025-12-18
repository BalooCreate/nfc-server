import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, Optional
import os
import json
import asyncio

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings


# =========================
# SETTINGS
# =========================

class Settings(BaseSettings):
    api_key: str = ""
    server_name: str = "NFC Remote Server"
    version: str = "1.0.0"
    default_port: int = 8000
    log_file: str = "nfc_server.log"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()


# =========================
# LOGGING
# =========================

logger = logging.getLogger("nfc_server")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = RotatingFileHandler(
        settings.log_file, maxBytes=1_000_000, backupCount=3
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())


# =========================
# MODELS
# =========================

class ApduRequest(BaseModel):
    session_id: str
    command_apdu: str


class ApduResponse(BaseModel):
    response_apdu: str
    paired: bool


# =========================
# STORAGE
# =========================

session_roles: Dict[str, Dict[str, str]] = {}
last_apdu: Dict[str, str] = {}
# Cozi pentru mesaje CĂTRE clienți (reader sau tag)
active_outboxes: Dict[str, Dict[str, asyncio.Queue]] = {}
# Cozi temporare pentru așteptarea răspunsului în /apdu
temp_response_queues: Dict[str, asyncio.Queue] = {}


# =========================
# AUTH
# =========================

def check_auth(auth: Optional[str]):
    if not settings.api_key:
        return
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    if auth.split(" ", 1)[1] != settings.api_key:
        raise HTTPException(403, "Forbidden")


# =========================
# ROLE LOGIC
# =========================

def register_role(session_id: str, role: str, client_id: str):
    if session_id not in session_roles:
        session_roles[session_id] = {}

    role = role.lower()
    if role in ("reader", "reader_mode"):
        session_roles[session_id]["reader"] = client_id
    elif role in ("tag", "card", "emulation"):
        session_roles[session_id]["tag"] = client_id


def is_paired(session_id: str) -> bool:
    roles = session_roles.get(session_id, {})
    return "reader" in roles and "tag" in roles


# =========================
# APP
# =========================

app = FastAPI(title=settings.server_name, version=settings.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def err(_, e: Exception):
    logger.exception(e)
    return JSONResponse({"error": "internal"}, status_code=500)


# =========================
# ENDPOINTS
# =========================

@app.get("/status")
async def status():
    return {"status": "online"}


@app.get("/ping")
async def ping():
    return {"status": "ok"}


@app.post("/tag/event")
async def tag_event(
    event: dict,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    check_auth(authorization)

    client_id = f"{request.client.host}:{request.client.port}"
    session_id = event.get("session_id", "").strip()
    raw_type = str(event.get("type", "")).upper()

    role = None
    if "READER" in raw_type:
        role = "reader"
    elif "TAG" in raw_type or "CARD" in raw_type or "EMULATION" in raw_type:
        role = "tag"

    if role and session_id:
        register_role(session_id, role, client_id)
        logger.info(f"[ROLE SET] session={session_id} role={role} client={client_id}")
    else:
        logger.warning(f"[UNMAPPED EVENT] session={session_id} type={raw_type}")

    paired = is_paired(session_id)
    return {"status": "ok", "role": role, "paired": paired}


@app.post("/apdu", response_model=ApduResponse)
async def apdu(
    req: ApduRequest,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    check_auth(authorization)

    session_id = req.session_id
    command_apdu = req.command_apdu.strip()

    if not command_apdu:
        raise HTTPException(400, "Comandă APDU goală")

    # Verifică dacă există un TAG conectat prin WebSocket
    tag_outbox = active_outboxes.get(session_id, {}).get("tag")
    if not tag_outbox:
        logger.warning(f"[APDU] Niciun tag conectat pentru sesiunea {session_id}")
        return ApduResponse(response_apdu="6A82", paired=False)

    # Trimite comanda către tag
    await tag_outbox.put({
        "type": "apdu_request",
        "command_apdu": command_apdu
    })

    # Așteaptă răspunsul
    response_queue = asyncio.Queue()
    temp_response_queues[session_id] = response_queue

    try:
        response_apdu = await asyncio.wait_for(response_queue.get(), timeout=8.0)
    except asyncio.TimeoutError:
        logger.error(f"[APDU] Timeout pentru sesiunea {session_id}")
        response_apdu = "6F00"
    finally:
        temp_response_queues.pop(session_id, None)

    return ApduResponse(response_apdu=response_apdu, paired=is_paired(session_id))


@app.get("/session/roles")
async def roles(session_id: str):
    return session_roles.get(session_id, {})


# =========================
# WEBSOCKET ENDPOINT
# =========================

@app.websocket("/ws")
async def nfc_websocket(websocket: WebSocket):
    await websocket.accept()

    session_id = websocket.query_params.get("session_id")
    role_param = websocket.query_params.get("role", "").lower()
    token = websocket.query_params.get("token")

    if not session_id or not role_param:
        await websocket.close(code=4000, reason="session_id și role obligatorii")
        return

    if settings.api_key and token != settings.api_key:
        await websocket.close(code=4003, reason="Token invalid")
        return

    if role_param in ("reader", "reader_mode"):
        role = "reader"
    elif role_param in ("tag", "card", "emulation"):
        role = "tag"
    else:
        await websocket.close(code=4001, reason="Rol necunoscut")
        return

    outbox = asyncio.Queue()
    active_outboxes.setdefault(session_id, {})[role] = outbox

    client_id = f"ws:{session_id}:{role}"
    register_role(session_id, role, client_id)

    logger.info(f"[WS CONNECT] session={session_id} role={role}")
    await websocket.send_json({"status": "connected", "role": role})

    async def sender():
        try:
            while True:
                msg = await outbox.get()
                await websocket.send_json(msg)
        except Exception:
            pass  # WebSocket închis

    sender_task = asyncio.create_task(sender())

    try:
        async for message in websocket.iter_text():
            try:
                data = json.loads(message)
                msg_type = data.get("type")

                if role == "tag" and msg_type == "apdu_response":
                    response_apdu = data.get("response_apdu", "6F00")

                    # Deblocare apel /apdu
                    resp_q = temp_response_queues.get(session_id)
                    if resp_q:
                        try:
                            resp_q.put_nowait(response_apdu)
                        except:
                            pass  # coada închisă

                    # Notificare live reader (opțional)
                    reader_outbox = active_outboxes.get(session_id, {}).get("reader")
                    if reader_outbox:
                        await reader_outbox.put({
                            "type": "apdu_response",
                            "response_apdu": response_apdu
                        })

                elif role == "reader" and msg_type == "apdu_request":
                    command_apdu = data.get("command_apdu")
                    if command_apdu:
                        tag_outbox = active_outboxes.get(session_id, {}).get("tag")
                        if tag_outbox:
                            await tag_outbox.put({
                                "type": "apdu_request",
                                "command_apdu": command_apdu
                            })
                        else:
                            await outbox.put({
                                "type": "apdu_response",
                                "response_apdu": "6A82"
                            })

            except Exception as e:
                logger.error(f"[WS] Eroare procesare mesaj: {e}")
                continue

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[WS ERROR] {e}")
    finally:
        sender_task.cancel()
        active_outboxes.get(session_id, {}).pop(role, None)
        if session_id in active_outboxes and not active_outboxes[session_id]:
            del active_outboxes[session_id]
        logger.info(f"[WS DISCONNECT] session={session_id} role={role}")


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", settings.default_port))
    uvicorn.run("main:app", host="0.0.0.0", port=port)