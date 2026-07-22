import os

from fastmcp import FastMCP
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.middleware import AuthMiddleware

from cfmcp.domains.dns_records import register_dns_record_tools
from cfmcp.domains.zones import register_zone_tools
from cfmcp.workers.assets import register_worker_asset_tools
from cfmcp.workers.d1 import register_d1_tools
from cfmcp.workers.kv import register_worker_kv_tools
from cfmcp.workers.r2 import register_r2_tools
from cfmcp.workers.routing import register_worker_routing_tools
from cfmcp.workers.scripts import register_worker_script_tools
from cfmcp.workers.secrets import register_worker_secret_tools


def _build_auth() -> GoogleProvider:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    base_url = os.environ.get("MCP_BASE_URL")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET environment variables are not set")
    if not base_url:
        raise RuntimeError("MCP_BASE_URL environment variable is not set")
    return GoogleProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        required_scopes=["openid", "email"],
    )


def _only_allowed_user() -> AuthMiddleware:
    allowed_email = os.environ.get("ALLOWED_GOOGLE_EMAIL")
    if not allowed_email:
        raise RuntimeError("ALLOWED_GOOGLE_EMAIL environment variable is not set")

    def check(ctx):
        if ctx.token is None:
            raise AuthorizationError("Not authorized")
        claims = ctx.token.claims
        if claims.get("email") != allowed_email or not claims.get("email_verified"):
            raise AuthorizationError("Not authorized")
        return True

    return AuthMiddleware(auth=check)


auth = _build_auth()
mcp = FastMCP("cloudflare-mcp", auth=auth, middleware=[_only_allowed_user()])

register_zone_tools(mcp)
register_dns_record_tools(mcp)
register_worker_script_tools(mcp)
register_worker_routing_tools(mcp)
register_worker_secret_tools(mcp)
register_worker_kv_tools(mcp)
register_worker_asset_tools(mcp)
register_r2_tools(mcp)
register_d1_tools(mcp)

app = mcp.http_app()

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
