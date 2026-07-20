# cloudflare-mcp

Servidor MCP remoto (FastMCP + transporte `streamable-http`) para administrar Cloudflare. Fase 1: módulo `domains` (zonas y registros DNS).

## Estructura

```
cfmcp/
  server.py              # instancia FastMCP + auth (Google OAuth) + registro de tools + ASGI app
  cf_client.py            # AsyncCloudflare client (lee CLOUDFLARE_API_TOKEN)
  domains/
    zones.py              # list_zones, get_zone
    dns_records.py        # list_dns_records, get_dns_record, create_dns_record, update_dns_record, delete_dns_record
requirements.txt
Dockerfile
```

## Autenticación

Google OAuth vía `GoogleProvider` (`fastmcp.server.auth.providers.google`), un `OAuthProxy` completo contra Google — el servidor delega el login a `accounts.google.com` en vez de emitir credenciales propias. Necesario porque la UI de conectores de Claude Desktop / claude.ai **solo acepta OAuth** (no tiene campo para pegar un bearer token estático — confirmado, ver [issue #112](https://github.com/anthropics/claude-ai-mcp/issues/112)).

`GoogleProvider` no tiene allowlist propia — cualquier cuenta de Google podría autenticar. Un `AuthMiddleware` (`_only_allowed_user()` en `cfmcp/server.py`) restringe el acceso a un único email (`ALLOWED_GOOGLE_EMAIL`), verificando el claim `email` (y `email_verified`) del token verificado por Google.

Requiere crear manualmente un OAuth Client en Google Cloud Console (no hay API para esto) — ver [Despliegue en Dokploy](#despliegue-en-dokploy).

**Nota histórica:** un proveedor de password auto-emitido (`PasswordOAuthProvider`) y `GitHubProvider` se probaron antes; se optó por Google porque la fricción de configurar un OAuth Client externo (igual en ambos) se acabó considerando aceptable a cambio de no tener que recordar/recuperar una contraseña compartida.

## Variables de entorno

- `CLOUDFLARE_API_TOKEN` — token de Cloudflare con `Zone→Zone→Read` y `Zone→DNS→Edit`, scoped a zonas específicas.
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
3. Env vars (`CLOUDFLARE_API_TOKEN`, `MCP_BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_GOOGLE_EMAIL`, `FASTMCP_HTTP_ALLOWED_HOSTS`, `FASTMCP_HTTP_ALLOWED_ORIGINS`) vía la UI de Dokploy — el endpoint `application-saveEnvironment` de la API falló consistentemente con 400 al llamarlo programáticamente.
4. `application-deploy`.
5. `domain-create` con el dominio real (`certificateType: letsencrypt`).

## Tools disponibles (módulo domains)

- `list_zones`, `get_zone`
- `list_dns_records`, `get_dns_record`, `create_dns_record`, `update_dns_record`, `delete_dns_record`

## Roadmap

- Registrar (dominios comprados vía Cloudflare Registrar): listar/consultar, auto_renew/locked/privacy
- Persistencia de clientes/tokens OAuth (SQLite) para sobrevivir restarts
- Workers Bindings (KV, R2, D1)
- Cache Purge / reglas WAF
- Pages
