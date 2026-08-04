"""Tests for the zone tools.

create_zone is the one zone-lifecycle call, and the wire shape is easy to get
wrong: the account goes in the BODY as a nested object, not as a query param or
a URL segment like the account-scoped Workers endpoints. A regression there
fails with a confusing 400 rather than an auth error, so it gets a tripwire.
"""

import json

import httpx
import pytest

import cfmcp.cf_client as cf_client
from cfmcp.domains.zones import register_zone_tools

ACCOUNT_ID = "test-account-id"


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


def zone_response(request: httpx.Request, captured: dict) -> httpx.Response:
    captured["method"] = request.method
    captured["url"] = str(request.url)
    captured["body"] = json.loads(request.read())
    return httpx.Response(
        200,
        json={
            "success": True,
            "errors": [],
            "messages": [],
            "result": {
                "id": "zone-1",
                "name": "example.com",
                "status": "pending",
                "name_servers": ["desiree.ns.cloudflare.com", "ken.ns.cloudflare.com"],
            },
        },
    )


@pytest.mark.anyio
async def test_create_zone_posts_account_in_body(account_env, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cf_client, "_client", make_sdk_client(lambda r: zone_response(r, captured))
    )

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    register_zone_tools(mcp)
    tool = await mcp.get_tool("create_zone")
    result = await tool.run({"name": "example.com"})

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/zones")
    # the account is a nested object in the body — not a query param, and not a
    # /accounts/<id>/ URL prefix the way the Workers endpoints are shaped
    assert captured["body"]["account"] == {"id": ACCOUNT_ID}
    assert captured["body"]["name"] == "example.com"
    assert captured["body"]["type"] == "full"

    structured = result.structured_content
    assert structured["id"] == "zone-1"
    assert structured["status"] == "pending"
    # the nameservers are the whole point of the call: without them there is
    # nothing to paste into the registrar
    assert structured["name_servers"] == [
        "desiree.ns.cloudflare.com",
        "ken.ns.cloudflare.com",
    ]


@pytest.mark.anyio
async def test_create_zone_explicit_account_overrides_env(account_env, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cf_client, "_client", make_sdk_client(lambda r: zone_response(r, captured))
    )

    from fastmcp import FastMCP

    mcp = FastMCP("test")
    register_zone_tools(mcp)
    tool = await mcp.get_tool("create_zone")
    await tool.run({"name": "example.com", "account_id": "other-account"})

    assert captured["body"]["account"] == {"id": "other-account"}
