import socket
import select
import struct
import logging
import os
import sys

# Configurare
HOST = '0.0.0.0'
PORT = int(os.environ.get("PORT", 5566)) # Portul din Railway sau default

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger("BlindRelay")

def recv_exact(sock, n):
    """Citește exact n bytes sau dă eroare dacă conexiunea cade."""
    data = b''
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data += packet
    return data

def handle_traffic(sock_a, sock_b):
    """Mută pachetele respectând lungimea (framing-ul) protocolului NFCGate."""
    try:
        # 1. Citește lungimea mesajului (primii 4 bytes, Big Endian)
        raw_len = recv_exact(sock_a, 4)
        if not raw_len:
            return False
        
        msg_len = struct.unpack('!I', raw_len)[0]
        
        # 2. Citește corpul mesajului bazat pe lungime
        msg_body = recv_exact(sock_a, msg_len)
        if not msg_body:
            return False

        # 3. Trimite tot pachetul (lungime + corp) către partener
        sock_b.sendall(raw_len + msg_body)
        return True
    except Exception as e:
        logger.error(f"Eroare transfer: {e}")
        return False

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(2)
        logger.info(f"🚀 Server BLIND RELAY pornit pe portul {PORT}")
        logger.info("Astept 2 dispozitive pentru a le conecta intre ele...")
    except Exception as e:
        logger.error(f"Nu pot porni serverul: {e}")
        sys.exit(1)

    clients = []

    while True:
        # Așteptăm conexiuni până avem 2 clienți
        while len(clients) < 2:
            conn, addr = server_socket.accept()
            logger.info(f"✅ Conectat: {addr}")
            clients.append(conn)
            
            if len(clients) == 1:
                logger.info("⏳ Aștept partenerul...")
            elif len(clients) == 2:
                logger.info("⚡ PERECHE FORMATĂ! Începe relay-ul.")

        # Bucla de relay între cei 2 clienți
        sock1, sock2 = clients[0], clients[1]
        
        # Monitorizăm ambele socket-uri
        valid_connection = True
        while valid_connection:
            readable, _, _ = select.select([sock1, sock2], [], [])
            
            for s in readable:
                if s is sock1:
                    if not handle_traffic(sock1, sock2):
                        valid_connection = False
                elif s is sock2:
                    if not handle_traffic(sock2, sock1):
                        valid_connection = False
            
        logger.info("❌ O conexiune a fost închisă. Resetez totul.")
        # Închidem tot și o luăm de la capăt
        for c in clients:
            try: c.close()
            except: pass
        clients = []

if __name__ == "__main__":
    main()
