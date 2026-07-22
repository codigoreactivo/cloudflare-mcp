import os

from cloudflare import AsyncCloudflare

_client: AsyncCloudflare | None = None
_account_id: str | None = None


def get_cloudflare_client() -> AsyncCloudflare:
    global _client
    if _client is None:
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
        if not api_token:
            raise RuntimeError("CLOUDFLARE_API_TOKEN environment variable is not set")
        _client = AsyncCloudflare(api_token=api_token)
    return _client


async def get_account_id() -> str:
    """Resolve the Cloudflare account id for account-scoped APIs (Workers, KV).

    The phase-1 tools (zones, DNS) are zone-scoped and never needed this; the
    Workers APIs all require an account id. Resolution order: the
    CLOUDFLARE_ACCOUNT_ID env var if set, else auto-discovery when the API
    token can see exactly one account. Cached for the process lifetime.
    """
    global _account_id
    if _account_id:
        return _account_id
    env_value = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if env_value:
        _account_id = env_value
        return _account_id
    client = get_cloudflare_client()
    accounts = [account async for account in client.accounts.list()]
    if len(accounts) == 1:
        _account_id = accounts[0].id
        return _account_id
    if not accounts:
        raise RuntimeError(
            "The API token cannot list any account — it is probably zone-scoped "
            "(the phase-1 DNS token). Workers tools need a token with account-level "
            "Workers permissions, or set CLOUDFLARE_ACCOUNT_ID explicitly."
        )
    raise RuntimeError(
        f"The API token sees {len(accounts)} accounts; set CLOUDFLARE_ACCOUNT_ID "
        "to choose which one Workers tools operate on."
    )


def compact(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}
