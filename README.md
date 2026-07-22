# cloudflare-mcp

Servidor MCP remoto (FastMCP + transporte `streamable-http`) para administrar Cloudflare. Fase 1: módulo `domains` (zonas y registros DNS). Fase 2: módulo `workers` (deploy de Workers y sitios estáticos, rutas/dominios, secrets, KV).

## Estructura

```
cfmcp/
  server.py              # instancia FastMCP + auth (Google OAuth) + registro de tools + ASGI app
  cf_client.py            # AsyncCloudflare client (CLOUDFLARE_API_TOKEN) + resolución de account_id
  domains/
    zones.py              # list_zones, get_zone
    dns_records.py        # list_dns_records, get_dns_record, create_dns_record, update_dns_record, delete_dns_record
  workers/
    scripts.py            # list_workers, get_worker_code, deploy_worker, delete_worker, versiones + rollback
    routing.py            # subdominio workers.dev, rutas por zona, dominios custom directos
    secrets.py            # list/set/delete de secrets por worker
    kv.py                 # namespaces KV + get/put/delete de claves
    assets.py             # deploy_static_site (Workers Static Assets, upload directo)
tests/
requirements.txt
Dockerfile
```

## Autenticación

Google OAuth vía `GoogleProvider` (`fastmcp.server.auth.providers.google`), un `OAuthProxy` completo contra Google — el servidor delega el login a `accounts.google.com` en vez de emitir credenciales propias. Necesario porque la UI de conectores de Claude Desktop / claude.ai **solo acepta OAuth** (no tiene campo para pegar un bearer token estático — confirmado, ver [issue #112](https://github.com/anthropics/claude-ai-mcp/issues/112)).

`GoogleProvider` no tiene allowlist propia — cualquier cuenta de Google podría autenticar. Un `AuthMiddleware` (`_only_allowed_user()` en `cfmcp/server.py`) restringe el acceso a un único email (`ALLOWED_GOOGLE_EMAIL`), verificando el claim `email` (y `email_verified`) del token verificado por Google.

Requiere crear manualmente un OAuth Client en Google Cloud Console (no hay API para esto) — ver [Despliegue en Dokploy](#despliegue-en-dokploy).

**Nota histórica:** un proveedor de password auto-emitido (`PasswordOAuthProvider`) y `GitHubProvider` se probaron antes; se optó por Google porque la fricción de configurar un OAuth Client externo (igual en ambos) se acabó considerando aceptable a cambio de no tener que recordar/recuperar una contraseña compartida.

## Variables de entorno

- `CLOUDFLARE_API_TOKEN` — token de Cloudflare. Fase 1 requería solo `Zone→Zone→Read` y `Zone→DNS→Edit`; los tools de Workers requieren además permisos de cuenta: `Account→Workers Scripts→Edit`, `Account→Workers KV Storage→Edit` y `Zone→Workers Routes→Edit`. Un token solo-zona sigue funcionando para DNS — los tools de Workers fallan con un error claro en vez de romper el arranque.
- `CLOUDFLARE_ACCOUNT_ID` — opcional. Las APIs de Workers son account-scoped; si no se define, se autodescubre cuando el token ve exactamente una cuenta (requiere que el token pueda listar cuentas).
- `MCP_BASE_URL` — URL pública del servidor (ej. `https://cfmcp.clicestrategico.com`), usada para construir las URLs de OAuth.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — credenciales del OAuth Client creado en Google Cloud Console.
- `ALLOWED_GOOGLE_EMAIL` — único email de Google autorizado a autenticar.
- `FASTMCP_HTTP_ALLOWED_HOSTS` / `FASTMCP_HTTP_ALLOWED_ORIGINS` — **obligatorio en producción**, formato lista JSON (ej. `["cfmcp.clicestrategico.com"]`), no un string plano (pydantic-settings lo parsea como JSON y crashea si no lo es). FastMCP bloquea con 421 cualquier Host que no sea loopback por defecto (protección DNS-rebinding).

## Desarrollo local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
CLOUDFLARE_API_TOKEN=xxx MCP_BASE_URL=http://127.0.0.1:8000 MCP_OAUTH_PASSWORD=xxx uvicorn cfmcp.server:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t cloudflare-mcp .
docker run -p 8000:8000 --env-file .env cloudflare-mcp
```

## Despliegue en Dokploy

Va en el proyecto **"Remote MCP"** existente (junto a Namecheap MCP y Google Drive MCP), mismo patrón: repo GitHub + `buildType: dockerfile` + dominio en `*.clicestrategico.com`.

0. Crear el OAuth Client en [Google Cloud Console](https://console.cloud.google.com) (paso manual, sin API): **APIs & Services → OAuth consent screen** (mínimo requerido), luego **Credentials → Create Credentials → OAuth client ID** tipo **Web application**, con redirect URI `https://cfmcp.clicestrategico.com/auth/callback` (default de `GoogleProvider`). Copiar el Client ID y Client secret generados.
1. Crear la app en Dokploy (`application-create`) en el environment de "Remote MCP".
2. Conectar el repo vía `application-saveGitProvider` (no `saveGithubProvider` — esa requiere una GitHub App integration configurada en Dokploy, que no existe aquí; `saveGitProvider` con `customGitUrl` funciona directo contra el repo público) + `saveBuildType(dockerfile)`.
3. Env vars (`CLOUDFLARE_API_TOKEN`, `MCP_BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_GOOGLE_EMAIL`, `FASTMCP_HTTP_ALLOWED_HOSTS`, `FASTMCP_HTTP_ALLOWED_ORIGINS`) vía `application-saveEnvironment`. Los 400 que este endpoint daba eran un bug del bridge OpenAPI de fastmcp en dokploy-mcp (descartaba campos requeridos-pero-nullables enviados como null) — corregido en dokploy-mcp el 2026-07-21; pasar `""` en `buildArgs`/`buildSecrets` siempre funciona.
4. `application-deploy`.
5. `domain-create` con el dominio real (`certificateType: letsencrypt`).

## Tools disponibles

**domains** — `list_zones`, `get_zone`, `list_dns_records`, `get_dns_record`, `create_dns_record`, `update_dns_record`, `delete_dns_record`

**workers** —
- Scripts: `list_workers`, `get_worker_code`, `deploy_worker` (worker de un solo módulo ES desde código fuente), `delete_worker`, `list_worker_versions`, `rollback_worker`
- Routing: `get_workers_subdomain`, `set_worker_subdomain` (workers.dev), `list/create/delete_worker_route` (rutas por zona), `list/attach/detach_worker_domain` (dominios custom directos — Cloudflare crea DNS y certificado solo)
- Secrets: `list_worker_secrets`, `set_worker_secret`, `delete_worker_secret`
- KV: `list_kv_namespaces`, `create/delete_kv_namespace`, `list_kv_keys`, `kv_get`, `kv_put`, `kv_delete`
- Static sites: `deploy_static_site` — sube una web estática ya construida vía Workers Static Assets (manifest con hash `sha256(base64(contenido)+extensión)[:32]`, sesión de upload con JWT propio, deploy con completion JWT). Límite deliberado de 300 archivos / 10 MiB: el contenido viaja como argumentos MCP, no como filesystem. Acepta `worker_code` opcional para poner un Worker delante de los assets (con binding `ASSETS`).

**Dónde termina el MCP y empieza wrangler:** este servidor es remoto — no ve los archivos locales de un proyecto. Workers de un archivo y sitios estáticos pequeños/medianos caben perfecto por MCP; apps con build (Vite/Astro/Next) y `node_modules` se despliegan con `wrangler deploy` local, y este MCP complementa gestionando rutas, dominios, secrets y KV después.

## Tests

```bash
uv run --with fastmcp --with 'cloudflare>=5.4.0,<6' --with pytest python -m pytest tests/
```

Cubren los helpers puros del flujo de assets (algoritmo de hash exacto de Cloudflare, manifest, límites) y dos tests a nivel de wire con `MockTransport`: que el multipart de `deploy_worker` nombra el módulo por filename (así resuelve `main_module`), y el flujo completo de `deploy_static_site` (sesión → upload autenticado con el JWT de sesión y partes por hash → deploy con el completion JWT).

## Roadmap

- Registrar (dominios comprados vía Cloudflare Registrar): listar/consultar, auto_renew/locked/privacy
- Persistencia de clientes/tokens OAuth (SQLite) para sobrevivir restarts
- R2 / D1 bindings
- Cache Purge / reglas WAF
- Workers logs (tail) — es WebSocket, requiere diseño aparte
