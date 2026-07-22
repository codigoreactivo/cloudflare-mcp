from typing import Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_account_id, get_cloudflare_client

# A stable default so deploys are reproducible; callers can override per deploy.
# Bump deliberately when you want new runtime behavior, the same way wrangler
# projects pin compatibility_date in wrangler.toml.
DEFAULT_COMPATIBILITY_DATE = "2026-07-01"


def register_worker_script_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def list_workers() -> list[dict]:
        """List all Workers scripts in the account, with their modification dates and deployment metadata."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        scripts = []
        async for script in client.workers.scripts.list(account_id=account_id):
            scripts.append(
                compact(
                    id=script.id,
                    created_on=str(script.created_on) if script.created_on else None,
                    modified_on=str(script.modified_on) if script.modified_on else None,
                    logpush=getattr(script, "logpush", None),
                    placement_mode=getattr(script, "placement_mode", None),
                )
            )
        return scripts

    @mcp.tool
    async def get_worker_code(script_name: str) -> str:
        """Download the deployed source code of a Worker script."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        response = await client.workers.scripts.get(script_name, account_id=account_id)
        return response.text() if callable(getattr(response, "text", None)) else str(response)

    @mcp.tool
    async def deploy_worker(
        script_name: str,
        code: str,
        compatibility_date: Optional[str] = None,
        compatibility_flags: Optional[list[str]] = None,
        bindings: Optional[list[dict]] = None,
    ) -> dict:
        """Deploy (create or update) a single-module ES Worker from source code.

        `code` is the full JavaScript module source (must have an `export default`
        with a fetch handler). `bindings` uses Cloudflare's binding JSON as-is,
        e.g. [{"type": "kv_namespace", "name": "MY_KV", "namespace_id": "..."}]
        or [{"type": "plain_text", "name": "MY_VAR", "text": "value"}].
        For larger apps with a build step, use wrangler locally instead — this
        tool is for single-file workers deployed conversationally.
        """
        client = get_cloudflare_client()
        account_id = await get_account_id()
        metadata = compact(
            main_module="worker.js",
            compatibility_date=compatibility_date or DEFAULT_COMPATIBILITY_DATE,
            compatibility_flags=compatibility_flags,
            bindings=bindings,
        )
        result = await client.workers.scripts.update(
            script_name,
            account_id=account_id,
            metadata=metadata,
            files=[("worker.js", code.encode(), "application/javascript+module")],
        )
        return result.model_dump(exclude_none=True)

    @mcp.tool
    async def delete_worker(script_name: str, force: bool = False) -> dict:
        """Delete a Worker script. Set force=true to also remove it when it still has bound resources (routes, domains)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.workers.scripts.delete(script_name, account_id=account_id, force=force)
        return {"deleted": True, "script_name": script_name}

    @mcp.tool
    async def list_worker_versions(script_name: str) -> list[dict]:
        """List the stored versions of a Worker script (newest first), for inspection or rollback."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        versions = []
        async for version in client.workers.scripts.versions.list(
            script_name, account_id=account_id
        ):
            versions.append(version.model_dump(exclude_none=True))
        return versions

    @mcp.tool
    async def rollback_worker(script_name: str, version_id: str) -> dict:
        """Point 100% of a Worker's traffic at an existing version (rollback / roll-forward). Get version ids from list_worker_versions."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        deployment = await client.workers.scripts.deployments.create(
            script_name,
            account_id=account_id,
            strategy="percentage",
            versions=[{"percentage": 100, "version_id": version_id}],
        )
        return deployment.model_dump(exclude_none=True)
