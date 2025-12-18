import asyncio
import websockets
import json
import sys

# 🔧 Configurare — SCHIMBĂ cu valorile tale
SERVER_URL = "wss://tudomeniu.railway.app/ws"
SESSION_ID = "nfc_log_session"
API_KEY = "your-secret-api-key"  # trebuie să fie același ca în .env pe server


async def tag_simulator():
    uri = f"{SERVER_URL}?session_id={SESSION_ID}&role=tag&token={API_KEY}"
    print(f"🟢 Conectare la: {uri}")

    try:
        async with websockets.connect(uri) as ws:
            print("✅ Conectat la serverul NFC!")

            # Așteaptă mesaje
            async for message in ws:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "apdu_request":
                        cmd = data.get("command_apdu", "")
                        print(f"\n📥 Comandă APDU primită: {cmd}")
                        # ✅ Răspuns automat (simulează un tag real)
                        response = "9000"  # Succes
                        await ws.send(json.dumps({
                            "type": "apdu_response",
                            "response_apdu": response
                        }))
                        print(f"📤 Trimis răspuns: {response}")

                    elif msg_type == "nfc_full_data":
                        print("\n📡 Date NFC primite de la cititor:")
                        print(f"   🕒 Timestamp: {data.get('timestamp')}")
                        print(f"   📡 APDU trimis: {data.get('apdu_command')}")
                        print(f"   📥 APDU primit: {data.get('apdu_response')}")
                        print(f"   🏷️ Tip tag: {data.get('tag_type')}")

                    else:
                        print(f"📧 Mesaj necunoscut: {data}")

                except json.JSONDecodeError:
                    print(f"❌ Mesaj invalid: {message}")
                except Exception as e:
                    print(f"⚠️ Eroare procesare: {e}")

    except websockets.InvalidStatusCode as e:
        if e.status_code == 403:
            print("❌ TOKEN INVALID! Verifică API_KEY.")
        elif e.status_code == 400:
            print("❌ Cerere invalidă – verifică session_id sau role.")
        else:
            print(f"❌ Eroare conexiune: {e.status_code}")
    except Exception as e:
        print(f"💥 Eroare: {e}")


if __name__ == "__main__":
    print("🚀 Pornire simulator de tag NFC...")
    asyncio.run(tag_simulator())