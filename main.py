import logging
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Dict

from fastapi import FastAPI, Header, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BaseSettings
from fastapi.responses import Response

# ==============================
#   CONFIG PRODUS (din .env)
# ==============================

class Settings(BaseSettings):
    api_key: str = ""                      # API key pentru clienți (dacă e gol => auth dezactivat)
    server_name: str = "NFC Remote Server"
    version: str = "1.0.0"
    default_port: int = 5000               # poți schimba în 5050 dacă vrei
    log_file: str = "nfc_server.log"
    log_level: str = "INFO"                # DEBUG / INFO / WARNING / ERROR

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
BACKUP_COUNT = 5                 # păstrează 5 fișiere vechi de log


# ==============================
#   LOGGING PROFESIONAL
# ==============================

logger = logging.getLogger("nfc_server")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
)
file_format = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(file_format)
logger.addHandler(console_handler)

logger.info("Pornit cu setările: "
            f"server_name={SERVER_NAME}, version={VERSION}, port={DEFAULT_PORT}, log_level={LOG_LEVEL}")


# ==============================
#   MODELE Pydantic
# ==============================

class ApduRequest(BaseModel):
    session_id: Optional[str] = None
    command_apdu: str


class ApduResponse(BaseModel):
    response_apdu: str
    status: str = "ok"


class NdefRecord(BaseModel):
    record_type: str          # ex: "uri", "text"
    lang: Optional[str] = None
    text: Optional[str] = None
    uri: Optional[str] = None


class TagEvent(BaseModel):
    session_id: Optional[str] = None
    type: str                 # "read" sau "emulate"
    tag_id: Optional[str] = None
    tech: Optional[List[str]] = None
    ndef_records: Optional[List[NdefRecord]] = None


class TagConfigResponse(BaseModel):
    mode: str                 # "emulate" sau "none"
    tag_id: Optional[str] = None
    ndef_records: Optional[List[NdefRecord]] = None


class SetTagConfigRequest(BaseModel):
    session_id: Optional[str] = None
    mode: str                 # "emulate" sau "none"
    tag_id: Optional[str] = None
    ndef_records: Optional[List[NdefRecord]] = None


# ==============================
#   STARE IN-MEMORY (demo)
# ==============================

tag_configs: Dict[str, TagConfigResponse] = {}
last_apdu_per_session: Dict[str, str] = {}


# ==============================
#   UTILE
# ==============================

def check_auth(authorization: Optional[str]) -> None:
    """
    Verifică token-ul Bearer API.
    Dacă API_KEY e gol -> auth dezactivat.
    """
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
    docs_url="/docs",      # poți dezactiva la versiunea de producție
    redoc_url="/redoc",
)

# CORS – ca să poți vorbi și din app-uri web dacă vrei
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # pentru produs poți restricționa
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------- HANDLER GLOBAL EROARE ---------

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


# --------- APDU (JNFC / NFC Gate Remote Reader) ---------

@app.post("/apdu", response_model=ApduResponse)
async def handle_apdu(
    req: ApduRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Endpoint APDU Proxy.
    Clienții (JNFC / NFC Gate / app custom) trimit:
        {
          "command_apdu": "00A4040007A0000002471001",
          "session_id": "optional"
        }
    """
    check_auth(authorization)

    session_id = (req.session_id or "default").strip() or "default"
    cmd = req.command_apdu.upper().replace(" ", "")

    logger.info(f"[APDU] session={session_id} cmd={cmd}")

    # TODO: aici pui logica ta – trimiți APDU la card, emulator, etc.
    # Deocamdată doar răspundem 9000.
    resp_apdu = "9000"

    last_apdu_per_session[session_id] = cmd

    return ApduResponse(response_apdu=resp_apdu)


# --------- TAG MODE (citire) ---------

@app.post("/tag/event")
async def tag_event(
    event: TagEvent,
    authorization: Optional[str] = Header(None),
):
    """
    Telefonul trimite aici evenimente TAG (citire / emulare).
    """
    check_auth(authorization)

    logger.info(f"[TAG EVENT] {event.json()}")
    # aici poți salva în DB / trimite în alt sistem etc.

    return {"status": "ok"}


# --------- TAG MODE (config pentru emulare) ---------

@app.get("/tag/config", response_model=TagConfigResponse)
async def tag_config(
    session_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """
    Telefonul întreabă ce TAG trebuie să emuleze.
    Poți seta din GUI / admin un tag per sesiune.
    """
    check_auth(authorization)

    sid = (session_id or "default").strip() or "default"

    if sid in tag_configs:
        cfg = tag_configs[sid]
        logger.info(f"[TAG CONFIG] session={sid} -> {cfg.json()}")
        return cfg

    # fallback demo: un tag NDEF cu un URL
    demo_cfg = TagConfigResponse(
        mode="emulate",
        tag_id="04AABBCCDD22",
        ndef_records=[
            NdefRecord(
                record_type="uri",
                uri="https://example.com/nfc-demo"
            )
        ]
    )
    logger.info(f"[TAG CONFIG] session={sid} -> DEMO {demo_cfg.json()}")
    return demo_cfg


# --------- ADMIN / DEBUG ---------

@app.get("/sessions")
async def list_sessions(
    authorization: Optional[str] = Header(None),
):
    """
    Endpoint pentru debugging: vezi ultimele APDU-uri per sesiune.
    """
    check_auth(authorization)
    return {"sessions": last_apdu_per_session}


@app.post("/admin/set_tag")
async def set_tag_config(
    data: SetTagConfigRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Setează dinamic config-ul de TAG pentru o sesiune.
    Exemplu JSON:
    {
      "session_id": "client1",
      "mode": "emulate",
      "tag_id": "04AABBCCDD22",
      "ndef_records": [
        { "record_type": "uri", "uri": "https://google.com" }
      ]
    }
    """
    check_auth(authorization)

    sid = (data.session_id or "default").strip() or "default"

    cfg = TagConfigResponse(
        mode=data.mode,
        tag_id=data.tag_id,
        ndef_records=data.ndef_records,
    )

    tag_configs[sid] = cfg
    logger.info(f"[ADMIN] Set TAG CONFIG for session={sid}: {cfg.json()}")

    return {"status": "ok", "session_id": sid}
#... (Restul codului rămâne neschimbat)

# --------- ENDPOINT PENTRU DATURI BINARE ---------

@app.post("/nfc-bin")
async def handle_nfc_bin(request: Request):
    try:
        # Citește datele binare din cerere
        data = await request.body()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad request: {e}")

    # Procesarea datelor binare
    response_data = process_nfc_bin(data)

    return Response(content=response_data, media_type="application/octet-stream")

def process_nfc_bin(data: bytes) -> bytes:
    # Extragerea informațiilor din mesaj
    command_type = data[0:1]  # Primul byte pentru tipul comenzii
    command_data = data[1:]    # Restul datelor

    # Implementarea logicii pentru comenzi
    if command_type == b'\x01':
        logger.info("Comandă de tip 1 primită")
        return b"ACK: Comanda 1 procesata"
    elif command_type == b'\x02':
        logger.info("Comandă de tip 2 primită")
        return b"ACK: Comanda 2 procesata"
    
    logger.warning("Comandă necunoscută primită")
    return "Error: Comandă necunoscută"

# ==============================
#   PORNIRE UVICORN (pt. stand-alone)
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
