import subprocess
import threading
import time
import json
import urllib.request
import urllib.error
import sys
import os
import tkinter as tk
from tkinter import messagebox

# ==========================
#   CONFIGURARE PENTRU TINE
# ==========================

# Executabil Python
PYTHON_EXE = "python"

# Folderul unde se află server.py și ngrok.exe
SERVER_DIR = r"C:\NFCServer"

SERVER_SCRIPT = os.path.join(SERVER_DIR, "server.py")
NGROK_PATH = os.path.join(SERVER_DIR, "ngrok.exe")

# Port Flask
FLASK_PORT = 5000

# ==========================
#   VARIABILE GLOBALE
# ==========================

server_proc = None
ngrok_proc = None

# ==========================
#   FUNCTII UTILE
# ==========================

def log(msg):
    """Scrie un mesaj în zona de log."""
    log_text.config(state=tk.NORMAL)
    log_text.insert(tk.END, msg + "\n")
    log_text.see(tk.END)
    log_text.config(state=tk.DISABLED)

def start_server():
    """Pornește server.py și ngrok."""
    global server_proc, ngrok_proc

    if server_proc or ngrok_proc:
        messagebox.showinfo("Info", "Serverul sau ngrok par deja pornite.")
        return

    # ================================
    # 1️⃣ PORNIRE SERVER.PY
    # ================================
    try:
        log("Pornesc server.py...")

        server_proc = subprocess.Popen(
            [PYTHON_EXE, SERVER_SCRIPT],
            cwd=SERVER_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        threading.Thread(target=read_process_output,
                         args=(server_proc, "[SERVER]"),
                         daemon=True).start()

    except Exception as e:
        messagebox.showerror("Eroare", f"Nu pot porni server.py:\n{e}")
        server_proc = None
        return

    # ================================
    # 2️⃣ PORNIRE NGROK
    # ================================
    try:
        log("Pornesc ngrok...")

        ngrok_proc = subprocess.Popen(
            [NGROK_PATH, "http", str(FLASK_PORT)],
            cwd=SERVER_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        threading.Thread(target=read_process_output,
                         args=(ngrok_proc, "[NGROK]"),
                         daemon=True).start()

    except Exception as e:
        messagebox.showerror("Eroare", f"Nu pot porni ngrok.exe:\n{e}")
        ngrok_proc = None
        return

    log("Aștept 4 secunde să pornească ngrok...")
    root.after(4000, fetch_ngrok_url)


def read_process_output(proc, prefix):
    """Afișează output-ul proceselor în log."""
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(f"{prefix} {line}")
    except Exception as e:
        log(f"{prefix} Eroare la citirea outputului: {e}")


def fetch_ngrok_url():
    url = "http://127.0.0.1:4040/api/tunnels"

    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except:
        log("[NGROK] Ngrok nu pare pornit încă...")
        return

    public_url = None

    for tunnel in data.get("tunnels", []):
        if tunnel.get("public_url", "").startswith("https://"):
            public_url = tunnel["public_url"]

    if public_url:
        url_var.set(public_url)
        log(f"URL ngrok detectat: {public_url}")
    else:
        log("[NGROK] Nu am găsit niciun URL public.")


def refresh_ngrok_url():
    fetch_ngrok_url()


def copy_url():
    link = url_var.get().strip()
    if not link:
        messagebox.showinfo("Info", "Nu există URL de copiat.")
        return
    root.clipboard_clear()
    root.clipboard_append(link)
    log(f"URL copiat: {link}")
    messagebox.showinfo("Copiat", "URL a fost copiat în clipboard.")


def stop_all():
    """Oprește serverul și ngrok."""
    global server_proc, ngrok_proc

    if server_proc:
        log("Oprirea server.py...")
        server_proc.terminate()
        server_proc = None

    if ngrok_proc:
        log("Oprirea ngrok.exe...")
        ngrok_proc.terminate()
        ngrok_proc = None

    log("Totul a fost oprit.")

def on_close():
    if messagebox.askyesno("Ieșire", "Vrei să oprești serverul și ngrok înainte de ieșire?"):
        stop_all()
    root.destroy()


# ==========================
#   GUI
# ==========================

root = tk.Tk()
root.title("NFC Server + Ngrok Controller")
root.geometry("700x500")

top = tk.Frame(root)
top.pack(fill=tk.X, padx=10, pady=5)

tk.Button(top, text="START SERVER + NGROK", command=start_server, bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)
tk.Button(top, text="STOP TOT", command=stop_all, bg="#F44336", fg="white").pack(side=tk.LEFT, padx=5)
tk.Button(top, text="Refresh URL Ngrok", command=refresh_ngrok_url).pack(side=tk.LEFT, padx=5)

url_frame = tk.Frame(root)
url_frame.pack(fill=tk.X, padx=10, pady=5)

tk.Label(url_frame, text="URL Ngrok:").pack(side=tk.LEFT)

url_var = tk.StringVar()
tk.Entry(url_frame, textvariable=url_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

tk.Button(url_frame, text="Copiere", command=copy_url).pack(side=tk.LEFT, padx=5)

log_frame = tk.Frame(root)
log_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)

log_text = tk.Text(log_frame, state=tk.DISABLED, wrap=tk.WORD)
log_text.pack(fill=tk.BOTH, expand=True)

log("GUI pornit. Apasă pe START SERVER + NGROK.")

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
