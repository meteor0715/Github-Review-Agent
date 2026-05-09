"""
Tests for GitHub client modules: auth, comment_poster, status_updater.
All HTTP calls are mocked with unittest.mock — no real GitHub API calls.

Why mock HTTP calls?
---------------------
Tests must be:
  1. Independent — don't break when GitHub is down
  2. Fast — no network round trips
  3. Free — no API rate limits consumed during testing

We use unittest.mock.patch to replace httpx.post with a fake that returns
whatever response we define. This tests OUR code logic, not GitHub's API.
"""

import pytest
from unittest.mock import patch, MagicMock


# ─── Auth tests ───────────────────────────────────────────────────────────────

class TestGenerateJWT:
    def test_raises_if_app_id_missing(self, monkeypatch):
        """generate_jwt should raise ValueError if GITHUB_APP_ID not set."""
        monkeypatch.delenv("GITHUB_APP_ID", raising=False)
        from github_client.auth import generate_jwt
        with pytest.raises(ValueError, match="GITHUB_APP_ID"):
            generate_jwt(app_id=None)

    def test_raises_if_pem_file_missing(self, monkeypatch):
        """generate_jwt should raise FileNotFoundError if .pem doesn't exist."""
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        from github_client.auth import generate_jwt
        with pytest.raises(FileNotFoundError):
            generate_jwt(app_id="12345", private_key_path="./nonexistent.pem")

    def test_jwt_is_string(self, tmp_path, monkeypatch):
        """With valid inputs, generate_jwt should return a non-empty string."""
        # Generate a real RSA key pair for testing
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pem_file = tmp_path / "test-key.pem"
        pem_file.write_bytes(pem)

        from github_client.auth import generate_jwt
        token = generate_jwt(app_id="12345", private_key_path=str(pem_file))
        assert isinstance(token, str)
        assert len(token) > 50  # JWT should be non-trivially long

    @patch("github_client.auth.httpx.post")
    def test_get_installation_token_returns_token(self, mock_post):
        """get_installation_token should POST to GitHub and return the token value."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_fake_token_abc123"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from github_client.auth import get_installation_token
        token = get_installation_token(
            installation_id="99999",
            jwt_token="fake.jwt.token",
        )
        assert token == "ghs_fake_token_abc123"
        mock_post.assert_called_once()

    @patch("github_client.auth.httpx.post")
    def test_get_installation_token_uses_correct_url(self, mock_post):
        """get_installation_token should POST to correct GitHub API URL."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_abc"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from github_client.auth import get_installation_token
        get_installation_token(installation_id="42", jwt_token="my.jwt")

        call_url = mock_post.call_args[0][0]
        assert "installations/42/access_tokens" in call_url


# ─── Comment poster tests ─────────────────────────────────────────────────────

class TestCommentPoster:
    SAMPLE_COMMENTS = [
        {"path": "src/app.py", "line": 5, "side": "RIGHT", "body": "🔴 **[HIGH]** Issue found"},
    ]

    @patch("github_client.comment_poster.httpx.post")
    def test_post_review_calls_correct_url(self, mock_post):
        """post_review_comments should POST to the PR reviews endpoint."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 1}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from github_client.comment_poster import post_review_comments
        post_review_comments(
            token="ghs_fake",
            repo_full_name="owner/repo",
            pr_number=42,
            comments=self.SAMPLE_COMMENTS,
            summary="Review summary",
            commit_sha="abc123",
        )

        call_url = mock_post.call_args[0][0]
        assert "owner/repo" in call_url
        assert "42" in call_url
        assert "reviews" in call_url

    @patch("github_client.comment_poster.httpx.post")
    def test_post_review_sends_comments_and_summary(self, mock_post):
        """Request body should include comments, summary, and COMMENT event."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 1}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from github_client.comment_poster import post_review_comments
        post_review_comments(
            token="ghs_fake",
            repo_full_name="owner/repo",
            pr_number=1,
            comments=self.SAMPLE_COMMENTS,
            summary="Overall summary",
            commit_sha="abc123",
        )

        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_body["event"] == "COMMENT"
        assert sent_body["body"] == "Overall summary"
        assert sent_body["comments"] == self.SAMPLE_COMMENTS
        assert sent_body["commit_id"] == "abc123"


