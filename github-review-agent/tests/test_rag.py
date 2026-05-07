"""
Unit tests for the RAG indexer and retriever.
"""
import pytest


class TestIndexer:
    def test_index_repository_creates_collection(self):
        # TODO: B2.4 — index a temp dir of dummy files, assert ChromaDB collection exists
        pass

    def test_index_handles_empty_repo(self):
        # TODO: B2.4 — assert no error raised for empty directory
        pass


class TestRetriever:
    def test_retrieve_returns_relevant_chunk(self):
        # TODO: B2.4 — index dummy file, query with related text, assert chunk returned
        pass

    def test_retrieve_top_k_respected(self):
        # TODO: B2.4 — assert number of returned chunks <= top_k
        pass
