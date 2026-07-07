"""Minimal self-issued OAuth 2.1 provider gated by a single shared password.

No third-party identity provider (no GitHub/Google/etc.) — this server is its
own authorization server, as required for the Claude Desktop / claude.ai
custom-connector UI, which only supports OAuth (no static bearer token field).

Reuses InMemoryOAuthProvider's client registry and token issuance (both
already correct/RFC-compliant); only authorize() is overridden, since the
base class auto-approves any client with no real credential check — which
is fine for its documented purpose (tests) but not for managing real
Cloudflare DNS.
"""

import html
import secrets
import time

from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

PENDING_LOGIN_EXPIRY_SECONDS = 5 * 60
MAX_BACKOFF_SECONDS = 5 * 60
FREE_ATTEMPTS = 3

LOGIN_FORM = """<!doctype html>
<html><body style="font-family: system-ui, sans-serif; max-width: 360px; margin: 80px auto;">
<h2>cloudflare-mcp</h2>
<form method="post">
  <input type="hidden" name="login_id" value="{login_id}">
  <label>Password<br><input type="password" name="password" autofocus style="width: 100%; padding: 8px; margin: 8px 0;"></label>
  <p style="color: crimson">{error}</p>
  <button type="submit" style="padding: 8px 16px;">Sign in</button>
</form>
</body></html>"""


class PasswordOAuthProvider(InMemoryOAuthProvider):
    def __init__(self, *, password: str, **kwargs):
        super().__init__(**kwargs)
        self._password = password
        self._pending: dict[str, tuple[OAuthClientInformationFull, AuthorizationParams, float]] = {}
        self._failed_attempts = 0
        self._locked_until = 0.0

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if client.client_id is None or client.client_id not in self.clients:
            raise AuthorizeError(
                error="unauthorized_client",
                error_description=f"Client '{client.client_id}' not registered.",
            )

        login_id = secrets.token_urlsafe(24)
        self._pending[login_id] = (client, params, time.time() + PENDING_LOGIN_EXPIRY_SECONDS)
        base = str(self.base_url).rstrip("/")
        return f"{base}/login?login_id={login_id}"

    def check_password(self, password: str) -> bool:
        if time.time() < self._locked_until:
            return False
        if secrets.compare_digest(password, self._password):
            self._failed_attempts = 0
            return True
        self._failed_attempts += 1
        if self._failed_attempts > FREE_ATTEMPTS:
            backoff = min(2 ** (self._failed_attempts - FREE_ATTEMPTS), MAX_BACKOFF_SECONDS)
            self._locked_until = time.time() + backoff
        return False

    async def complete_login(self, login_id: str) -> str:
        """Issue the real authorization code and return the client's redirect URL."""
        entry = self._pending.pop(login_id, None)
        if entry is None:
            raise AuthorizeError(error="access_denied", error_description="Login session expired or invalid.")
        client, params, expires_at = entry
        if time.time() > expires_at:
            raise AuthorizeError(error="access_denied", error_description="Login session expired.")
        if client.client_id is None:
            raise AuthorizeError(error="invalid_client", error_description="Client ID is required.")

        scopes_list = params.scopes or []
        if client.scope:
            allowed = set(client.scope.split())
            scopes_list = [s for s in scopes_list if s in allowed]

        auth_code_value = f"cfmcp_auth_code_{secrets.token_hex(16)}"
        self.auth_codes[auth_code_value] = AuthorizationCode(
            code=auth_code_value,
            client_id=client.client_id,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=scopes_list,
            expires_at=time.time() + 300,
            code_challenge=params.code_challenge,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=auth_code_value, state=params.state)


def register_login_routes(mcp, auth: PasswordOAuthProvider) -> None:
    @mcp.custom_route("/login", methods=["GET", "POST"])
    async def login(request: Request) -> Response:
        if request.method == "GET":
            login_id = request.query_params.get("login_id", "")
            return HTMLResponse(LOGIN_FORM.format(login_id=html.escape(login_id), error=""))

        form = await request.form()
        login_id = str(form.get("login_id", ""))
        password = str(form.get("password", ""))

        if not auth.check_password(password):
            return HTMLResponse(
                LOGIN_FORM.format(login_id=html.escape(login_id), error="Incorrect password"),
                status_code=401,
            )

        try:
            redirect_url = await auth.complete_login(login_id)
        except AuthorizeError as e:
            return HTMLResponse(
                f"<p>Login failed: {html.escape(e.error_description or e.error)}</p>",
                status_code=400,
            )

        return RedirectResponse(url=redirect_url, status_code=302)
