"""
GitHub App Authentication — generates JWT tokens and exchanges them for
short-lived installation access tokens.

Full auth flow recap (covered in B1.1):
-----------------------------------------
Step 1: Sign a JWT with your RSA private key (valid 10 minutes)
Step 2: POST JWT to GitHub → receive installation access token (valid 1 hour)
Step 3: Use installation token as Bearer token for all GitHub API calls

Why do tokens expire?
----------------------
Short-lived tokens limit blast radius if a token leaks. Even if an attacker
grabs a token from logs or memory, it's useless after 1 hour. This is the
principle of least privilege over TIME — a core security concept.

Why RS256 (RSA) and not HS256 (HMAC)?
----------------------------------------
HMAC (symmetric): same key signs AND verifies → GitHub would need your secret
RSA (asymmetric): private key signs, public key verifies → you keep private key,
                  GitHub only has the public key. Even if GitHub is breached,
                  no one can forge tokens using the public key alone.
"""

import time
import os
import httpx
import jwt  # PyJWT
from dotenv import load_dotenv

load_dotenv()

GITHUB_API_URL = "https://api.github.com"


def generate_jwt(
    app_id: str | None = None,
    private_key_path: str | None = None,
) -> str:
    """
    Generate a signed RS256 JWT for authenticating as the GitHub App.

    JWT payload fields (required by GitHub):
      iat (issued at): when the JWT was created — MUST be slightly in the past
                       (we subtract 60s) to account for clock skew between servers
      exp (expires):   when the JWT expires — max 10 minutes in the future
      iss (issuer):    your GitHub App ID — tells GitHub which app this JWT is for

    Args:
        app_id: GitHub App ID (reads GITHUB_APP_ID env var if not provided)
        private_key_path: Path to .pem file (reads GITHUB_APP_PRIVATE_KEY_PATH if not provided)

    Returns:
        Signed JWT string

    Raises:
        FileNotFoundError: If the private key .pem file doesn't exist
        ValueError: If app_id is missing
    """
    app_id = app_id or os.getenv("GITHUB_APP_ID")
    private_key_path = private_key_path or os.getenv(
        "GITHUB_APP_PRIVATE_KEY_PATH", "./secrets/private-key.pem"
    )

    if not app_id:
        raise ValueError("GITHUB_APP_ID is not set in environment variables")

    pem_path = os.path.abspath(private_key_path)
    if not os.path.exists(pem_path):
        raise FileNotFoundError(f"Private key not found at {pem_path}. Did you download it from GitHub App settings?")

    with open(pem_path, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iat": now - 60,       # issued 60s ago — prevents clock skew rejection
        "exp": now + (10 * 60), # expires in 10 minutes (GitHub's maximum)
        "iss": str(app_id),    # issuer = your App ID
    }

    # Sign with RS256 (RSA + SHA-256)
    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token


def get_installation_token(
    installation_id: str,
    jwt_token: str | None = None,
) -> str:
    """
    Exchange a JWT for a short-lived installation access token.

    The installation token is what we actually use to make API calls
    (post comments, set commit status, read diffs).

    Args:
        installation_id: GitHub App installation ID.
                         Found in webhook payload under installation.id
                         Or in GitHub App settings → Install App → see URL
        jwt_token: Pre-generated JWT. If None, generates a fresh one.

    Returns:
        Installation access token string (valid for ~1 hour)

    Raises:
        httpx.HTTPStatusError: If GitHub rejects the JWT (invalid/expired)
    """
    token = jwt_token or generate_jwt()

    url = f"{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Using httpx (sync) here for simplicity in this utility function
    # Milestone 4 will use async httpx for the full pipeline
    response = httpx.post(url, headers=headers)
    response.raise_for_status()  # raises HTTPStatusError on 4xx/5xx

    return response.json()["token"]

