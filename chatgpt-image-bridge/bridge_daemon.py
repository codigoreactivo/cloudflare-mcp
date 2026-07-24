"""
Daemon local: punto de encuentro entre el host nativo (extensión de Chrome) y
el servidor MCP. Sobre un socket de dominio UNIX (no TCP → no alcanzable por
red) con autenticación por token.

Además del ruteo, el daemon es el único punto por el que pasa TODO, así que
aquí viven dos protecciones:

  1. Serialización: solo una generación en vuelo a la vez (un asyncio.Lock).
     Esto también evita que la extensión reciba dos peticiones a la vez.

  2. Limitador de ritmo "lite" (anti-ráfaga): espaciado aleatorio entre
     generaciones + topes por hora y por día. El objetivo es no golpear la web
     de ChatGPT con un patrón robótico de ráfaga. Ver AVISO más abajo: esto
     reduce el riesgo, no lo elimina.

Config por variables de entorno (con defaults conservadores):
    BRIDGE_MIN_GAP_SECONDS  (default 20)   hueco mínimo entre generaciones
    BRIDGE_MAX_GAP_SECONDS  (default 45)   hueco máximo (se elige al azar en [min,max])
    BRIDGE_MAX_PER_HOUR     (default 12)   tope de generaciones por hora
    BRIDGE_MAX_PER_DAY      (default 60)   tope de generaciones por día
    BRIDGE_GEN_TIMEOUT      (default 180)  timeout por generación (s)

Debe quedar corriendo antes de usar la extensión o el MCP:
    python3 bridge_daemon.py

AVISO: ningún limitador del lado del cliente garantiza que OpenAI no detecte
automatización ni evita una suspensión. La única protección real es volumen
bajo y uso esporádico. Esto solo evita el patrón de ráfaga más obvio.
"""

import asyncio
import json
import logging
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[daemon] %(asctime)s %(message)s")
log = logging.getLogger("bridge_daemon")


