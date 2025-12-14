import requests
import sys

# --- CONFIGURARE ---
SERVER_URL = "https://nfc-server-production-7ea6.up.railway.app"  # sau "http://localhost:8000"
SESSION_ID = "phone"  # înlocuiește cu ID-ul tău (ex: "phone123")
API_KEY = "secret123"  # înlocuiește cu API key-ul tău din .env

TAG_CONFIG = {
    "session_id": SESSION_ID,
    "mode": "emulate",
    "tag_id": "04AABBCCDD22",
    "ndef_records": [
        {
            "record_type": "uri",
            "uri": "https://example.com/nfc"
        }
    ]
}
# -------------------

def set_tag_config():
    url = f"{SERVER_URL}/admin/set_tag"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=TAG_CONFIG, headers=headers)
        response.raise_for_status()
        print(f"✅ Configurație setată cu succes pentru session_id='{SESSION_ID}'")
        print("Răspuns:", response.json())
    except requests.exceptions.HTTPError as e:
        print(f"❌ Eroare HTTP: {e}")
        print("Detalii:", response.text)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Eroare: {e}")
        sys.exit(1)

if __name__ == "__main__":
    set_tag_config()