# ─── Status updater tests ─────────────────────────────────────────────────────

class TestStatusUpdater:
    @patch("github_client.status_updater.httpx.post")
    def test_set_commit_status_posts_correct_state(self, mock_post):
        """set_commit_status should POST the correct state to GitHub."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"state": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from github_client.status_updater import set_commit_status
        set_commit_status(
            token="ghs_fake",
            repo_full_name="owner/repo",
            sha="abc123sha",
            state="success",
            description="AI Review complete — 0 issues",
        )

        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_body["state"] == "success"
        assert sent_body["context"] == "ai-review-agent"

    def test_set_commit_status_rejects_invalid_state(self):
        """set_commit_status should raise ValueError for invalid state strings."""
        from github_client.status_updater import set_commit_status
        with pytest.raises(ValueError, match="Invalid state"):
            set_commit_status(
                token="t", repo_full_name="o/r", sha="abc",
                state="flying",  # not a valid state
            )

    @patch("github_client.status_updater.httpx.post")
    def test_description_truncated_to_140_chars(self, mock_post):
        """Descriptions over 140 chars should be truncated with ellipsis."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from github_client.status_updater import set_commit_status
        long_desc = "x" * 200
        set_commit_status(
            token="t", repo_full_name="o/r", sha="abc",
            state="success", description=long_desc
        )
        sent_desc = mock_post.call_args.kwargs["json"]["description"]
        assert len(sent_desc) <= 140
        assert sent_desc.endswith("...")


# ─── Webhook handler tests ────────────────────────────────────────────────────

class TestWebhookHandler:
    def test_parse_pr_payload_extracts_fields(self):
        """parse_pr_payload should extract all required fields from webhook JSON."""
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Add password field",
                "diff_url": "https://github.com/owner/repo/pull/42.diff",
                "base": {"sha": "base_sha_abc"},
                "head": {"sha": "head_sha_xyz"},
            },
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 99},
        }
        from app.webhook_handler import parse_pr_payload
        result = parse_pr_payload(payload)
        assert result["pr_number"] == 42
        assert result["repo_full_name"] == "owner/repo"
        assert result["action"] == "opened"
        assert result["head_sha"] == "head_sha_xyz"
        assert result["installation_id"] == "99"

    def test_parse_pr_payload_returns_none_for_closed_action(self):
        """PR 'closed' action should return None — we don't review closed PRs."""
        payload = {
            "action": "closed",
            "pull_request": {"number": 1, "base": {"sha": ""}, "head": {"sha": ""}, "diff_url": ""},
            "repository": {"full_name": "o/r"},
            "installation": {"id": 1},
        }
        from app.webhook_handler import parse_pr_payload
        assert parse_pr_payload(payload) is None

    def test_verify_signature_rejects_wrong_secret(self, monkeypatch):
        """Webhook with wrong HMAC secret should fail verification."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "correct_secret")
        from app.webhook_handler import _verify_signature
        import hmac
        import hashlib
        # Sign with the WRONG secret
        wrong_mac = hmac.new(b"wrong_secret", b"payload", hashlib.sha256)
        fake_sig = "sha256=" + wrong_mac.hexdigest()
        assert _verify_signature(b"payload", fake_sig) is False

    def test_verify_signature_accepts_correct_secret(self, monkeypatch):
        """Webhook with correct HMAC-SHA256 signature should pass verification."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "my_secret")
        from app.webhook_handler import _verify_signature
        import hmac
        import hashlib
        payload = b'{"action": "opened"}'
        mac = hmac.new(b"my_secret", payload, hashlib.sha256)
        sig = "sha256=" + mac.hexdigest()
        assert _verify_signature(payload, sig) is True
