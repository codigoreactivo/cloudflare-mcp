from typing import Literal, Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_cloudflare_client

RecordType = Literal["A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA", "PTR"]


def register_dns_record_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def list_dns_records(
        zone_id: str, type: Optional[RecordType] = None, name: Optional[str] = None
    ) -> list[dict]:
        """List DNS records in a Cloudflare zone, optionally filtered by type and/or exact name."""
        client = get_cloudflare_client()
        records = []
        async for record in client.dns.records.list(zone_id=zone_id, **compact(type=type, name=name)):
            records.append(record.model_dump())
        return records

    @mcp.tool
    async def get_dns_record(zone_id: str, record_id: str) -> dict:
        """Get a single DNS record by its ID within a zone."""
        client = get_cloudflare_client()
        record = await client.dns.records.get(record_id, zone_id=zone_id)
        return record.model_dump()

    @mcp.tool
    async def create_dns_record(
        zone_id: str,
        type: RecordType,
        name: str,
        content: Optional[str] = None,
        ttl: Optional[int] = None,
        proxied: Optional[bool] = None,
        priority: Optional[int] = None,
        comment: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """Create a new DNS record in a Cloudflare zone."""
        client = get_cloudflare_client()
        record = await client.dns.records.create(
            zone_id=zone_id,
            type=type,
            name=name,
            ttl=ttl or 1,
            **compact(content=content, proxied=proxied, priority=priority, comment=comment, tags=tags),
        )
        return record.model_dump()

    @mcp.tool
    async def update_dns_record(
        zone_id: str,
        record_id: str,
        type: Optional[RecordType] = None,
        name: Optional[str] = None,
        content: Optional[str] = None,
        ttl: Optional[int] = None,
        proxied: Optional[bool] = None,
        priority: Optional[int] = None,
        comment: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """Update fields of an existing DNS record. Only the provided fields are changed; the rest keep their current value."""
        client = get_cloudflare_client()
        current = await client.dns.records.get(record_id, zone_id=zone_id)
        record = await client.dns.records.edit(
            record_id,
            zone_id=zone_id,
            type=type or current.type,
            name=name or current.name,
            ttl=ttl or current.ttl,
            **compact(
                content=content if content is not None else current.content,
                proxied=proxied if proxied is not None else getattr(current, "proxied", None),
                priority=priority if priority is not None else getattr(current, "priority", None),
                comment=comment if comment is not None else getattr(current, "comment", None),
                tags=tags if tags is not None else getattr(current, "tags", None),
            ),
        )
        return record.model_dump()

    @mcp.tool
    async def delete_dns_record(zone_id: str, record_id: str) -> dict:
        """Delete a DNS record from a Cloudflare zone."""
        client = get_cloudflare_client()
        result = await client.dns.records.delete(record_id, zone_id=zone_id)
        return result.model_dump() if result is not None else {"deleted": True, "id": record_id}
