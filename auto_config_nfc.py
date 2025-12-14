import re
import json
import requests
from collections import defaultdict

# 🔧 Configurare
LOG_FILE = "nfc_server.log"
SERVER_URL = "http://localhost:8000"  # sau Railway URL
API_KEY = "secret123"  # înlocuiește cu API key-ul tău

# TAG-uri implicite
DEFAULT_TAG_CONFIG = {
    "mode": "emulate",
    "tag_id": "04AABBCCDD22",
    "ndef_records": [
        {"record_type": "uri", "uri": "https://example.com/nfc"}
    ]
}

def extract_session_ids_from_log():
    session_ids = set()
    tag_config_pattern = r'\[TAG CONFIG\] session=([^\s]+)'
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            match = re.search(tag_config_pattern, line)
            if match:
                sid = match.group(1)
                session_ids.add(sid)
    return session_ids

def is_likely_emulator(session_id: str) -> bool:
    """Heuristic: considerăm sesiunea emulator dacă are cuvinte-cheie."""
    emulator_keywords = {"tag", "emul", "nfc", "phone", "device", "client"}
    return any(kw in session_id.lower() for kw in emulator_keywords)

def set_tag_config(session_id: str):
    url = f"{SERVER_URL}/admin/set_tag"
    payload = {
        "session_id": session_id,
        **DEFAULT_TAG_CONFIG
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"✅ Configurație setată pentru: {session_id}")
        return True
    except Exception as e:
        print(f"❌ Eroare la setarea {session_id}: {e}")
        return False

def main():
    print("🔍 Scan log for active session_id...")
    session_ids = extract_session_ids_from_log()
    if not session_ids:
        print("⚠️ Nu s-au găsit session_id în log.")
        return

    print(f"🆔 Găsite sesiuni: {sorted(session_ids)}")

    for sid in session_ids:
        if is_likely_emulator(sid):
            print(f"🤖 Detectat emulator: {sid}")
            set_tag_config(sid)
        else:
            print(f"📡 Sesiune ignorată (cititor?): {sid}")

if __name__ == "__main__":
    main()