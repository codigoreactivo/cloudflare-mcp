"""Tests for the Workers modules.

The wire-level tests matter most: they assert the exact multipart shape
Cloudflare expects (module parts named by filename, assets uploads keyed by
content hash, session JWT auth) without touching the network — the same
tripwire pattern that caught the fastmcp null-drop regression in dokploy-mcp.
"""

import base64
import hashlib
import json

import httpx
import pytest

import cfmcp.cf_client as cf_client
import cfmcp.workers.assets as assets_mod
import cfmcp.workers.d1 as d1_mod
import cfmcp.workers.r2 as r2_mod
import cfmcp.workers.scripts as scripts_mod
from cfmcp.workers.assets import (
    asset_hash,
    build_manifest,
    decode_input_files,
    normalize_path,
)

ACCOUNT_ID = "test-account-id"


# --- pure helpers -----------------------------------------------------------


def test_asset_hash_matches_cloudflare_algorithm():
    # sha256(base64(content) + extension) hex, truncated to 32 chars — the
    # exact formula from Cloudflare's direct-upload docs (and wrangler).
    content = b"<html>hello</html>"
    expected = hashlib.sha256(base64.b64encode(content) + b".html").hexdigest()[:32]
    assert asset_hash(content, "/index.html") == expected
    assert len(expected) == 32


def test_asset_hash_differs_by_extension():
    content = b"same bytes"
    assert asset_hash(content, "/a.css") != asset_hash(content, "/a.js")


def test_normalize_path_adds_leading_slash():
    assert normalize_path("index.html") == "/index.html"
    assert normalize_path("/index.html") == "/index.html"


def test_build_manifest_shape():
    manifest = build_manifest({"/index.html": b"<html></html>"})
    entry = manifest["/index.html"]
    assert set(entry) == {"hash", "size"}
    assert entry["size"] == len(b"<html></html>")


def test_decode_input_files_merges_text_and_base64():
    decoded = decode_input_files(
        {"index.html": "<html></html>"},
        {"/logo.png": base64.b64encode(b"\x89PNG").decode()},
    )
    assert decoded["/index.html"] == b"<html></html>"
    assert decoded["/logo.png"] == b"\x89PNG"


def test_decode_input_files_rejects_empty_and_oversize():
    with pytest.raises(ValueError):
        decode_input_files(None, None)
    big = "x" * (assets_mod.MAX_TOTAL_BYTES + 1)
    with pytest.raises(ValueError):
        decode_input_files({"/big.txt": big}, None)
    many = {f"/f{i}.txt": "x" for i in range(assets_mod.MAX_FILES + 1)}
    with pytest.raises(ValueError):
        decode_input_files(many, None)


# --- wire-level: what actually reaches Cloudflare ---------------------------


def make_sdk_client(handler):
    from cloudflare import AsyncCloudflare

    return AsyncCloudflare(
        api_token="test-token",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def account_env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setattr(cf_client, "_account_id", None)
    yield
    monkeypatch.setattr(cf_client, "_client", None)
    monkeypatch.setattr(cf_client, "_account_id", None)


@pytest.mark.anyio
async def test_deploy_worker_sends_module_part_named_by_filename(account_env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"success": True, "errors": [], "messages": [], "result": {"id": "w"}})

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))
    client = cf_client.get_cloudflare_client()
    account_id = await cf_client.get_account_id()

    code = "export default { fetch() { return new Response('ok') } }"
    await client.workers.scripts.update(
        "my-worker",
        account_id=account_id,
        metadata={"main_module": "worker.js", "compatibility_date": "2026-07-01"},
        files=[("worker.js", code.encode(), "application/javascript+module")],
    )

    assert f"/accounts/{ACCOUNT_ID}/workers/scripts/my-worker" in captured["url"]
    assert captured["content_type"].startswith("multipart/form-data")
    body = captured["body"]
    # The module part must be named by its filename — that's how the metadata's
    # main_module reference resolves — and carry the ES-module content type.
    assert b'name="worker.js"' in body
    assert b"application/javascript+module" in body
    assert code.encode() in body
    # metadata travels as a JSON part
    assert b'name="metadata"' in body
    assert b"main_module" in body


