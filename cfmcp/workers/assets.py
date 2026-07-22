"""Deploy static sites to Workers via the Static Assets direct-upload API.

Flow (mirrors what wrangler does under the hood, per
https://developers.cloudflare.com/workers/static-assets/direct-upload/):
1. Build a manifest {path: {hash, size}} — hash is sha256(base64(content) +
   file extension) hex, truncated to 32 chars. Cloudflare dedupes by hash:
   the upload session only asks for files it doesn't already have.
2. POST the manifest to assets-upload-session → a session JWT plus "buckets"
   of hashes to upload (empty buckets = everything already stored).
3. Upload each bucket as multipart/form-data (field name = hash, body =
   base64 content) authenticated with the session JWT — NOT the API token.
   The last upload response returns the completion JWT.
4. Deploy the script with metadata.assets = {jwt: completion, config}.

This tool targets already-built small/medium sites (landing pages, docs,
HTML+CSS+JS). Apps that need a build step should use wrangler locally — the
content here travels through MCP tool arguments, so size limits are enforced.
"""

import base64
import hashlib
import mimetypes
import os
from typing import Optional

import httpx
from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_account_id, get_cloudflare_client
from cfmcp.workers.scripts import DEFAULT_COMPATIBILITY_DATE

CF_API_BASE = "https://api.cloudflare.com/client/v4"
MAX_TOTAL_BYTES = 10 * 1024 * 1024  # keep well under MCP message-size practicality
MAX_FILES = 300

# Test seam: the JWT-authenticated batch upload can't go through the SDK client
# (different auth), so it builds its own httpx client here. Tests set this to an
# httpx.MockTransport to intercept those requests; None means real network.
_TRANSPORT: Optional[httpx.AsyncBaseTransport] = None


def normalize_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def asset_hash(content: bytes, path: str) -> str:
    """Cloudflare's asset content hash: sha256 of (base64(content) + extension), first 32 hex chars."""
    extension = os.path.splitext(path)[1]
    digest = hashlib.sha256(base64.b64encode(content) + extension.encode()).hexdigest()
    return digest[:32]


def build_manifest(files: dict[str, bytes]) -> dict[str, dict]:
    return {
        path: {"hash": asset_hash(content, path), "size": len(content)}
        for path, content in files.items()
    }


def decode_input_files(
    files: Optional[dict[str, str]], files_base64: Optional[dict[str, str]]
) -> dict[str, bytes]:
    decoded: dict[str, bytes] = {}
    for path, text in (files or {}).items():
        decoded[normalize_path(path)] = text.encode()
    for path, b64 in (files_base64 or {}).items():
        decoded[normalize_path(path)] = base64.b64decode(b64)
    if not decoded:
        raise ValueError("No files provided. Pass text files in `files` and/or binaries in `files_base64`.")
    if len(decoded) > MAX_FILES:
        raise ValueError(f"{len(decoded)} files exceeds the limit of {MAX_FILES} for MCP deploys; use wrangler locally.")
    total = sum(len(c) for c in decoded.values())
    if total > MAX_TOTAL_BYTES:
        raise ValueError(
            f"Total size {total} bytes exceeds the {MAX_TOTAL_BYTES}-byte limit for MCP deploys; use wrangler locally."
        )
    return decoded


async def upload_buckets(
    account_id: str, session_jwt: str, buckets: list[list[str]], by_hash: dict[str, tuple[str, bytes]]
) -> str:
    """Upload each bucket of hashes with the session JWT; return the completion JWT."""
    completion_jwt = session_jwt  # if buckets are empty, the session JWT already is the completion token
    async with httpx.AsyncClient(base_url=CF_API_BASE, timeout=120, transport=_TRANSPORT) as http:
        for bucket in buckets:
            parts = []
            for file_hash in bucket:
                path, content = by_hash[file_hash]
                content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
                parts.append((file_hash, (file_hash, base64.b64encode(content), content_type)))
            response = await http.post(
                f"/accounts/{account_id}/workers/assets/upload",
                params={"base64": "true"},
                headers={"Authorization": f"Bearer {session_jwt}"},
                files=parts,
            )
            response.raise_for_status()
            jwt = (response.json().get("result") or {}).get("jwt")
            if jwt:
                completion_jwt = jwt
    return completion_jwt


def register_worker_asset_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def deploy_static_site(
        script_name: str,
        files: Optional[dict[str, str]] = None,
        files_base64: Optional[dict[str, str]] = None,
        html_handling: Optional[str] = None,
        not_found_handling: Optional[str] = None,
        worker_code: Optional[str] = None,
        compatibility_date: Optional[str] = None,
    ) -> dict:
        """Deploy a static website to a Worker using Workers Static Assets.

        `files` maps paths to text content ({"/index.html": "<html>..."}),
        `files_base64` maps paths to base64 content for binaries (images, fonts).
        Optional `worker_code` adds a Worker module in front of the assets (it
        gets an ASSETS binding to serve them via env.ASSETS.fetch(request));
        without it the site is served directly. `html_handling` accepts
        "auto-trailing-slash" (default), "force-trailing-slash",
        "drop-trailing-slash" or "none"; `not_found_handling` accepts "none"
        (default), "404-page" or "single-page-application". Size limits: 300
        files / 10 MiB total — beyond that, build locally and use wrangler.
        """
        client = get_cloudflare_client()
        account_id = await get_account_id()

        decoded = decode_input_files(files, files_base64)
        manifest = build_manifest(decoded)
        by_hash = {entry["hash"]: (path, decoded[path]) for path, entry in manifest.items()}

        session = await client.workers.scripts.assets.upload.create(
            script_name, account_id=account_id, manifest=manifest
        )
        session_jwt = getattr(session, "jwt", None)
        buckets = getattr(session, "buckets", None) or []
        if not session_jwt:
            raise RuntimeError("Cloudflare did not return an upload session JWT; check the token's Workers Scripts:Edit permission.")

        completion_jwt = await upload_buckets(account_id, session_jwt, buckets, by_hash)

        assets_config = compact(html_handling=html_handling, not_found_handling=not_found_handling)
        metadata = compact(
            assets=compact(jwt=completion_jwt, config=assets_config or None),
            compatibility_date=compatibility_date or DEFAULT_COMPATIBILITY_DATE,
            main_module="worker.js" if worker_code else None,
            bindings=[{"name": "ASSETS", "type": "assets"}] if worker_code else None,
        )
        script_files = (
            [("worker.js", worker_code.encode(), "application/javascript+module")]
            if worker_code
            else []
        )
        result = await client.workers.scripts.update(
            script_name,
            account_id=account_id,
            metadata=metadata,
            **({"files": script_files} if script_files else {}),
        )
        return {
            "deployed": True,
            "script_name": script_name,
            "assets_uploaded": sum(len(b) for b in buckets),
            "assets_total": len(decoded),
            "result": result.model_dump(exclude_none=True),
        }