def _envf(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


MIN_GAP = _envf("BRIDGE_MIN_GAP_SECONDS", 20.0)
MAX_GAP = max(MIN_GAP, _envf("BRIDGE_MAX_GAP_SECONDS", 45.0))
MAX_PER_HOUR = int(_envf("BRIDGE_MAX_PER_HOUR", 12))
MAX_PER_DAY = int(_envf("BRIDGE_MAX_PER_DAY", 60))
DEFAULT_GEN_TIMEOUT = _envf("BRIDGE_GEN_TIMEOUT", 180.0)

TOKEN = common.load_or_create_token()

extension_writer = None          # writer de la extensión conectada (solo una)
pending: dict = {}               # id -> asyncio.Future con la respuesta
gen_lock: asyncio.Lock = None    # se instancia en main(), serializa generaciones

# Ritmo: marcas de tiempo (wall clock) de inicios de generación.
_starts_wall: list = []
_last_start_monotonic = 0.0


async def _write_line(writer, obj) -> None:
    writer.write((json.dumps(obj) + "\n").encode("utf-8"))
    await writer.drain()


def _rate_decision():
    """Decide si se puede generar ahora.

    Devuelve (allowed, delay, reason):
      - allowed=True, delay>0  -> permitido, pero duerme `delay` s antes (espaciado).
      - allowed=False          -> rechazado por tope; `delay` es el retry-after y
                                   `reason` lo explica.
    """
    global _starts_wall
    wall = time.time()
    _starts_wall = [t for t in _starts_wall if wall - t < 86400.0]

    in_day = len(_starts_wall)
    if in_day >= MAX_PER_DAY:
        oldest = min(_starts_wall)
        return False, 86400.0 - (wall - oldest), f"tope diario ({MAX_PER_DAY}) alcanzado"

    hour_marks = [t for t in _starts_wall if wall - t < 3600.0]
    if len(hour_marks) >= MAX_PER_HOUR:
        return False, 3600.0 - (wall - min(hour_marks)), f"tope por hora ({MAX_PER_HOUR}) alcanzado"

    gap = random.uniform(MIN_GAP, MAX_GAP)
    delay = max(0.0, (_last_start_monotonic + gap) - time.monotonic())
    return True, delay, ""


def _record_start() -> None:
    global _last_start_monotonic
    _last_start_monotonic = time.monotonic()
    _starts_wall.append(time.time())


async def handle_mcp_request(msg, writer) -> None:
    req_id = msg.get("id")
    if req_id is None:
        await _write_line(writer, {"type": "response", "id": None, "error": "request sin 'id'"})
        return
    if extension_writer is None:
        await _write_line(writer, {
            "type": "response", "id": req_id,
            "error": ("La extensión de Chrome no está conectada. Abre Chrome (con la "
                      "extensión cargada) e inicia sesión en chatgpt.com."),
        })
        return

    timeout = float(msg.get("timeout") or DEFAULT_GEN_TIMEOUT)

    # El lock serializa TODA la cadena (espaciado + generación): una a la vez.
    async with gen_lock:
        allowed, delay, reason = _rate_decision()
        if not allowed:
            await _write_line(writer, {
                "type": "response", "id": req_id,
                "error": f"Límite de ritmo: {reason}. Reintenta en ~{int(delay)}s.",
            })
            return
        if delay > 0:
            log.info("espaciando %.1fs antes de generar (anti-ráfaga)", delay)
            await asyncio.sleep(delay)
        if extension_writer is None:
            await _write_line(writer, {
                "type": "response", "id": req_id,
                "error": "La extensión se desconectó mientras se esperaba turno.",
            })
            return

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        pending[req_id] = fut
        _record_start()
        try:
            await _write_line(extension_writer, {
                "type": "request", "id": req_id,
                "prompt": msg.get("prompt", ""), "n": msg.get("n", 1),
            })
        except Exception as e:  # noqa: BLE001
            pending.pop(req_id, None)
            await _write_line(writer, {
                "type": "response", "id": req_id,
                "error": f"No se pudo enviar a la extensión: {e}",
            })
            return

        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            resp = {"type": "response", "id": req_id,
                    "error": f"Timeout ({int(timeout)}s) esperando la imagen."}
        finally:
            pending.pop(req_id, None)

    # Fuera del lock: entregar la respuesta al cliente MCP.
    try:
        await _write_line(writer, resp)
    except Exception:  # noqa: BLE001
        pass  # el cliente MCP ya se fue; nada que hacer


async def handle_extension(reader, writer) -> None:
    global extension_writer
    # Solo se sigue una extensión a la vez. Si ya había una conectada (p.ej.
    # el usuario tiene la extensión cargada en dos navegadores, o un proceso
    # viejo no llegó a desconectarse limpio), se cierra explícitamente en vez
    # de dejarla huérfana: conectada a nivel de socket pero nunca más
    # referenciada, y por tanto inalcanzable para futuras peticiones.
    if extension_writer is not None and extension_writer is not writer:
        log.info("nueva conexión de extensión: cerrando la anterior")
        try:
            extension_writer.close()
        except Exception:  # noqa: BLE001
            pass
    extension_writer = writer
    log.info("extensión conectada")
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "response":
                fut = pending.get(msg.get("id"))
                if fut is not None and not fut.done():
                    fut.set_result(msg)
    finally:
        if writer is extension_writer:
            extension_writer = None
            log.info("extensión desconectada")


async def handle_mcp(reader, writer) -> None:
    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "request":
            await handle_mcp_request(msg, writer)


async def handle_client(reader, writer) -> None:
    try:
        hello_line = await reader.readline()
        if not hello_line:
            return
        try:
            hello = json.loads(hello_line)
        except json.JSONDecodeError:
            return
        if hello.get("token") != TOKEN:
            log.warning("handshake rechazado: token inválido")
            try:
                await _write_line(writer, {"type": "error", "error": "token inválido"})
            except Exception:  # noqa: BLE001
                pass
            return
        role = hello.get("role")
        if role == "extension":
            await handle_extension(reader, writer)
        elif role == "mcp":
            await handle_mcp(reader, writer)
        else:
            log.warning("rol desconocido en handshake: %r", role)
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("error en conexión: %s", e)
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    global gen_lock
    gen_lock = asyncio.Lock()
    common.ensure_runtime_dir()
    if os.path.exists(common.SOCKET_PATH):
        os.unlink(common.SOCKET_PATH)  # limpiar socket viejo
    server = await asyncio.start_unix_server(handle_client, path=common.SOCKET_PATH)
    os.chmod(common.SOCKET_PATH, 0o600)
    log.info("escuchando en socket UNIX %s", common.SOCKET_PATH)
    log.info("token: %s (perms 600)", common.TOKEN_PATH)
    log.info("ritmo: hueco %.0f-%.0fs, tope %d/h, %d/día",
             MIN_GAP, MAX_GAP, MAX_PER_HOUR, MAX_PER_DAY)
    try:
        async with server:
            await server.serve_forever()
    finally:
        # Borra el socket al cerrar para no dejar un archivo huérfano que
        # simule que el daemon sigue vivo.
        if os.path.exists(common.SOCKET_PATH):
            try:
                os.unlink(common.SOCKET_PATH)
            except OSError:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
