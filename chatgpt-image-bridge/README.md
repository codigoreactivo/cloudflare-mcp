# ChatGPT Image Bridge

Puente local (extensión Chrome + native messaging + servidor MCP) para que
tus agentes de terminal puedan pedir imágenes a ChatGPT reutilizando tu
sesión de Chrome ya logueada, sin tocar la API oficial.

Ubicación del proyecto: `~/Dev/mcp/chatgpt-image-bridge`. Historial de cambios
en [`CHANGELOG.md`](./CHANGELOG.md).

## ⚠️ Antes de usarlo (léelo)

Automatizar la interfaz web de ChatGPT para generar contenido de forma
programática **puede violar los Términos de Servicio de OpenAI** (que
restringen el acceso automatizado fuera de la API oficial). Es tu cuenta y
esto es para pruebas personales antes de pasarte a la API, pero un uso
intensivo o evidente podría hacer que OpenAI **limite o suspenda la cuenta**.

Este proyecto incluye un limitador de ritmo "lite" (anti-ráfaga) y teclea el
prompt con pausas, para no parecer un bot que dispara en ráfaga. **Esto reduce
el riesgo, no lo elimina:** ningún truco del lado del cliente derrota con
certeza la detección de automatización del servidor. La única protección real
es **volumen bajo y uso esporádico**. Úsalo con moderación.

## Seguridad del canal local

El daemon ya **no** usa un puerto TCP. Usa un **socket de dominio UNIX** en
`~/.chatgpt-image-bridge/bridge.sock` (no alcanzable por red; solo procesos de
tu usuario) y un **token** en `~/.chatgpt-image-bridge/token` que el daemon
crea automáticamente al arrancar. El directorio es `700` y los archivos `600`.
Tanto el host nativo como el servidor MCP leen ese token para autenticarse en
el handshake; una conexión sin el token correcto se rechaza.

## Arquitectura

```
[agente en terminal] --stdio--> [mcp_server/server.py]
                                        |
                    socket UNIX ~/.chatgpt-image-bridge/bridge.sock
                    (JSON por línea, handshake con token)
                                        |
                                [bridge_daemon.py]  <-- daemon persistente
                                  - autentica el token                     |
                                  - serializa: 1 generación a la vez       |
                                  - limita el ritmo (anti-ráfaga)          |
                                        |
                    socket UNIX (mismo, handshake con token)
                                        |
                          [native_host/host.py]  <-- lanzado por Chrome
                                        |
                        native messaging (stdio, protocolo de Chrome)
                                        |
                          [extension/background.js]
                                  - pestaña dedicada en 2º plano           |
                                  - chat nuevo por cada petición           |
                                        |
                        chrome.tabs.sendMessage
                                        |
                          [extension/content.js]  <-- corre en chatgpt.com
                                  - teclea con pausas, espera la imagen     |
                                        |
                              descarga vía chrome.downloads
```

`bridge_daemon.py` es el punto de encuentro y el único sitio por el que pasa
todo: por eso ahí viven la serialización y el limitador de ritmo.

## Instalación

### 0. Requisitos

```bash
cd ~/Dev/mcp/chatgpt-image-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1. Arrancar el daemon puente

Debe quedar corriendo siempre que quieras usar esto (déjalo en una terminal
aparte, en `tmux`, o crea un LaunchAgent si quieres que arranque solo). La
primera vez crea el token y el socket automáticamente:

```bash
python3 bridge_daemon.py
```

Opcional: ajustar el ritmo con variables de entorno (defaults conservadores):

```bash
BRIDGE_MIN_GAP_SECONDS=20 \
BRIDGE_MAX_GAP_SECONDS=45 \
BRIDGE_MAX_PER_HOUR=12 \
BRIDGE_MAX_PER_DAY=60 \
python3 bridge_daemon.py
```

- `BRIDGE_MIN_GAP_SECONDS` / `BRIDGE_MAX_GAP_SECONDS`: hueco entre generaciones;
  el real se elige al azar en ese rango (jitter anti-ráfaga).
- `BRIDGE_MAX_PER_HOUR` / `BRIDGE_MAX_PER_DAY`: topes duros. Al superarlos, la
  tool devuelve un error indicando en cuánto reintentar.
- Los contadores son **en memoria**: si reinicias el daemon, se reinician.

#### Autoarranque (ya configurado como LaunchAgent)

El daemon ya está instalado como LaunchAgent en
`~/Library/LaunchAgents/com.jesusjhoel.chatgpt-image-bridge.plist`: arranca solo
al iniciar sesión y se reinicia si se cae. No hace falta lanzarlo a mano; el
comando de arriba es solo para depurar. Consume ~8 MB de RAM y 0 % de CPU en
reposo.

```bash
# estado (running + pid)
launchctl print gui/$(id -u)/com.jesusjhoel.chatgpt-image-bridge | grep -E 'state =|pid ='
# reiniciar (tras cambiar el código o el ritmo en el plist)
launchctl kickstart -k gui/$(id -u)/com.jesusjhoel.chatgpt-image-bridge
# parar y desactivar (deja de arrancar en login)
launchctl bootout gui/$(id -u)/com.jesusjhoel.chatgpt-image-bridge
# volver a activar
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jesusjhoel.chatgpt-image-bridge.plist
# ver logs
tail -f ~/Library/Logs/chatgpt-image-bridge.err.log
```

Para ajustar el ritmo, edita las variables `BRIDGE_*` en el plist y reinicia con
`kickstart -k`.

### 2. Cargar la extensión en Chrome

1. Ve a `chrome://extensions`.
2. Activa "Modo de desarrollador" (arriba a la derecha).
3. Clic en "Cargar descomprimida" y selecciona la carpeta `extension/`.
4. Copia el **ID de la extensión** que aparece en su tarjeta.

