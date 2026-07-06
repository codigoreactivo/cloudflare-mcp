import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from cfmcp.domains.dns_records import register_dns_record_tools
from cfmcp.domains.zones import register_zone_tools


def _build_auth() -> StaticTokenVerifier:
    token = os.environ.get("MCP_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("MCP_ACCESS_TOKEN environment variable is not set")
    return StaticTokenVerifier(tokens={token: {"client_id": "cloudflare-mcp"}})


mcp = FastMCP("cloudflare-mcp", auth=_build_auth())

register_zone_tools(mcp)
register_dns_record_tools(mcp)

app = mcp.http_app()

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
