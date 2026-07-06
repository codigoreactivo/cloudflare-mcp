# cloudflare-mcp

Servidor MCP remoto (FastMCP + transporte `streamable-http`) para administrar Cloudflare. Fase 1: módulo `domains` (zonas y registros DNS).

## Estructura

```
cfmcp/
  server.py              # instancia FastMCP + auth + registro de tools + ASGI app
  oauth.py                # proveedor OAuth 2.1 propio (password-gated, sin GitHub/Google)
  cf_client.py            # AsyncCloudflare client (lee CLOUDFLARE_API_TOKEN)
  domains/
    zones.py              # list_zones, get_zone
    dns_records.py        # list_dns_records, get_dns_record, create_dns_record, update_dns_record, delete_dns_record
requirements.txt
Dockerfile
```

## Autenticación

OAuth 2.1 propio (`cfmcp/oauth.py`), sin proveedor de identidad de terceros (no GitHub/Google): el servidor actúa como su propio authorization server. Necesario porque la UI de conectores de Claude Desktop / claude.ai **solo acepta OAuth** (no tiene campo para pegar un bearer token estático — confirmado, ver [issue #112](https://github.com/anthropics/claude-ai-mcp/issues/112)).

Funcionamiento: `authorize()` no auto-aprueba (a diferencia de `InMemoryOAuthProvider`, que es solo para testing y aprueba a cualquiera) — redirige a una página `/login` propia que pide `MCP_OAUTH_PASSWORD`. Solo con la contraseña correcta se emite el código de autorización real. Incluye backoff exponencial tras 3 intentos fallidos. El resto del flujo (DCR, PKCE, emisión/refresh de tokens) reutiliza la lógica ya correcta de `InMemoryOAuthProvider`.

Probado end-to-end con un cliente OAuth simulado: discovery, DCR, `/authorize` → `/login`, contraseña incorrecta → 401, contraseña correcta → código de un solo uso, intercambio de token con PKCE, llamada a `/mcp` sin token → 401 + `WWW-Authenticate`, con token → 200.

**Limitación conocida (v1):** clientes y tokens registrados viven en memoria — un restart del proceso invalida sesiones OAuth existentes (Claude Desktop solo necesita reconectar). Mejora futura: persistencia en SQLite.

## Variables de entorno

- `CLOUDFLARE_API_TOKEN` — token de Cloudflare con `Zone→Zone→Read` y `Zone→DNS→Edit`, scoped a zonas específicas.
- `MCP_BASE_URL` — URL pública del servidor (ej. `https://cfmcp.clicestrategico.com`), usada para construir las URLs de OAuth.
- `MCP_OAUTH_PASSWORD` — contraseña que protege el login OAuth. Usar un secreto largo generado (ej. `openssl rand -base64 32`), no un PIN memorizable.
- `FASTMCP_HTTP_ALLOWED_HOSTS` / `FASTMCP_HTTP_ALLOWED_ORIGINS` — **obligatorio en producción**: FastMCP bloquea con 421 cualquier Host que no sea loopback por defecto (protección DNS-rebinding). Debe incluir el dominio público real (ver `.env.example`).

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

1. Crear la app en Dokploy (`application-create`) en el environment de "Remote MCP".
2. Conectar el repo vía `saveGitProvider`/`saveGithubProvider` + `saveBuildType(dockerfile)`.
3. `application-saveEnvironment` con `CLOUDFLARE_API_TOKEN`, `MCP_BASE_URL`, `MCP_OAUTH_PASSWORD`, `FASTMCP_HTTP_ALLOWED_HOSTS`, `FASTMCP_HTTP_ALLOWED_ORIGINS`.
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
