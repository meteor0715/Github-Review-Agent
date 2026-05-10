"""
Integration tests — runs the full pipeline against a fixture PR diff
without needing a live GitHub connection or Ollama (all mocked).

What is an integration test vs a unit test?
--------------------------------------------
Unit test: tests ONE function in isolation, all dependencies mocked.
           Fast, precise, but doesn't test how parts work TOGETHER.

Integration test: tests MULTIPLE components wired together.
                  Slower, but catches bugs at the seams between components —
                  e.g. "the orchestrator returns the right shape for comment_poster to accept".

Why mock GitHub and Ollama here?
---------------------------------
We're testing that the WIRING between components is correct:
  diff_parser → orchestrator → comment_poster
We trust the individual units (tested in test_agents.py / test_rag.py).
We mock external services (Ollama, GitHub) so tests run without those services.

Interview note: "Integration tests give us confidence that agents, formatter,
and GitHub client compose correctly. We mock at the boundary of external
services so tests stay fast and deterministic."
"""
import pytest
from unittest.mock import patch, MagicMock


# A realistic diff with two security issues to trigger findings
SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1234567..abcdefg 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,6 +10,8 @@ def connect():
     host = "localhost"
+    password = "supersecret123"
+    db.connect(host, password)
     return True
diff --git a/src/auth.py b/src/auth.py
index 0000001..0000002 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -1,3 +1,5 @@
 def login(user, pwd):
+    query = f"SELECT * FROM users WHERE name='{user}'"
+    db.execute(query)
     return True
"""

# Diff with only whitespace / comment changes — should produce zero or minimal findings
CLEAN_DIFF = """\
diff --git a/src/utils.py b/src/utils.py
index abc..def 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,3 +1,4 @@
 # Utility helpers
+# Updated: added docstring
 def noop():
     pass
"""


class TestFullPipeline:
    """
    Tests that verify the full pipeline from parsed diff → orchestrator → comments.

    Mock strategy
    -------------
    We mock run_code_analysis_agent (the LLM boundary) and return pre-built
    findings. This lets us test that:
      parse_diff → orchestrator → formatter → comment_poster
    all compose correctly, without needing a real LLM.

    The internal behaviour of run_code_analysis_agent is already covered in
    test_agents.py — integration tests should mock at the external boundary,
    not re-test internals.
    """

    SECURITY_FINDINGS = [
        {
            "filename": "src/app.py",
            "line": 11,
            "message": "Hardcoded password detected",
            "severity": "HIGH",
            "category": "security",
            "suggestion": "Use os.getenv('DB_PASS') instead",
        }
    ]

    SQL_FINDINGS = [
        {
            "filename": "src/auth.py",
            "line": 2,
            "message": "SQL injection risk — f-string used in query",
            "severity": "HIGH",
            "category": "security",
            "suggestion": "Use parameterised query: db.execute('SELECT * FROM users WHERE name=?', (user,))",
        }
    ]

    @patch("agents.orchestrator.build_review_summary")
    @patch("agents.orchestrator.run_code_analysis_agent")
    def test_pipeline_produces_comments_for_diff(self, mock_analysis, mock_summary):
        """
        End-to-end: parse a diff with security issues → orchestrator returns
        non-empty comments list.

        Verifies:
        - parse_diff produces per-file data correctly
        - finding dicts flow through format_review_comments into comment shape
        - result has expected keys: comments, summary
        """
        mock_analysis.return_value = self.SECURITY_FINDINGS
        mock_summary.return_value = "Found 1 HIGH severity issue."

        from app.diff_parser import parse_diff
        from agents.orchestrator import run_orchestrator

        parsed = parse_diff(SAMPLE_DIFF)
        assert len(parsed) >= 1, "diff parser should find at least 1 file"

        result = run_orchestrator(parsed, rag_context="")

        assert "comments" in result
        assert "summary" in result
        assert isinstance(result["comments"], list)
        assert len(result["comments"]) > 0

    @patch("agents.orchestrator.build_review_summary")
    @patch("agents.orchestrator.run_code_analysis_agent")
    @patch("github_client.comment_poster.httpx.post")
    def test_pipeline_posts_comments_to_github(self, mock_http_post, mock_analysis, mock_summary):
        """
        Verifies that when orchestrator produces findings, comment_poster makes
        the GitHub API call with the required fields: commit_id, event, comments.
        """
        mock_analysis.return_value = self.SQL_FINDINGS
        mock_summary.return_value = "Found 1 SQL injection issue."
        mock_http_post.return_value = MagicMock(status_code=200,
                                                json=lambda: {"id": 999})

        from app.diff_parser import parse_diff
        from agents.orchestrator import run_orchestrator
        from github_client.comment_poster import post_review_comments

        parsed = parse_diff(SAMPLE_DIFF)
        result = run_orchestrator(parsed, rag_context="")

        post_review_comments(
            token="fake-token",
            repo_full_name="owner/repo",
            pr_number=42,
            comments=result["comments"],
            summary=result["summary"],
            commit_sha="abc123sha",
        )

        assert mock_http_post.called
        call_kwargs = mock_http_post.call_args
        post_body = call_kwargs.kwargs.get("json") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})
        assert "commit_id" in post_body
        assert post_body["commit_id"] == "abc123sha"
        assert "event" in post_body
        assert post_body["event"] == "COMMENT"

    @patch("agents.orchestrator.build_review_summary")
    @patch("agents.orchestrator.run_code_analysis_agent")
    def test_pipeline_handles_empty_diff_gracefully(self, mock_analysis, mock_summary):
        """
        An empty diff should not cause errors and should return zero comments.
        Edge case: closed PRs or PRs with only binary changes produce empty diffs.
        """
        mock_analysis.return_value = []
        mock_summary.return_value = "No issues found."

        from app.diff_parser import parse_diff
        from agents.orchestrator import run_orchestrator

        parsed = parse_diff("")
        assert parsed == [], "empty diff should produce empty list"

        result = run_orchestrator(parsed, rag_context="")
        assert result["comments"] == []

    @patch("agents.orchestrator.build_review_summary")
    @patch("agents.orchestrator.run_code_analysis_agent")
    def test_clean_diff_produces_no_high_findings(self, mock_analysis, mock_summary):
        """
        A diff with only comment/whitespace changes → no HIGH findings.
        """
        mock_analysis.return_value = []
        mock_summary.return_value = "No issues found."

        from app.diff_parser import parse_diff
        from agents.orchestrator import run_orchestrator

        parsed = parse_diff(CLEAN_DIFF)
        result = run_orchestrator(parsed, rag_context="")

        high_findings = [
            c for c in result["comments"]
            if "🔴" in c.get("body", "") or "[HIGH]" in c.get("body", "")
        ]
        assert high_findings == []

    @patch("github_client.status_updater.httpx.post")
    def test_commit_status_pending_then_success(self, mock_http_post):
        """
        Verifies set_commit_status can be called for the full pending → success
        lifecycle without error, and both calls reach the correct API endpoint.
        """
        mock_http_post.return_value = MagicMock(
            status_code=201, json=lambda: {"state": "success"}
        )

        from github_client.status_updater import set_commit_status

        set_commit_status("fake-token", "owner/repo", "deadbeef1234",
                          "pending", "AI Review starting…")
        set_commit_status("fake-token", "owner/repo", "deadbeef1234",
                          "success", "AI Review complete — 0 HIGH issues")

        assert mock_http_post.call_count == 2

        for call in mock_http_post.call_args_list:
            url = call.args[0] if call.args else call.kwargs.get("url", "")
            assert "statuses" in url

