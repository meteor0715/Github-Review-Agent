"""
Unit tests for the RAG indexer and retriever.

All ChromaDB and Ollama calls are mocked so these run without any external services.

Key concepts being tested:
  - Indexer correctly calls ChromaDB and embedding model
  - Indexer skips binary/excluded files
  - Retriever extracts clean query from diff (strips +/- prefixes)
  - Retriever handles missing collection gracefully (returns empty string)
  - Retriever formats context with filename headers
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─── Diff parser tests ────────────────────────────────────────────────────────
# parse_diff is pure Python (no external deps) so these are fully real tests
# with no mocking needed.

class TestDiffParser:
    """
    Tests for app.diff_parser.parse_diff

    Why test the diff parser so thoroughly?
    ----------------------------------------
    parse_diff is the first thing that runs in the pipeline. If it produces
    wrong line numbers or misses files, everything downstream is broken.
    It's also pure Python — no mocking needed, fast, reliable.
    """

    SIMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index a1b2c3d..e4f5g6h 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
 def connect():
+    password = "secret"
+    db.connect(password)
     return True
"""

    def test_parses_filename(self):
        from app.diff_parser import parse_diff
        result = parse_diff(self.SIMPLE_DIFF)
        assert len(result) == 1
        assert result[0]["filename"] == "src/app.py"

    def test_parses_added_lines(self):
        from app.diff_parser import parse_diff
        result = parse_diff(self.SIMPLE_DIFF)
        assert 'password = "secret"' in result[0]["added_lines"]
        assert "db.connect(password)" in result[0]["added_lines"]

    def test_does_not_include_removed_lines_in_added_lines(self):
        """Removed lines should NOT appear in added_lines."""
        diff = """\
diff --git a/src/x.py b/src/x.py
index abc..def 100644
--- a/src/x.py
+++ b/src/x.py
@@ -1,3 +1,3 @@
-old_function()
+new_function()
"""
        from app.diff_parser import parse_diff
        result = parse_diff(diff)
        assert "old_function" not in result[0]["added_lines"]
        assert "new_function" in result[0]["added_lines"]

    def test_empty_diff_returns_empty_list(self):
        from app.diff_parser import parse_diff
        assert parse_diff("") == []

    def test_parses_multiple_files(self):
        from app.diff_parser import parse_diff
        diff = """\
diff --git a/src/a.py b/src/a.py
index abc..def 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,1 +1,2 @@
 pass
+new_line_a()
diff --git a/src/b.py b/src/b.py
index abc..def 100644
--- a/src/b.py
+++ b/src/b.py
@@ -1,1 +1,2 @@
 pass
+new_line_b()
"""
        result = parse_diff(diff)
        assert len(result) == 2
        filenames = [r["filename"] for r in result]
        assert "src/a.py" in filenames
        assert "src/b.py" in filenames

    def test_hunk_line_numbers_are_correct(self):
        """Added lines should track the new file line number correctly."""
        from app.diff_parser import parse_diff
        result = parse_diff(self.SIMPLE_DIFF)
        hunks = result[0]["hunks"]
        assert len(hunks) == 1

        added = [l for l in hunks[0]["lines"] if l["type"] == "added"]
        assert len(added) == 2
        # Hunk starts at line 1, context takes line 1 → first added is line 2
        assert added[0]["line_no"] == 2
        assert added[1]["line_no"] == 3

    def test_context_lines_are_tracked(self):
        from app.diff_parser import parse_diff
        result = parse_diff(self.SIMPLE_DIFF)
        context_lines = [l for l in result[0]["hunks"][0]["lines"] if l["type"] == "context"]
        assert len(context_lines) >= 1


# ─── Indexer tests ────────────────────────────────────────────────────────────

