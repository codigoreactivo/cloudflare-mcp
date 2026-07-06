import os

from fastmcp import FastMCP
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware

from cfmcp.domains.dns_records import register_dns_record_tools
from cfmcp.domains.zones import register_zone_tools


def _build_auth() -> GitHubProvider:
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
    base_url = os.environ.get("MCP_BASE_URL")
    if not client_id or not client_secret:
        raise RuntimeError("GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET environment variables are not set")
    if not base_url:
        raise RuntimeError("MCP_BASE_URL environment variable is not set")
    return GitHubProvider(client_id=client_id, client_secret=client_secret, base_url=base_url)


def _only_allowed_user() -> AuthMiddleware:
    allowed_login = os.environ.get("ALLOWED_GITHUB_LOGIN")
    if not allowed_login:
        raise RuntimeError("ALLOWED_GITHUB_LOGIN environment variable is not set")

    def check(ctx):
        if ctx.token is None or ctx.token.claims.get("login") != allowed_login:
            raise AuthorizationError("Not authorized")
        return True

    return AuthMiddleware(auth=check)


auth = _build_auth()
mcp = FastMCP("cloudflare-mcp", auth=auth, middleware=[_only_allowed_user()])

register_zone_tools(mcp)
register_dns_record_tools(mcp)

app = mcp.http_app()

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