> El ID de una extensión descomprimida depende de la **ruta** de la carpeta.
> Como el proyecto vive en `~/Dev/mcp/chatgpt-image-bridge`, cárgala desde ahí.
> Si vuelves a mover la carpeta, el ID cambia y tendrás que recargar la
> extensión y repetir el paso 3.

### 3. Registrar el host nativo

```bash
cd native_host
python3 install.py <EXTENSION_ID>
```

Escribe el manifest en:
`~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.jesusjhoel.chatgpt_bridge.json`
(solo Google Chrome; para Brave/Edge/Chromium haría falta la carpeta
equivalente de ese navegador).

### 4. Reiniciar Chrome completamente

Cierra Chrome del todo (Cmd+Q) y vuelve a abrirlo. En `chrome://extensions`
(clic en "Service worker" de la extensión) revisa que no haya errores de
conexión con el host nativo.

### 5. Iniciar sesión en ChatGPT

Abre `https://chatgpt.com` en ese mismo Chrome e inicia sesión. La
automatización reutiliza esa sesión desde una pestaña dedicada en segundo
plano; no necesitas volver a loguearte.

### 6. Registrar el servidor MCP en tu agente

Con Claude Code (usa el `python3` del venv del paso 0 para que tenga `mcp`):

```bash
claude mcp add chatgpt-image-bridge -- \
  ~/Dev/mcp/chatgpt-image-bridge/.venv/bin/python \
  ~/Dev/mcp/chatgpt-image-bridge/mcp_server/server.py
```

## Uso correcto y estricto (skill)

Hay una skill de Claude Code en `~/.claude/skills/chatgpt-image-bridge/` que
impone el uso seguro de este MCP (preflight, una imagen a la vez, respetar los
topes de ritmo, sin reintentos en bucle, sin evasión). El agente la carga sola
al ir a usar `generate_chatgpt_image`. No la borres si quieres que el uso siga
siendo cuidadoso.

## Uso

Con el daemon corriendo, Chrome abierto (logueado en ChatGPT) y el MCP
registrado, tu agente llama a la tool:

```
generate_chatgpt_image(prompt="un zorro low-poly sobre fondo degradado")
```

Devuelve las rutas locales absolutas de las imágenes descargadas (en tu
carpeta de Descargas, dentro de `chatgpt_bridge/`).

Por el anti-ráfaga, una llamada puede tardar más que la generación en sí: si
hay otra en curso o toca esperar el espaciado, se pone en cola. El servidor MCP
espera hasta `timeout + BRIDGE_QUEUE_ALLOWANCE` (default 900 s) por eso.

## Si algo se rompe: selectores del DOM

ChatGPT cambia su interfaz con frecuencia. Toda la automatización del DOM vive
en `extension/content.js`, con los selectores centralizados en el objeto
`SELECTORS` al inicio:

- `composer`: el cuadro de texto del prompt.
- `sendButton`: el botón de enviar.
- `stopButton`: el botón mientras genera (su desaparición indica que terminó).
- `assistantMessage`: el contenedor de la respuesta del asistente.

Abre chatgpt.com, inspecciona el elemento con DevTools, actualiza el selector y
recarga la extensión desde `chrome://extensions`.

## Limitaciones conocidas

- **Una generación a la vez**: el daemon serializa a propósito. Varias
  peticiones MCP se encolan (esto también evita cruces entre requests).
- **Ritmo limitado a propósito**: con los defaults, máx. 12/hora y 60/día, con
  huecos de 20-45 s. Ajústalo con las env vars si te queda corto — pero recuerda
  el aviso de arriba sobre suspensiones.
- **Descarga de la imagen endurecida, verificada en vivo**: `content.js` toma
  las `<img>` con `naturalWidth > 64` del último mensaje, y descarga cada una
  con `fetch()` **dentro del content script** (con la sesión de la página),
  convirtiéndola a data URL antes de pasarla a `background.js` para
  `chrome.downloads.download`. Esto evita depender de que el service worker
  resuelva una URL firmada sin la sesión de la pestaña. Probado con una
  imagen real de 1.8 MB generada en vivo con la cuenta del usuario: round-trip
  byte-perfecto (SHA256 idéntico) y detección correcta de la extensión real
  (png/jpg/webp/gif) por mime type. Si el `fetch()` falla —p. ej. por CORS, si
  la URL firmada vive en un CDN de otro dominio que no exponga
  `Access-Control-Allow-Origin`— hay timeout (30s) y **fallback automático**
  a pasar la URL https cruda a `chrome.downloads.download`, igual que el
  diseño original, para no perder la imagen por este paso extra.
- **Extensión atada a la ruta**: mover la carpeta cambia el ID (ver paso 2).
- El service worker MV3 puede suspenderse por inactividad; el `alarm` de
  `background.js` reconecta el host nativo, con algo de latencia en la primera
  petición tras un rato inactivo.
- Si Chrome está cerrado o la extensión no está conectada, la tool falla con un
  error explícito en vez de colgarse.
