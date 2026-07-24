# Changelog

Todas las versiones se refieren a `extension/version` en `extension/manifest.json`.
El backend (`bridge_daemon.py`, `native_host/`, `mcp_server/`) no tiene versión
propia; sus cambios se listan aquí igual, marcados como tal.

## 1.1.0 — 2026-07-24

### Extensión (`extension/content.js`, `extension/background.js`)

- **Descarga de imágenes endurecida.** `content.js` ahora hace `fetch()` de
  cada imagen generada *dentro del content script* (con la sesión de la
  página) y la convierte a data URL antes de pasarla a `background.js`, en
  vez de dejar que el service worker intente resolver la URL firmada
  directamente con `chrome.downloads.download`. Verificado con una imagen
  real de 1.8 MB: round-trip byte-perfecto (SHA256 idéntico).
- **Timeout + fallback automático.** El fetch de cada imagen tiene un timeout
  de 30s (`AbortController`); si falla (red, o CORS si la URL firmada vive en
  un CDN de otro dominio), se hace fallback a la URL https cruda en vez de
  abortar toda la generación. Probado contra un servidor que nunca responde.
- **Timeout de red de seguridad en `background.js`** (`sendToContentScript`,
  210s) para no colgarse indefinidamente si el content script nunca llega a
  responder (pestaña muerta, mensaje perdido).
- **Extensión de archivo real**: `extensionFromDataUrl()` deriva `.png` /
  `.jpg` / `.webp` / `.gif` del mime type de la data URL (o de la propia URL
  en el caso de fallback), en vez de asumir siempre `.png`.
- Revisado por dos agentes independientes (corrección + seguridad); ambos
  concluyeron que el cambio es una mejora neta de seguridad frente al diseño
  anterior (URL firmada pasada cruda al service worker).

### Backend (sin versión propia, mismo commit)

- `bridge_daemon.py`: canal de control migrado de TCP `127.0.0.1:8765` a un
  socket de dominio UNIX (`~/.chatgpt-image-bridge/bridge.sock`, permisos
  `600`) con autenticación por token, para que no sea alcanzable por ningún
  proceso local sin el token.
- `bridge_daemon.py`: serialización de generaciones (una a la vez) y
  limitador de ritmo anti-ráfaga (espaciado con jitter + topes por hora/día),
  configurable por variables de entorno `BRIDGE_*`.
- `native_host/host.py`: lectura exacta de N bytes en el protocolo de native
  messaging (antes vulnerable a lecturas parciales del pipe).
- `extension/background.js`: pestaña dedicada en segundo plano con chat nuevo
  por cada petición, en vez de reutilizar cualquier pestaña de ChatGPT
  abierta (evita inyectar prompts en conversaciones del usuario).
- `extension/content.js`: el prompt se teclea con pausas irregulares en vez
  de pegarse de golpe (anti-ráfaga "lite"; no es evasión de detección).
- Instalado como LaunchAgent de macOS (arranque automático + reinicio si se
  cae).
- Añadida skill de Claude Code (`~/.claude/skills/chatgpt-image-bridge/`) con
  reglas de uso estricto (una imagen a la vez, respetar límites de ritmo, sin
  reintentos en bucle, sin evasión).

## 1.0.0 — 2026-07-24

- Primera versión: extensión Chrome (native messaging) + daemon puente (TCP
  local) + servidor MCP (`generate_chatgpt_image`) para generar imágenes en
  chatgpt.com reutilizando la sesión del navegador del usuario.
