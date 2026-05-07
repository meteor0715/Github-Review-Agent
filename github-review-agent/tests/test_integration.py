"""
Integration tests — runs the full pipeline against a fixture PR diff
without needing a live GitHub connection or Ollama (mocked).
"""
import pytest


SAMPLE_DIFF = """
diff --git a/src/app.py b/src/app.py
index 1234567..abcdefg 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,6 +10,8 @@ def connect():
+    password = "supersecret123"
+    db.connect(password)
"""


class TestFullPipeline:
    def test_pipeline_produces_comments_for_diff(self):
        # TODO: A4.3 — run full pipeline with SAMPLE_DIFF, assert comments list non-empty
        pass

    def test_pipeline_posts_comments_to_github(self):
        # TODO: A4.3 — mock comment_poster, assert it is called with correct args
        pass

    def test_pipeline_handles_empty_diff_gracefully(self):
        # TODO: A4.3 — assert no error and empty comments returned for empty diff
        pass
