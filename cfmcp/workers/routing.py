from typing import Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_account_id, get_cloudflare_client


def register_worker_routing_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_workers_subdomain() -> dict:
        """Get the account's workers.dev subdomain (workers enabled on it are served at <script>.<subdomain>.workers.dev)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        subdomain = await client.workers.subdomains.get(account_id=account_id)
        return subdomain.model_dump(exclude_none=True)

    @mcp.tool
    async def set_worker_subdomain(script_name: str, enabled: bool, previews_enabled: Optional[bool] = None) -> dict:
        """Enable or disable serving a Worker on the account's workers.dev subdomain."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        result = await client.workers.scripts.subdomain.create(
            script_name,
            account_id=account_id,
            enabled=enabled,
            **compact(previews_enabled=previews_enabled),
        )
        return result.model_dump(exclude_none=True)

    @mcp.tool
    async def list_worker_routes(zone_id: str) -> list[dict]:
        """List Worker routes in a zone (pattern -> script mappings on your own domains)."""
        client = get_cloudflare_client()
        routes = []
        async for route in client.workers.routes.list(zone_id=zone_id):
            routes.append(route.model_dump(exclude_none=True))
        return routes

    @mcp.tool
    async def create_worker_route(zone_id: str, pattern: str, script: str) -> dict:
        """Route requests matching a URL pattern (e.g. "api.example.com/*") on a zone to a Worker script. The hostname must resolve through Cloudflare (orange-cloud DNS record)."""
        client = get_cloudflare_client()
        route = await client.workers.routes.create(zone_id=zone_id, pattern=pattern, script=script)
        return route.model_dump(exclude_none=True)

    @mcp.tool
    async def delete_worker_route(zone_id: str, route_id: str) -> dict:
        """Remove a Worker route from a zone."""
        client = get_cloudflare_client()
        await client.workers.routes.delete(route_id, zone_id=zone_id)
        return {"deleted": True, "route_id": route_id}

    @mcp.tool
    async def list_worker_domains() -> list[dict]:
        """List custom domains attached directly to Workers in the account."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        domains = []
        async for domain in client.workers.domains.list(account_id=account_id):
            domains.append(domain.model_dump(exclude_none=True))
        return domains

    @mcp.tool
    async def attach_worker_domain(hostname: str, service: str, zone_id: str, environment: str = "production") -> dict:
        """Attach a custom domain (e.g. app.example.com) directly to a Worker. Cloudflare creates the DNS record and certificate automatically — no route or manual DNS needed."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        domain = await client.workers.domains.update(
            account_id=account_id,
            hostname=hostname,
            service=service,
            zone_id=zone_id,
            environment=environment,
        )
        return domain.model_dump(exclude_none=True)

    @mcp.tool
    async def detach_worker_domain(domain_id: str) -> dict:
        """Detach a custom domain from its Worker (get ids from list_worker_domains)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.workers.domains.delete(domain_id, account_id=account_id)
        return {"detached": True, "domain_id": domain_id}
