from typing import Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_account_id, get_cloudflare_client


def register_r2_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def list_r2_buckets(name_contains: Optional[str] = None) -> list[dict]:
        """List R2 buckets in the account, optionally filtered by a substring of the name."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        response = await client.r2.buckets.list(account_id=account_id, **compact(name_contains=name_contains))
        return [bucket.model_dump(exclude_none=True) for bucket in (response.buckets or [])]

    @mcp.tool
    async def create_r2_bucket(name: str, location_hint: Optional[str] = None) -> dict:
        """Create an R2 bucket. `location_hint` optionally biases where it's created (e.g. "wnam", "eeur", "apac") — Cloudflare still serves it globally."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        bucket = await client.r2.buckets.create(
            account_id=account_id, name=name, **compact(location_hint=location_hint)
        )
        return bucket.model_dump(exclude_none=True)

    @mcp.tool
    async def get_r2_bucket(bucket_name: str) -> dict:
        """Get details of an R2 bucket (location, storage class, creation date)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        bucket = await client.r2.buckets.get(bucket_name, account_id=account_id)
        return bucket.model_dump(exclude_none=True)

    @mcp.tool
    async def delete_r2_bucket(bucket_name: str) -> dict:
        """Delete an R2 bucket. The bucket must be empty first — this does not delete its objects."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.r2.buckets.delete(bucket_name, account_id=account_id)
        return {"deleted": True, "bucket_name": bucket_name}
