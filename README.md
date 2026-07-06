# cloudflare-mcp

Servidor MCP remoto (FastMCP + transporte `streamable-http`) para administrar Cloudflare. Fase 1: módulo `domains` (zonas y registros DNS).

## Estructura

```
cfmcp/
  server.py              # instancia FastMCP + auth + registro de tools + ASGI app
  cf_client.py            # AsyncCloudflare client (lee CLOUDFLARE_API_TOKEN)
  domains/
    zones.py              # list_zones, get_zone
    dns_records.py        # list_dns_records, get_dns_record, create_dns_record, update_dns_record, delete_dns_record
requirements.txt
Dockerfile
```

## Variables de entorno

- `CLOUDFLARE_API_TOKEN` — token de Cloudflare con `Zone→Zone→Read` y `Zone→DNS→Edit`, scoped a zonas específicas.
- `MCP_ACCESS_TOKEN` — secreto propio que protege el endpoint remoto (bearer token). Obligatorio: el servidor no arranca sin él.

## Desarrollo local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
CLOUDFLARE_API_TOKEN=xxx MCP_ACCESS_TOKEN=xxx uvicorn cfmcp.server:app --host 0.0.0.0 --port 8000
```

Probado end-to-end: sin header `Authorization` → 401; token incorrecto → 401; token correcto → handshake MCP completo sobre `streamable-http` en `/mcp`.

## Docker

```bash
docker build -t cloudflare-mcp .
docker run -p 8000:8000 -e CLOUDFLARE_API_TOKEN=xxx -e MCP_ACCESS_TOKEN=xxx cloudflare-mcp
```

## Despliegue en Dokploy

`saveDockerProvider` de Dokploy solo referencia una imagen ya publicada en un registry (no construye desde un Dockerfile local sin git). Pasos:

1. `docker build` + `docker push` a un registry (Docker Hub / GHCR).
2. Crear la app en Dokploy (`application-create`) dentro de un proyecto/environment.
3. `application-saveDockerProvider` apuntando a la imagen publicada.
4. `application-saveEnvironment` con `CLOUDFLARE_API_TOKEN` y `MCP_ACCESS_TOKEN`.
5. `application-deploy`.
6. `domain-create` con el dominio propio (o `domain-generateDomain` para probar rápido con un subdominio traefik.me).

Alternativa: conectar un repo git (GitHub/otro) vía `saveGithubProvider`/`saveGitProvider` + `saveBuildType(dockerfile)` para que Dokploy construya la imagen él mismo, sin necesitar un registry externo.

## Tools disponibles (módulo domains)

- `list_zones`, `get_zone`
- `list_dns_records`, `get_dns_record`, `create_dns_record`, `update_dns_record`, `delete_dns_record`

## Roadmap

- Registrar (dominios comprados vía Cloudflare Registrar): listar/consultar, auto_renew/locked/privacy
- Workers Bindings (KV, R2, D1)
- Cache Purge / reglas WAF
- Pages
