from typing import Dict, Optional
from authlib.integrations.httpx_client import AsyncOAuth2Client

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    *,
    state: Optional[str] = None,
    scope: str = "read:user",
) -> str:
    """Return the GitHub authorization URL."""
    client = AsyncOAuth2Client(client_id=client_id, redirect_uri=redirect_uri)
    url, _state = client.create_authorization_url(
        GITHUB_AUTHORIZE_URL, state=state, scope=scope
    )
    return url


async def fetch_github_user(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> Dict[str, object]:
    """Exchange *code* for a token and return the user's profile."""
    async with AsyncOAuth2Client(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    ) as client:
        await client.fetch_token(
            GITHUB_ACCESS_TOKEN_URL,
            code=code,
            client_secret=client_secret,
        )
        resp = await client.get(GITHUB_USER_URL, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()
