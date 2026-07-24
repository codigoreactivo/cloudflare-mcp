# Changelog

Todas las versiones se refieren a `extension/version` en `extension/manifest.json`.
El backend (`bridge_daemon.py`, `native_host/`, `mcp_server/`) no tiene versión
propia; sus cambios se listan aquí igual, marcados como tal.

## 1.1.3 — 2026-07-24

### Extensión (`extension/content.js`)

- **Fix crítico: selector de mensaje del asistente obsoleto.**
  `[data-message-author-role="assistant"]` solo existe en el DOM de
  chatgpt.com mientras el mensaje está en streaming activo; una vez la
  conversación se asienta (idle), el atributo desaparece por completo
  (verificado en vivo: 0 coincidencias en una conversación ya completada,
  incluida una con imagen generada y visible). Por eso, tras el fix de 1.1.1
  (pestaña activa), la generación dejó de colgarse pero empezó a fallar con
  "No se encontró el mensaje del asistente" — el margen de 1s tras detectar
  el fin de generación era suficiente para que la conversación ya se hubiera
  asentado y el selector dejara de matchear.
  - Fix: nuevo selector estable `[data-testid^="conversation-turn-N"]`
    (un `<section>` por turno), confirmado que persiste en el estado final.
    Los turnos alternan usuario/asistente en orden estricto, así que el
    último turno del DOM es siempre la respuesta más reciente.
  - Se ajustó también la espera inicial para exigir 2 turnos nuevos (el eco
    del propio prompt del usuario + la respuesta del asistente), no solo 1,
    evitando adelantarse a un estado donde solo existe el eco del usuario.
  - Verificado en vivo contra una conversación real con imagen generada
    (1254×1254, `complete: true`): el nuevo selector encuentra el turno
    correcto y la imagen.

## 1.1.2 — 2026-07-24

### Extensión (`extension/background.js`)

- **Fix: ya no se reutilizan pestañas entre peticiones.** Con el fix de
  1.1.1 (pestaña activa), reutilizar la misma pestaña dedicada entre
  peticiones exponía otro problema: si pasaba suficiente tiempo, el
  navegador podía "descargarla" de memoria (`discard`, para ahorrar RAM), y
  reactivarla disparaba una recarga implícita que se solapaba con la
  navegación propia del código, dejando el DOM a medias justo cuando
  `content.js` intentaba leer el mensaje generado. Visto en vivo: error
  "No se encontró el mensaje del asistente" con el mensaje ya borrado del
  DOM, en vez del timeout de antes. Ahora cada petición cierra la pestaña
  dedicada anterior (si existe) y crea una nueva; se eliminó también la
  navegación duplicada (`openFreshChat`) que ya no hacía falta.

## 1.1.1 — 2026-07-24

### Extensión (`extension/background.js`)

- **Fix crítico: la pestaña dedicada ahora se mantiene ACTIVA (primer plano)
  durante toda la generación**, en vez de en segundo plano. Diagnosticado en
  vivo con la cuenta real del usuario en Brave: `generate_chatgpt_image`
  colgaba siempre hasta el timeout completo (180s) aunque ChatGPT sí generaba
  la imagen correctamente.
  - Causa raíz #1 (confirmada empíricamente): Chrome/Brave detienen o
    retrasan severamente los timers (`setTimeout`) de una pestaña oculta —un
    `setTimeout` de 2s no se disparó ni una sola vez en 40s reales de
    background—, y `content.js` depende de sondear el DOM con `setTimeout`
    para detectar cuándo termina la generación.
  - Causa raíz #2 (confirmada empíricamente): con la pestaña oculta, las
    `<img>` generadas tienen el `src` correcto pero `naturalWidth: 0`
    indefinidamente (el navegador difiere la descarga/decode de imágenes en
    pestañas no visibles), así que aunque el polling funcionara, el filtro
    `naturalWidth > 64` de `content.js` tampoco encontraría nada.
  - Fix: `chrome.tabs.create`/`chrome.tabs.update` ahora usan `active: true`,
    y se añadió `chrome.windows.update({focused: true})` para asegurar que
    también la VENTANA contenedora tenga foco (la visibilidad de página en
    Chromium depende de ambas cosas). Costo de UX: la pestaña salta al frente
    durante cada generación — mismo comportamiento que Claude in Chrome.
- Dato adicional del diagnóstico: la URL de la imagen generada resultó ser
  same-origin (`chatgpt.com/backend-api/estuary/content?id=...`), no un CDN
  de terceros — así que el riesgo de CORS señalado en la revisión de 1.1.0
  aplica solo si OpenAI cambia esa infraestructura, no en el caso típico
  observado.

### Backend (`bridge_daemon.py`)

- **Fix: conexiones de extensión huérfanas.** El daemon solo trackeaba una
  "extensión actual"; al llegar una conexión nueva (segundo navegador,
  recarga de la extensión, reinicio del daemon) simplemente sobrescribía la
  referencia sin cerrar la anterior, dejándola conectada a nivel de socket
  pero inalcanzable para futuras peticiones. Reproducido y verificado en vivo
  (evidencia: una conexión real de Brave quedó huérfana durante las pruebas
  de esta misma versión). Ahora, al llegar una conexión nueva, se cierra
  explícitamente la anterior antes de empezar a trackear la nueva.

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
