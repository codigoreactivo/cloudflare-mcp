from typing import Literal, Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_account_id, get_cloudflare_client

ZoneStatus = Literal["initializing", "pending", "active", "moved"]
ZoneType = Literal["full", "partial", "secondary", "internal"]


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
    async def create_zone(
        name: str,
        account_id: Optional[str] = None,
        type: ZoneType = "full",
    ) -> dict:
        """Add a domain to Cloudflare as a new zone, returning the nameservers to set at the registrar.

        Creating the zone changes nothing by itself: the domain keeps resolving
        through its current nameservers until they are repointed at the registrar
        to the returned `name_servers`, at which point the zone flips from
        `pending` to `active`.

        Cloudflare does NOT copy the domain's existing DNS records here — this
        API creates an empty zone. Recreate the records with create_dns_record
        BEFORE switching nameservers, or the domain goes dark the moment the
        delegation cuts over.

        Requires a token with Zone:Edit scoped to all zones in the account; a
        token limited to specific zones cannot create new ones. account_id
        defaults to the account the token resolves to.
        """
        client = get_cloudflare_client()
        zone = await client.zones.create(
            account={"id": account_id or await get_account_id()},
            name=name,
            type=type,
        )
        return {
            "id": zone.id,
            "name": zone.name,
            "status": zone.status,
            "name_servers": zone.name_servers,
        }

    @mcp.tool
    async def get_zone(zone_id: str) -> dict:
        """Get details of a single Cloudflare zone (domain) by its zone ID, including activation status and assigned nameservers."""
        client = get_cloudflare_client()
        zone = await client.zones.get(zone_id=zone_id)
        return zone.model_dump()
