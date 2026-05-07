"""
GitHub App Authentication — generates JWT tokens and exchanges them for
short-lived installation access tokens used to call the GitHub API.
"""
import time


def generate_jwt(app_id: str, private_key_path: str) -> str:
    """
    Generate a signed JWT for the GitHub App.

    Args:
        app_id: GitHub App ID from the App settings page
        private_key_path: Path to the downloaded .pem private key file

    Returns:
        Signed JWT string (valid for 10 minutes)
    """
    # TODO: B1.3 — implement using PyJWT
    pass


def get_installation_token(jwt: str, installation_id: str) -> str:
    """
    Exchange a JWT for an installation access token.

    Args:
        jwt: Signed JWT from generate_jwt()
        installation_id: GitHub App installation ID (from webhook payload)

    Returns:
        Short-lived installation access token string
    """
    # TODO: B1.3 — POST to /app/installations/{id}/access_tokens
    pass
