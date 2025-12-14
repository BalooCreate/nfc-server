import logging
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BaseSettings, HttpUrl, validator

# ==============================
#   CONFIG PRODUS (din .env)
# ==============================

class Settings(BaseSettings):
    api_key: str = ""                      # Dacă e gol → auth dezactivat
    server_name: str = "NFC Remote Server"
    version: str = "1.0.0"
    default_port: int = 5000
    log_file: str = "nfc_server.log"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

API_KEY = settings.api_key
SERVER_NAME = settings.server_name
VERSION = settings.version
DEFAULT_PORT = settings.default_port
LOG_FILE = settings.log_file
LOG_LEVEL = settings.log_level.upper()

MAX_LOG_SIZE = 1 * 1024 * 1024   # 1 MB
BACKUP_COUNT = 5


# ==============================
#   LOGGING
# ==============================

logger = logging.getLogger("nfc_server")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
)
formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info(
    f"Pornit cu setările: server_name={SERVER_NAME}, version={VERSION}, "
    f"port={DEFAULT_PORT}, log_level={LOG_LEVEL}"
)


# ==============================
#   MODELE Pydantic
# ==============================

class ApduRequest(BaseModel):
    session_id: str                     # ✅ obligatoriu
    command_apdu: str


class ApduResponse(BaseModel):
    response_apdu: str
    status: str = "ok"


class NdefRecord(BaseModel):
    record_type: str                    # ex: "uri", "text"
    lang: Optional[str] = None
    text: Optional[str] = None
    uri: Optional[HttpUrl] = None       # ✅ validare URI cu Pydantic

    @validator("uri", pre=True)
    def strip_uri(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class TagEvent(BaseModel):
    session_id: str                     # ✅ obligatoriu
    type: str                           # "read" sau "emulate"
    tag_id: Optional[str] = None
    tech: Optional[List[str]] = None
    ndef_records: Optional[List[NdefRecord]] = None


class TagConfigResponse(BaseModel):
    mode: str                           # "emulate" sau "none"
    tag_id: Optional[str] = None
    ndef_records: Optional[List[NdefRecord]] = None


class SetTagConfigRequest(BaseModel):
    session_id: str                     # ✅ obligatoriu
    mode: str
    tag_id: Optional[str] = None
    ndef_records: Optional[List[NdefRecord]] = None


# ==============================
#   STARE IN-MEMORY
# ==============================

tag_configs: Dict[str, TagConfigResponse] = {}
last_apdu_per_session: Dict[str, str] = {}


# ==============================
#   UTILE
# ==============================

def check_auth(authorization: Optional[str]) -> None:
    if not API_KEY:
        return
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("Cerere fără token valid")
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1].strip()
    if token != API_KEY:
        logger.warning("Token invalid")
        raise HTTPException(status_code=403, detail="Invalid API token")


# ==============================
#   APLICAȚIE FASTAPI
# ==============================

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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Eroare neașteptată la {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# --------- ENDPOINTURI DE BAZĂ ---------

@app.get("/status")
async def status():
    return {
        "status": "online",
        "server": SERVER_NAME,
        "version": VERSION,
    }


@app.get("/info")
async def info():
    return {
        "server": SERVER_NAME,
        "version": VERSION,
        "apdu_endpoint": "/apdu",
        "tag_config_endpoint": "/tag/config",
        "tag_event_endpoint": "/tag/event",
        "sessions_endpoint": "/sessions",
    }


# --------- APDU ---------

@app.post("/apdu", response_model=ApduResponse)
async def handle_apdu(
    req: ApduRequest,
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    session_id = req.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id cannot be empty")
    cmd = req.command_apdu.upper().replace(" ", "")
    logger.info(f"[APDU] session={session_id} cmd={cmd}")
    last_apdu_per_session[session_id] = cmd
    return ApduResponse(response_apdu="9000")


# --------- TAG EVENT ---------

@app.post("/tag/event")
async def tag_event(
    event: TagEvent,
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    logger.info(f"[TAG EVENT] session={event.session_id} type={event.type}")
    return {"status": "ok"}


# --------- TAG CONFIG (FĂRĂ DEMO!) ---------

@app.get("/tag/config", response_model=TagConfigResponse)
async def tag_config(
    session_id: str,                      # ✅ obligatoriu
    authorization: Optional[str] = Header(None),
):
    """
    Returnează configurația TAG pentru sesiunea dată.
    Nu există fallback demo – doar configurații setate explicit.
    """
    check_auth(authorization)
    sid = session_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id cannot be empty")

    if sid not in tag_configs:
        raise HTTPException(
            status_code=404,
            detail=f"No tag configuration found for session '{sid}'. "
                   f"Use POST /admin/set_tag to configure it."
        )

    cfg = tag_configs[sid]
    logger.info(f"[TAG CONFIG] session={sid} -> {cfg.json()}")
    return cfg


# --------- ADMIN ---------

@app.get("/sessions")
async def list_sessions(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    return {"sessions": last_apdu_per_session}


@app.post("/admin/set_tag")
async def set_tag_config(
    data: SetTagConfigRequest,
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    sid = data.session_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id cannot be empty")

    cfg = TagConfigResponse(
        mode=data.mode,
        tag_id=data.tag_id,
        ndef_records=data.ndef_records,
    )
    tag_configs[sid] = cfg
    logger.info(f"[ADMIN] Set TAG CONFIG for session={sid}: {cfg.json()}")
    return {"status": "ok", "session_id": sid}


# --------- NFC BINAR ---------

@app.post("/nfc-bin")
async def handle_nfc_bin(request: Request):
    try:
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="Empty body")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad request: {e}")

    response_data = process_nfc_bin(data)
    if isinstance(response_data, str):
        response_data = response_data.encode("utf-8")
    return Response(content=response_data, media_type="application/octet-stream")


def process_nfc_bin(data: bytes) -> bytes:
    if len(data) == 0:
        return b"Error: Empty command"

    command_type = data[0:1]
    # Restul datelor poate fi folosit în viitor

    if command_type == b'\x01':
        logger.info("Comandă de tip 1 primită")
        return b"ACK: Comanda 1 procesata"
    elif command_type == b'\x02':
        logger.info("Comandă de tip 2 primită")
        return b"ACK: Comanda 2 procesata"
    else:
        logger.warning(f"Comandă necunoscută: {command_type.hex()}")
        return b"Error: Comanda necunoscuta"


# ==============================
#   PORNIRE UVICORN
# ==============================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Pornesc {SERVER_NAME} pe portul {DEFAULT_PORT}")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=DEFAULT_PORT,
        reload=False,
        workers=1,
    )
