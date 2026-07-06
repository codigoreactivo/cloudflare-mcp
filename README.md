# cloudflare-mcp

Servidor MCP remoto (FastMCP + transporte `streamable-http`) para administrar Cloudflare. Fase 1: módulo `domains` (zonas y registros DNS).

## Estructura

```
cfmcp/
  server.py              # instancia FastMCP + auth (GitHubProvider) + registro de tools + ASGI app
  cf_client.py            # AsyncCloudflare client (lee CLOUDFLARE_API_TOKEN)
  domains/
    zones.py              # list_zones, get_zone
    dns_records.py        # list_dns_records, get_dns_record, create_dns_record, update_dns_record, delete_dns_record
requirements.txt
Dockerfile
```

## Autenticación

OAuth 2.1 vía `GitHubProvider` de FastMCP (`fastmcp.server.auth.providers.github`) — el camino que la propia documentación de FastMCP recomienda para producción (ver [gofastmcp.com/servers/auth/authentication](https://gofastmcp.com/servers/auth/authentication): *"Full OAuth implementation should be avoided unless you have compelling reasons that external providers cannot address"*). Necesario porque la UI de conectores de Claude Desktop / claude.ai **solo acepta OAuth** (no tiene campo para bearer token estático — ver [issue #112](https://github.com/anthropics/claude-ai-mcp/issues/112)).

`GitHubProvider` es un `OAuthProxy`: hace de puente entre GitHub (que no soporta Dynamic Client Registration) y clientes MCP como Claude Desktop (que sí la requieren) — incluye la pantalla de consentimiento nativa de FastMCP (`ConsentMixin`). Un `AuthMiddleware` adicional restringe el acceso a un único usuario de GitHub (`ALLOWED_GITHUB_LOGIN`) comparando `token.claims["login"]`, ya que `GitHubProvider` no trae esa restricción integrada.

**Limitación conocida (v1):** el registro de clientes OAuth (`client_storage`) vive en un archivo local dentro del contenedor (sin volumen persistente) — un restart/redeploy borra los clientes/tokens registrados y Claude Desktop necesita reconectar. Mejora futura: montar un volumen persistente.

## Crear la GitHub OAuth App

1. GitHub → Settings → Developer settings → OAuth Apps → New OAuth App.
2. Homepage URL: `https://cfmcp.clicestrategico.com`
3. Authorization callback URL: `https://cfmcp.clicestrategico.com/auth/callback` (path por defecto de `GitHubProvider`)
4. Generar el Client Secret y guardar ambos valores.

## Variables de entorno

- `CLOUDFLARE_API_TOKEN` — token de Cloudflare con `Zone→Zone→Read` y `Zone→DNS→Edit`, scoped a zonas específicas.
- `MCP_BASE_URL` — URL pública del servidor (ej. `https://cfmcp.clicestrategico.com`), debe coincidir con la callback URL registrada en GitHub.
- `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` — de la GitHub OAuth App.
- `ALLOWED_GITHUB_LOGIN` — único username de GitHub autorizado a usar el servidor.
- `FASTMCP_HTTP_ALLOWED_HOSTS` / `FASTMCP_HTTP_ALLOWED_ORIGINS` — **obligatorio en producción**, formato lista JSON (ej. `["cfmcp.clicestrategico.com"]`). FastMCP bloquea con 421 cualquier Host que no sea loopback por defecto (protección DNS-rebinding).

## Desarrollo local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
CLOUDFLARE_API_TOKEN=xxx MCP_BASE_URL=http://127.0.0.1:8000 GITHUB_CLIENT_ID=xxx GITHUB_CLIENT_SECRET=xxx ALLOWED_GITHUB_LOGIN=tu-usuario uvicorn cfmcp.server:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t cloudflare-mcp .
docker run -p 8000:8000 --env-file .env cloudflare-mcp
```

## Despliegue en Dokploy

Va en el proyecto **"Remote MCP"** existente (junto a Namecheap MCP y Google Drive MCP), mismo patrón: repo GitHub + `buildType: dockerfile` + dominio en `*.clicestrategico.com`.

1. Crear la app en Dokploy (`application-create`) en el environment de "Remote MCP".
2. Conectar el repo vía `application-saveGitProvider` (no `saveGithubProvider` — esa requiere una GitHub App integration configurada en Dokploy, que no existe aquí; `saveGitProvider` con `customGitUrl` funciona directo contra el repo público).
3. `application-saveBuildType(dockerfile)`.
4. Env vars vía la UI de Dokploy (el endpoint `application-saveEnvironment` de la API falló consistentemente con 400 al llamarlo programáticamente — pegar manualmente en Environment funciona bien).
5. `application-deploy`.
6. `domain-create` con el dominio real (`certificateType: letsencrypt`).

## Tools disponibles (módulo domains)

- `list_zones`, `get_zone`
- `list_dns_records`, `get_dns_record`, `create_dns_record`, `update_dns_record`, `delete_dns_record`

## Roadmap

- Registrar (dominios comprados vía Cloudflare Registrar): listar/consultar, auto_renew/locked/privacy
- Volumen persistente para el client_storage de OAuth
- Workers Bindings (KV, R2, D1)
- Cache Purge / reglas WAF
- Pages
