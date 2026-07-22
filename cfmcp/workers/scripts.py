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

    @mcp.tool
    async def list_worker_deployments(script_name: str) -> list[dict]:
        """List a Worker's deployment history (newest first): each entry shows which version(s)
        are live and the traffic split between them (e.g. a canary at 10%/90%), when it was
        deployed, and by whom. This is the "what's actually running right now" view — distinct
        from list_worker_versions, which only lists stored versions without deployment/traffic state.
        """
        client = get_cloudflare_client()
        account_id = await get_account_id()
        response = await client.workers.scripts.deployments.list(script_name, account_id=account_id)
        return [deployment.model_dump(exclude_none=True) for deployment in response.deployments]

    @mcp.tool
    async def get_worker_deployment(script_name: str, deployment_id: str) -> dict:
        """Get full detail on one Worker deployment by id (from list_worker_deployments)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        deployment = await client.workers.scripts.deployments.get(
            deployment_id, script_name=script_name, account_id=account_id
        )
        return deployment.model_dump(exclude_none=True)

    @mcp.tool
    async def create_worker_version(
        script_name: str,
        code: str,
        compatibility_date: Optional[str] = None,
        compatibility_flags: Optional[list[str]] = None,
        bindings: Optional[list[dict]] = None,
    ) -> dict:
        """Stage a new version of a Worker WITHOUT routing any traffic to it — same parameters as
        deploy_worker, but nothing goes live. Use this to test a change safely: stage it here, then
        use set_worker_traffic_split to send it a small percentage of traffic (canary), and once
        confident, rollback_worker (or another set_worker_traffic_split call) to send it 100%.
        """
        client = get_cloudflare_client()
        account_id = await get_account_id()
        metadata = compact(
            main_module="worker.js",
            compatibility_date=compatibility_date or DEFAULT_COMPATIBILITY_DATE,
            compatibility_flags=compatibility_flags,
            bindings=bindings,
        )
        result = await client.workers.scripts.versions.create(
            script_name,
            account_id=account_id,
            metadata=metadata,
            files=[("worker.js", code.encode(), "application/javascript+module")],
        )
        return result.model_dump(exclude_none=True)

    @mcp.tool
    async def set_worker_traffic_split(script_name: str, versions: list[dict]) -> dict:
        """Split a Worker's live traffic across two or more versions for a gradual/canary rollout.

        `versions` is a list of {"version_id": ..., "percentage": ...} and must sum to 100, e.g.
        [{"version_id": "new", "percentage": 10}, {"version_id": "old", "percentage": 90}].
        Get version ids from list_worker_versions or create_worker_version. For the common case of
        sending 100% to a single version, use rollback_worker instead — it's the same underlying
        call with less to get wrong.
        """
        client = get_cloudflare_client()
        account_id = await get_account_id()
        deployment = await client.workers.scripts.deployments.create(
            script_name,
            account_id=account_id,
            strategy="percentage",
            versions=versions,
        )
        return deployment.model_dump(exclude_none=True)

    @mcp.tool
    async def get_worker_schedules(script_name: str) -> list[dict]:
        """List a Worker's Cron Triggers (scheduled executions, e.g. "0 0 * * *" for daily at midnight)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        response = await client.workers.scripts.schedules.get(script_name, account_id=account_id)
        return [schedule.model_dump(exclude_none=True) for schedule in (response.schedules or [])]

    @mcp.tool
    async def set_worker_schedules(script_name: str, crons: list[str]) -> list[dict]:
        """Replace a Worker's full set of Cron Triggers with `crons` (standard cron expressions,
        e.g. ["0 0 * * *", "0 */6 * * *"]). This is a full replace, not an add — pass all schedules
        you want to keep, or an empty list to remove all of them.
        """
        client = get_cloudflare_client()
        account_id = await get_account_id()
        response = await client.workers.scripts.schedules.update(
            script_name, account_id=account_id, body=[{"cron": cron} for cron in crons]
        )
        return [schedule.model_dump(exclude_none=True) for schedule in (response.schedules or [])]