@pytest.mark.anyio
async def test_deploy_static_site_full_flow(account_env, monkeypatch):
    """Session → bucket upload (JWT auth, hash-keyed parts) → deploy with completion JWT."""
    seen = {"session": None, "uploads": [], "deploy": None}
    index_html = "<html>site</html>"
    index_hash = asset_hash(index_html.encode(), "/index.html")

    def sdk_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/assets-upload-session"):
            seen["session"] = json.loads(request.read())
            return httpx.Response(
                200,
                json={"success": True, "errors": [], "messages": [],
                      "result": {"jwt": "session-jwt", "buckets": [[index_hash]]}},
            )
        seen["deploy"] = request.read()
        return httpx.Response(200, json={"success": True, "errors": [], "messages": [], "result": {"id": "site"}})

    def upload_handler(request: httpx.Request) -> httpx.Response:
        seen["uploads"].append(
            {"auth": request.headers.get("authorization"), "body": request.read()}
        )
        return httpx.Response(201, json={"success": True, "errors": [], "messages": [], "result": {"jwt": "completion-jwt"}})

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(sdk_handler))
    monkeypatch.setattr(assets_mod, "_TRANSPORT", httpx.MockTransport(upload_handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    assets_mod.register_worker_asset_tools(mcp)
    tool = await mcp.get_tool("deploy_static_site")
    result = await tool.run({"script_name": "my-site", "files": {"index.html": index_html}})

    manifest = seen["session"]["manifest"]
    assert manifest["/index.html"]["hash"] == index_hash
    # bucket upload authenticates with the session JWT, not the API token,
    # and keys each part by content hash with base64 body
    upload = seen["uploads"][0]
    assert upload["auth"] == "Bearer session-jwt"
    assert index_hash.encode() in upload["body"]
    assert base64.b64encode(index_html.encode()) in upload["body"]
    # the final deploy carries the completion JWT from the upload response
    assert b"completion-jwt" in seen["deploy"]
    structured = result.structured_content
    assert structured["deployed"] is True
    assert structured["assets_uploaded"] == 1


@pytest.mark.anyio
async def test_list_worker_deployments_surfaces_traffic_split(account_env, monkeypatch):
    """list_worker_deployments must expose the live traffic split (versions + percentage),
    not just a bare version list — that distinction from list_worker_versions is the whole
    point of this tool."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "success": True, "errors": [], "messages": [],
                "result": {
                    "deployments": [
                        {
                            "id": "dep-2",
                            "created_on": "2026-07-22T00:00:00Z",
                            "source": "api",
                            "strategy": "percentage",
                            "author_email": "a@b.com",
                            "versions": [
                                {"version_id": "v2", "percentage": 90},
                                {"version_id": "v1", "percentage": 10},
                            ],
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    scripts_mod.register_worker_script_tools(mcp)
    tool = await mcp.get_tool("list_worker_deployments")
    result = await tool.run({"script_name": "my-worker"})

    assert f"/accounts/{ACCOUNT_ID}/workers/scripts/my-worker/deployments" in captured["url"]
    deployments = result.structured_content["result"]
    assert deployments[0]["id"] == "dep-2"
    versions = deployments[0]["versions"]
    assert {v["version_id"]: v["percentage"] for v in versions} == {"v2": 90, "v1": 10}


@pytest.mark.anyio
async def test_get_worker_deployment_hits_single_deployment_endpoint(account_env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "success": True, "errors": [], "messages": [],
                "result": {
                    "id": "dep-2", "created_on": "2026-07-22T00:00:00Z", "source": "api",
                    "strategy": "percentage", "versions": [{"version_id": "v2", "percentage": 100}],
                },
            },
        )

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    scripts_mod.register_worker_script_tools(mcp)
    tool = await mcp.get_tool("get_worker_deployment")
    result = await tool.run({"script_name": "my-worker", "deployment_id": "dep-2"})

    assert f"/accounts/{ACCOUNT_ID}/workers/scripts/my-worker/deployments/dep-2" in captured["url"]
    assert result.structured_content["id"] == "dep-2"


@pytest.mark.anyio
async def test_create_worker_version_hits_versions_endpoint_not_scripts(account_env, monkeypatch):
    """A staged version must go to .../versions, never .../scripts (which would deploy it live)."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(
            200,
            json={"success": True, "errors": [], "messages": [],
                  "result": {"id": "ver-1", "number": 2, "resources": {}}},
        )

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    scripts_mod.register_worker_script_tools(mcp)
    tool = await mcp.get_tool("create_worker_version")
    result = await tool.run({"script_name": "my-worker", "code": "export default {}"})

    assert captured["url"].endswith(f"/accounts/{ACCOUNT_ID}/workers/scripts/my-worker/versions")
    assert result.structured_content["id"] == "ver-1"


@pytest.mark.anyio
async def test_set_worker_traffic_split_sends_full_version_list(account_env, monkeypatch):
    """A canary split must send every {version_id, percentage} entry as-is — dropping one silently
    would misroute traffic, the same class of bug as the fastmcp null-drop lesson."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"success": True, "errors": [], "messages": [], "result": {"id": "dep-3"}})

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    scripts_mod.register_worker_script_tools(mcp)
    tool = await mcp.get_tool("set_worker_traffic_split")
    versions = [{"version_id": "new", "percentage": 10}, {"version_id": "old", "percentage": 90}]
    await tool.run({"script_name": "my-worker", "versions": versions})

    assert captured["body"]["versions"] == versions
    assert captured["body"]["strategy"] == "percentage"


@pytest.mark.anyio
async def test_set_worker_schedules_replaces_full_cron_list(account_env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={"success": True, "errors": [], "messages": [],
                  "result": {"schedules": [{"cron": "0 0 * * *"}, {"cron": "0 */6 * * *"}]}},
        )

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    scripts_mod.register_worker_script_tools(mcp)
    tool = await mcp.get_tool("set_worker_schedules")
    result = await tool.run({"script_name": "my-worker", "crons": ["0 0 * * *", "0 */6 * * *"]})

    assert captured["url"].endswith(f"/accounts/{ACCOUNT_ID}/workers/scripts/my-worker/schedules")
    assert captured["body"] == [{"cron": "0 0 * * *"}, {"cron": "0 */6 * * *"}]
    schedules = result.structured_content["result"]
    assert [s["cron"] for s in schedules] == ["0 0 * * *", "0 */6 * * *"]


@pytest.mark.anyio
async def test_create_r2_bucket_and_list(account_env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        if request.method == "POST":
            captured["body"] = json.loads(request.read())
            return httpx.Response(
                200,
                json={"success": True, "errors": [], "messages": [],
                      "result": {"name": "my-bucket", "creation_date": "2026-07-22T00:00:00Z", "location": "wnam", "storage_class": "Standard"}},
            )
        return httpx.Response(
            200,
            json={"success": True, "errors": [], "messages": [],
                  "result": {"buckets": [{"name": "my-bucket", "storage_class": "Standard"}]}},
        )

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    r2_mod.register_r2_tools(mcp)

    create_tool = await mcp.get_tool("create_r2_bucket")
    created = await create_tool.run({"name": "my-bucket", "location_hint": "wnam"})
    # the SDK translates snake_case params to the camelCase the R2 API expects on the wire
    assert captured["body"] == {"name": "my-bucket", "locationHint": "wnam"}
    assert created.structured_content["name"] == "my-bucket"

    list_tool = await mcp.get_tool("list_r2_buckets")
    result = await list_tool.run({})
    assert f"/accounts/{ACCOUNT_ID}/r2/buckets" in captured["url"]
    buckets = result.structured_content["result"]
    assert buckets[0]["name"] == "my-bucket"


@pytest.mark.anyio
async def test_query_d1_database_sends_sql_and_params(account_env, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={"success": True, "errors": [], "messages": [],
                  "result": [{"success": True, "results": [{"id": 1, "name": "a"}], "meta": {"rows_read": 1}}]},
        )

    monkeypatch.setattr(cf_client, "_client", make_sdk_client(handler))

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    d1_mod.register_d1_tools(mcp)
    tool = await mcp.get_tool("query_d1_database")
    result = await tool.run({"database_id": "db-1", "sql": "SELECT * FROM users WHERE id = ?", "params": ["1"]})

    assert captured["url"].endswith(f"/accounts/{ACCOUNT_ID}/d1/database/db-1/query")
    assert captured["body"] == {"sql": "SELECT * FROM users WHERE id = ?", "params": ["1"]}
    rows = result.structured_content["result"]
    assert rows[0]["results"][0]["name"] == "a"
