from typing import Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_account_id, get_cloudflare_client


def register_worker_kv_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def list_kv_namespaces() -> list[dict]:
        """List Workers KV namespaces in the account."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        namespaces = []
        async for namespace in client.kv.namespaces.list(account_id=account_id):
            namespaces.append(namespace.model_dump(exclude_none=True))
        return namespaces

    @mcp.tool
    async def create_kv_namespace(title: str) -> dict:
        """Create a Workers KV namespace. Use the returned id in a Worker's kv_namespace binding."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        namespace = await client.kv.namespaces.create(account_id=account_id, title=title)
        return namespace.model_dump(exclude_none=True)

    @mcp.tool
    async def delete_kv_namespace(namespace_id: str) -> dict:
        """Delete a Workers KV namespace and all keys in it."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.kv.namespaces.delete(namespace_id, account_id=account_id)
        return {"deleted": True, "namespace_id": namespace_id}

    @mcp.tool
    async def list_kv_keys(namespace_id: str, prefix: Optional[str] = None, limit: int = 100) -> list[dict]:
        """List keys in a KV namespace, optionally filtered by prefix."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        keys = []
        async for key in client.kv.namespaces.keys.list(
            namespace_id, account_id=account_id, **compact(prefix=prefix, limit=limit)
        ):
            keys.append(key.model_dump(exclude_none=True))
            if len(keys) >= limit:
                break
        return keys

    @mcp.tool
    async def kv_get(namespace_id: str, key: str) -> str:
        """Read a value from a KV namespace (returned as text)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        response = await client.kv.namespaces.values.get(
            key, namespace_id=namespace_id, account_id=account_id
        )
        return response.text() if callable(getattr(response, "text", None)) else str(response)

    @mcp.tool
    async def kv_put(
        namespace_id: str,
        key: str,
        value: str,
        expiration_ttl: Optional[int] = None,
    ) -> dict:
        """Write a text value to a KV namespace, optionally expiring after expiration_ttl seconds (min 60)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.kv.namespaces.values.update(
            key,
            namespace_id=namespace_id,
            account_id=account_id,
            value=value,
            **compact(expiration_ttl=expiration_ttl),
        )
        return compact(written=True, namespace_id=namespace_id, key=key, expiration_ttl=expiration_ttl)

    @mcp.tool
    async def kv_delete(namespace_id: str, key: str) -> dict:
        """Delete a key from a KV namespace."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.kv.namespaces.values.delete(
            key, namespace_id=namespace_id, account_id=account_id
        )
        return {"deleted": True, "namespace_id": namespace_id, "key": key}
