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

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()

API_KEY = settings.api_key
SERVER_NAME = settings.server_name
VERSION = settings.version
LOG_FILE = settings.log_file
LOG_LEVEL = settings.log_level.upper()

MAX_LOG_SIZE = 1 * 1024 * 1024
BACKUP_COUNT = 5


# =========================
# LOGGING
# =========================

logger = logging.getLogger("nfc_server")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

if not logger.handlers:
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding="utf-8"
    )

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(logging.StreamHandler())


# =========================
# MODELS
# =========================

class ApduRequest(BaseModel):
    session_id: str
    command_apdu: str


class ApduResponse(BaseModel):
    response_apdu: str
    status: str = "ok"
    paired: bool = False


class NdefRecord(BaseModel):
    record_type: str
    lang: Optional[str] = None
    text: Optional[str] = None
    uri: Optional[HttpUrl] = None

    @field_validator("uri", mode="before")
    @classmethod
    def strip_uri(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class TagEvent(BaseModel):
    session_id: str
    type: str
    tag_id: Optional[str] = None
    tech: Optional[List[str]] = None
    ndef_records: Optional[List[NdefRecord]] = None


class TagConfigResponse(BaseModel):
    mode: str
    tag_id: Optional[str] = None
    ndef_records: Optional[List[NdefRecord]] = None


class SetTagConfigRequest(BaseModel):
    session_id: str
    mode: str
    tag_id: Optional[str] = None
    ndef_records: Optional[List[NdefRecord]] = None


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    clients: int


# =========================
# STORAGE (IN-MEMORY)
# =========================

tag_configs: Dict[str, TagConfigResponse] = {}
last_apdu_per_session: Dict[str, str] = {}

# AUTO-PAIRING
session_clients: Dict[str, Set[str]] = {}
session_status: Dict[str, str] = {}


# =========================
# AUTH
# =========================

def check_auth(authorization: Optional[str]) -> None:
    if not API_KEY:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ", 1)[1].strip()
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API token")


# =========================
# PAIRING LOGIC
# =========================

def update_pairing(session_id: str, client_id: str):
    if session_id not in session_clients:
        session_clients[session_id] = set()

    session_clients[session_id].add(client_id)

    if len(session_clients[session_id]) >= 2:
        session_status[session_id] = "paired"
    else:
        session_status[session_id] = "waiting"


# =========================
# APP
# =========================

app = FastAPI(
    title=SERVER_NAME,
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# ERROR HANDLER
# =========================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Eroare neașteptată la {request.url}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# =========================
# ENDPOINTS
# =========================

@app.get("/status")
async def status():
    return {"status": "online", "server": SERVER_NAME, "version": VERSION}


@app.post("/apdu", response_model=ApduResponse)
async def handle_apdu(
    req: ApduRequest,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    check_auth(authorization)

    session_id = req.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id cannot be empty")

    client_id = f"{request.client.host}:{request.client.port}"
    update_pairing(session_id, client_id)

    cmd = req.command_apdu.upper().replace(" ", "")
    last_apdu_per_session[session_id] = cmd

    paired = session_status.get(session_id) == "paired"

    logger.info(
        f"[APDU] session={session_id} client={client_id} paired={paired}"
    )

    return ApduResponse(response_apdu="9000", paired=paired)


@app.post("/tag/event")
async def tag_event(
    event: TagEvent,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    check_auth(authorization)

    client_id = f"{request.client.host}:{request.client.port}"
    update_pairing(event.session_id, client_id)

    paired = session_status.get(event.session_id) == "paired"

    logger.info(
        f"[TAG EVENT] session={event.session_id} client={client_id} paired={paired}"
    )

    return {"status": "ok", "paired": paired}


@app.get("/session/status", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: str,
    authorization: Optional[str] = Header(None)
):
    check_auth(authorization)

    clients = len(session_clients.get(session_id, set()))
    status = session_status.get(session_id, "waiting")

    return SessionStatusResponse(
        session_id=session_id,
        status=status,
        clients=clients
    )


@app.post("/nfc-bin")
async def handle_nfc_bin(request: Request):
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty body")

    response_data = process_nfc_bin(data)
    return Response(content=response_data, media_type="application/octet-stream")


# =========================
# NFC BINARY PROCESSING
# =========================

def process_nfc_bin(data: bytes) -> bytes:
    command_type = data[0:1]

    if command_type == b"\x01":
        return b"ACK: Comanda 1 procesata"
    elif command_type == b"\x02":
        return b"ACK: Comanda 2 procesata"
    else:
        return b"Error: Comanda necunoscuta"


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", str(settings.default_port)))
    logger.info(f"Pornesc {SERVER_NAME} pe portul {port}")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=1
    )