class TestIndexer:
    @patch("rag.indexer._get_chroma_client")
    @patch("rag.indexer._get_embeddings")
    def test_index_repository_stores_chunks(self, mock_embeddings, mock_client, tmp_path):
        """Indexer should embed and store chunks from source files."""
        # Create a dummy Python file in a temp directory
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "hello.py").write_text("def hello():\n    return 'world'\n")

        # Mock ChromaDB collection
        mock_collection = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.create_collection.return_value = mock_collection
        mock_client.return_value = mock_client_instance

        # Mock embeddings — return a dummy vector
        mock_embeddings_instance = MagicMock()
        mock_embeddings_instance.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_embeddings.return_value = mock_embeddings_instance

        from rag.indexer import index_repository
        count = index_repository(str(tmp_path))

        assert count > 0
        mock_collection.add.assert_called()

    @patch("rag.indexer._get_chroma_client")
    @patch("rag.indexer._get_embeddings")
    def test_index_skips_excluded_dirs(self, mock_embeddings, mock_client, tmp_path):
        """Files inside node_modules, __pycache__, .git etc. should be skipped."""
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "lodash.js").write_text("// lodash")
        (tmp_path / "real_code.py").write_text("x = 1")

        mock_collection = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.create_collection.return_value = mock_collection
        mock_client.return_value = mock_client_instance
        mock_embeddings_instance = MagicMock()
        mock_embeddings_instance.embed_documents.return_value = [[0.1, 0.2]]
        mock_embeddings.return_value = mock_embeddings_instance

        from rag.indexer import index_repository
        index_repository(str(tmp_path))

        # All stored documents should be from real_code.py, not node_modules
        if mock_collection.add.called:
            stored_docs = mock_collection.add.call_args_list
            for call in stored_docs:
                metas = call.kwargs.get("metadatas") or call.args[2] if len(call.args) > 2 else []
                for meta in metas:
                    assert "node_modules" not in meta.get("filename", "")

    @patch("rag.indexer._get_chroma_client")
    @patch("rag.indexer._get_embeddings")
    def test_index_empty_repo_returns_zero(self, mock_embeddings, mock_client, tmp_path):
        """Indexing an empty directory should return 0."""
        mock_collection = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.create_collection.return_value = mock_collection
        mock_client.return_value = mock_client_instance
        mock_embeddings.return_value = MagicMock()

        from rag.indexer import index_repository
        count = index_repository(str(tmp_path))
        assert count == 0
        mock_collection.add.assert_not_called()


# ─── Retriever tests ──────────────────────────────────────────────────────────

class TestRetriever:
    def test_extract_query_from_diff_strips_plus_prefix(self):
        """_extract_query_from_diff should strip '+' from added lines."""
        from rag.retriever import _extract_query_from_diff
        diff = "+password = 'secret'\n+db.connect(password)\n"
        query = _extract_query_from_diff(diff)
        assert "password = 'secret'" in query
        assert not query.startswith("+")

    def test_extract_query_skips_plus_plus_plus_header(self):
        """Lines starting with +++ (file header) should not be in the query."""
        from rag.retriever import _extract_query_from_diff
        diff = "+++ b/src/app.py\n+real_code()\n"
        query = _extract_query_from_diff(diff)
        assert "b/src/app.py" not in query
        assert "real_code()" in query

    def test_extract_query_truncates_to_max_chars(self):
        from rag.retriever import _extract_query_from_diff
        long_diff = "+" + "x" * 600
        query = _extract_query_from_diff(long_diff, max_chars=500)
        assert len(query) <= 500

    @patch("rag.retriever._get_chroma_client")
    def test_retrieve_context_returns_empty_if_collection_missing(self, mock_client):
        """If the collection doesn't exist yet, return empty string (don't crash)."""
        mock_client.return_value.get_collection.side_effect = Exception("Collection not found")
        from rag.retriever import retrieve_context
        result = retrieve_context("+some code", collection_name="nonexistent")
        assert result == ""

    @patch("rag.retriever._get_chroma_client")
    def test_retrieve_context_returns_empty_if_collection_empty(self, mock_client):
        """Empty collection should return empty string."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_client.return_value.get_collection.return_value = mock_collection
        from rag.retriever import retrieve_context
        result = retrieve_context("+some code")
        assert result == ""

    @patch("rag.retriever._get_embeddings")
    @patch("rag.retriever._get_chroma_client")
    def test_retrieve_context_returns_formatted_chunks(self, mock_client, mock_embeddings):
        """Retriever should return formatted context with filename headers."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 3
        mock_collection.query.return_value = {
            "documents": [["def connect(): pass"]],
            "metadatas": [[{"filename": "src/db.py", "chunk_index": 0}]],
        }
        mock_client.return_value.get_collection.return_value = mock_collection

        mock_embeddings_instance = MagicMock()
        mock_embeddings_instance.embed_query.return_value = [0.1, 0.2, 0.3]
        mock_embeddings.return_value = mock_embeddings_instance

        from rag.retriever import retrieve_context
        result = retrieve_context("+db.connect()")
        assert "src/db.py" in result
        assert "def connect(): pass" in result
