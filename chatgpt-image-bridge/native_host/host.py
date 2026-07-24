"""
Host de native messaging: Chrome lo lanza como subproceso (vía stdio) cuando
la extensión llama a chrome.runtime.connectNative(). Su única función es
retransmitir mensajes entre Chrome (protocolo native messaging: 4 bytes de
longitud little-endian + JSON UTF-8) y bridge_daemon.py (JSON por línea sobre
un socket de dominio UNIX autenticado con token).

No lo ejecutes directamente: Chrome lo invoca a través de run_host.sh, cuya
ruta se registra con install.py.
"""

import json
import os
import socket
import struct
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402


def _read_exact(stream, n):
    """Lee EXACTAMENTE n bytes del stream (los pipes entregan por trozos).
    Devuelve None si el stream se cierra antes de completar."""
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def read_native_message():
    raw_length = _read_exact(sys.stdin.buffer, 4)
    if raw_length is None:
        return None
    message_length = struct.unpack("<I", raw_length)[0]
    body = _read_exact(sys.stdin.buffer, message_length)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def send_native_message(obj) -> None:
    encoded = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main() -> None:
    try:
        token = common.load_token()
    except FileNotFoundError:
        send_native_message({
            "type": "fatal_error",
            "error": ("No existe el token del bridge. ¿Está corriendo "
                      "'python3 bridge_daemon.py'?"),
        })
        return

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(common.SOCKET_PATH)
        sock.settimeout(None)
    except OSError:
        send_native_message({
            "type": "fatal_error",
            "error": (f"No se pudo conectar al daemon en {common.SOCKET_PATH}. "
                      f"¿Está corriendo 'python3 bridge_daemon.py'?"),
        })
        return

    sock_file = sock.makefile("r")
    sock.sendall((json.dumps({"role": "extension", "token": token}) + "\n").encode("utf-8"))

    def daemon_to_chrome() -> None:
        for line in sock_file:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            send_native_message(msg)

    t = threading.Thread(target=daemon_to_chrome, daemon=True)
    t.start()

    while True:
        msg = read_native_message()
        if msg is None:
            break
        try:
            sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        except OSError:
            break


if __name__ == "__main__":
    main()
