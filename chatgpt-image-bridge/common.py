"""
Configuración compartida por el daemon, el host nativo y el servidor MCP.

El canal de control es un **socket de dominio UNIX** (no TCP), así que no es
alcanzable por red: solo procesos del mismo usuario, con acceso al archivo del
socket, pueden conectarse. Encima, el handshake exige un **token** local. El
token lo crea el daemon al arrancar (permisos 600) dentro de un directorio con
permisos 700.
"""

import os
import secrets

RUNTIME_DIR = os.path.expanduser("~/.chatgpt-image-bridge")
SOCKET_PATH = os.path.join(RUNTIME_DIR, "bridge.sock")
TOKEN_PATH = os.path.join(RUNTIME_DIR, "token")


def ensure_runtime_dir() -> None:
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    os.chmod(RUNTIME_DIR, 0o700)


def load_or_create_token() -> str:
    """Devuelve el token, creándolo si no existe. Lo llama el daemon."""
    ensure_runtime_dir()
    if os.path.exists(TOKEN_PATH):
        return _read_token()
    token = secrets.token_hex(32)
    # Creación atómica con permisos restrictivos desde el primer byte.
    fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(TOKEN_PATH, 0o600)
    return token


def load_token() -> str:
    """Lee el token existente. Lo llaman los clientes (host nativo y MCP).
    Lanza FileNotFoundError si el daemon aún no lo ha creado."""
    return _read_token()


def _read_token() -> str:
    with open(TOKEN_PATH, "r") as f:
        return f.read().strip()
