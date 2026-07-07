import os

from fastmcp import FastMCP
from mcp.server.auth.settings import ClientRegistrationOptions

from cfmcp.domains.dns_records import register_dns_record_tools
from cfmcp.domains.zones import register_zone_tools
from cfmcp.oauth import PasswordOAuthProvider, register_login_routes


def _build_auth() -> PasswordOAuthProvider:
    base_url = os.environ.get("MCP_BASE_URL")
    password = os.environ.get("MCP_OAUTH_PASSWORD")
    if not base_url:
        raise RuntimeError("MCP_BASE_URL environment variable is not set")
    if not password:
        raise RuntimeError("MCP_OAUTH_PASSWORD environment variable is not set")
    return PasswordOAuthProvider(
        base_url=base_url,
        password=password,
        client_registration_options=ClientRegistrationOptions(enabled=True),
    )


auth = _build_auth()
mcp = FastMCP("cloudflare-mcp", auth=auth)

register_zone_tools(mcp)
register_dns_record_tools(mcp)
register_login_routes(mcp, auth)

app = mcp.http_app()

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
