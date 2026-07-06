from typing import Literal, Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_cloudflare_client

ZoneStatus = Literal["initializing", "pending", "active", "moved"]


def register_zone_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def list_zones(name: Optional[str] = None, status: Optional[ZoneStatus] = None) -> list[dict]:
        """List Cloudflare zones (domains) in the account, optionally filtered by exact name or status."""
        client = get_cloudflare_client()
        zones = []
        async for zone in client.zones.list(**compact(name=name, status=status)):
            zones.append(
                {
                    "id": zone.id,
                    "name": zone.name,
                    "status": zone.status,
                    "name_servers": zone.name_servers,
                }
            )
        return zones

    @mcp.tool
    async def get_zone(zone_id: str) -> dict:
        """Get details of a single Cloudflare zone (domain) by its zone ID, including activation status and assigned nameservers."""
        client = get_cloudflare_client()
        zone = await client.zones.get(zone_id=zone_id)
        return zone.model_dump()
