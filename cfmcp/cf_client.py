import os

from cloudflare import AsyncCloudflare

_client: AsyncCloudflare | None = None


def get_cloudflare_client() -> AsyncCloudflare:
    global _client
    if _client is None:
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
        if not api_token:
            raise RuntimeError("CLOUDFLARE_API_TOKEN environment variable is not set")
        _client = AsyncCloudflare(api_token=api_token)
    return _client


def compact(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}
