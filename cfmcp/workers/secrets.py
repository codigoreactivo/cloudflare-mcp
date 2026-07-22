from fastmcp import FastMCP

from cfmcp.cf_client import get_account_id, get_cloudflare_client


def register_worker_secret_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def list_worker_secrets(script_name: str) -> list[dict]:
        """List the names of secrets bound to a Worker (values are write-only and never returned by Cloudflare)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        secrets = []
        async for secret in client.workers.scripts.secrets.list(
            script_name, account_id=account_id
        ):
            secrets.append(secret.model_dump(exclude_none=True))
        return secrets

    @mcp.tool
    async def set_worker_secret(script_name: str, name: str, value: str) -> dict:
        """Create or update a secret on a Worker. Takes effect immediately without redeploying the script."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        result = await client.workers.scripts.secrets.update(
            script_name,
            account_id=account_id,
            name=name,
            text=value,
            type="secret_text",
        )
        return result.model_dump(exclude_none=True)

    @mcp.tool
    async def delete_worker_secret(script_name: str, name: str) -> dict:
        """Delete a secret from a Worker."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.workers.scripts.secrets.delete(
            name, script_name=script_name, account_id=account_id
        )
        return {"deleted": True, "script_name": script_name, "secret": name}
