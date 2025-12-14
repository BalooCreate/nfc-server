import logging
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Dict, Set
import os

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, field_validator, ConfigDict
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

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


# =========================
# LOGGING
# =========================

logger = logging.getLogger("nfc_server")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = RotatingFileHandler("nfc_server.log", maxBytes=1_000_000, backupCount=3)
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


class TagEvent(BaseModel):
    session_id: str
    type: str  # reader / tag


# =========================
# STORAGE
# =========================

session_roles: Dict[str, Dict[str, str]] = {}
last_apdu: Dict[str, str] = {}


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
    return JSONResponse(500, {"error": "internal"})


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
    event: TagEvent,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    check_auth(authorization)

    client_id = f"{request.client.host}:{request.client.port}"
    register_role(event.session_id, event.type, client_id)

    paired = is_paired(event.session_id)

    logger.info(
        f"[ROLE] session={event.session_id} roles={session_roles.get(event.session_id)}"
    )

    return {"paired": paired}


@app.post("/apdu", response_model=ApduResponse)
async def apdu(
    req: ApduRequest,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    check_auth(authorization)

    last_apdu[req.session_id] = req.command_apdu
    paired = is_paired(req.session_id)

    logger.info(
        f"[APDU] session={req.session_id} paired={paired}"
    )

    return ApduResponse(response_apdu="9000", paired=paired)


@app.get("/session/roles")
async def roles(session_id: str):
    return session_roles.get(session_id, {})


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", settings.default_port))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
