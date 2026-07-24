"""
Servidor MCP que expone una tool `generate_chatgpt_image` a tus agentes de
terminal (Claude Code, etc). Traduce cada llamada en una request al
bridge_daemon.py (vía socket de dominio UNIX + token), que a su vez la
retransmite a la extensión de Chrome para que automatice chatgpt.com con tu
sesión ya logueada.

Requiere que bridge_daemon.py esté corriendo y que la extensión esté conectada
(Chrome abierto, host nativo instalado, sesión iniciada en chatgpt.com).

Nota: el daemon serializa y espacia las generaciones (anti-ráfaga), así que una
llamada puede tardar más de lo que dura la generación en sí porque espera turno.
Por eso el socket espera hasta `timeout` + BRIDGE_QUEUE_ALLOWANCE segundos.
"""

import json
import os
import socket
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

DEFAULT_TIMEOUT = 180
# Margen extra para tolerar la espera en cola (serialización + espaciado).
QUEUE_ALLOWANCE = int(os.environ.get("BRIDGE_QUEUE_ALLOWANCE", "900"))

mcp = FastMCP("chatgpt-image-bridge")


def _request_image(prompt: str, count: int, timeout: int) -> list:
    try:
        token = common.load_token()
    except FileNotFoundError as e:
        raise RuntimeError(
            "El daemon no está corriendo (no existe el token). Arranca "
            "'python3 bridge_daemon.py'."
        ) from e

    request_id = str(uuid.uuid4())
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(common.SOCKET_PATH)
    except OSError as e:
        raise RuntimeError(
            f"No se pudo conectar al daemon ({common.SOCKET_PATH}). "
            f"¿Está corriendo 'python3 bridge_daemon.py'? [{e}]"
        ) from e

    with sock:
        sock_file = sock.makefile("r")
        sock.sendall((json.dumps({"role": "mcp", "token": token}) + "\n").encode("utf-8"))
        sock.sendall(
            (json.dumps({
                "type": "request", "id": request_id,
                "prompt": prompt, "n": count, "timeout": timeout,
            }) + "\n").encode("utf-8")
        )
        sock.settimeout(timeout + QUEUE_ALLOWANCE)
        while True:
            line = sock_file.readline()
            if not line:
                raise RuntimeError(
                    "Conexión con el daemon cerrada inesperadamente."
                )
            msg = json.loads(line)
            if msg.get("type") == "error":  # handshake rechazado (token)
                raise RuntimeError(msg.get("error", "error de handshake"))
            if msg.get("type") == "response" and msg.get("id") == request_id:
                if msg.get("error"):
                    raise RuntimeError(msg["error"])
                return msg.get("paths", [])


@mcp.tool()
def generate_chatgpt_image(prompt: str, count: int = 1, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Genera imagen(es) en ChatGPT (chatgpt.com) usando tu sesión de Chrome
    ya autenticada, y devuelve las rutas locales absolutas de los archivos
    descargados (una por línea).

    El daemon serializa y espacia las peticiones para evitar ráfagas, así que
    la llamada puede tardar más de lo esperado si hay otra en curso o si toca
    esperar por el espaciado anti-ráfaga. Si se supera un tope por hora/día,
    devuelve un error indicando en cuánto tiempo reintentar.

    Args:
        prompt: descripción de la imagen a generar.
        count: informativo; ChatGPT decide cuántas imágenes devuelve por respuesta.
        timeout: segundos máximos para la generación en sí (sin contar la cola).
    """
    try:
        paths = _request_image(prompt, count, timeout)
    except socket.timeout as e:
        raise RuntimeError(
            f"Timeout esperando la generación ({timeout}s + cola)."
        ) from e

    if not paths:
        return "No se recibieron imágenes."
    return "\n".join(paths)


if __name__ == "__main__":
    mcp.run()
