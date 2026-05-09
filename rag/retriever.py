"""
RAG Retriever — given a PR diff, retrieves the most relevant existing
code snippets from ChromaDB to give agents broader codebase context.

How vector similarity search works:
-------------------------------------
When you query ChromaDB, it:
  1. Embeds your query text into a vector (same embedding model as indexing)
  2. Calculates the distance between your query vector and every stored vector
  3. Returns the top-k closest vectors (and their original text)

Distance metric: ChromaDB defaults to L2 (Euclidean distance).
Lower distance = more similar meaning.

Why is this better than keyword search (like grep)?
----------------------------------------------------
Keyword search finds exact word matches. Vector search finds SEMANTIC matches.

Example:
  Query: "database connection error handling"
  Keyword search: finds files literally containing "database connection error handling"
  Vector search: finds files about try/except around db.connect(), even if worded differently

For code review context, semantic search is far more useful.
"""

import os
from langchain_ollama import OllamaEmbeddings
import chromadb
from dotenv import load_dotenv

load_dotenv()


def _get_chroma_client() -> chromadb.PersistentClient:
    db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    return chromadb.PersistentClient(path=db_path)


def _get_embeddings() -> OllamaEmbeddings:
    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaEmbeddings(model=embed_model, base_url=base_url)


def _extract_query_from_diff(diff_text: str, max_chars: int = 500) -> str:
    """
    Extract a meaningful query string from a raw diff.

    Why not embed the entire raw diff?
    -----------------------------------
    A raw diff contains lots of noise: '+', '-', '@@' headers, line numbers.
    Embedding clean, meaningful text gives better retrieval results.

    We extract just the ADDED lines (lines starting with '+') and strip the
    '+' prefix, then truncate to max_chars to stay within embedding model limits.

    Args:
        diff_text: Raw unified diff string
        max_chars: Max characters to use as the query

    Returns:
        Clean text extracted from added lines in the diff
    """
    added_lines = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:].strip())  # strip the leading '+'

    query = " ".join(added_lines)
    return query[:max_chars] if query else diff_text[:max_chars]


def retrieve_context(
    diff_text: str,
    collection_name: str = "codebase",
    top_k: int = 5,
) -> str:
    """
    Retrieve top-k relevant code chunks from ChromaDB for the given diff.

    Args:
        diff_text: The raw diff string from the PR
        collection_name: ChromaDB collection to query (must be indexed first)
        top_k: Number of similar chunks to retrieve.
               5 is a good default — enough context without overflowing the
               LLM's context window when injected into the agent prompt.

    Returns:
        Formatted string of relevant code snippets to inject into agent prompts.
        Empty string if the collection doesn't exist or has no matching results.
    """
    # Try to get the collection — return empty string if it doesn't exist yet
    # (repo hasn't been indexed, which is fine for first-run or small PRs)
    try:
        client = _get_chroma_client()
        collection = client.get_collection(name=collection_name)
    except Exception:
        # Collection doesn't exist — indexer hasn't been run yet
        return ""

    # Check the collection isn't empty
    if collection.count() == 0:
        return ""

    # Build a clean query from the diff's added lines
    query_text = _extract_query_from_diff(diff_text)
    if not query_text.strip():
        return ""

    # Embed the query and search
    embeddings_fn = _get_embeddings()
    query_vector = embeddings_fn.embed_query(query_text)

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, collection.count()),  # can't request more than exists
        include=["documents", "metadatas"],
    )

    # Format retrieved chunks into a readable context block
    # We include the filename so the LLM knows WHERE the context is from
    chunks = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    if not chunks:
        return ""

    context_parts = []
    for chunk, meta in zip(chunks, metas):
        filename = meta.get("filename", "unknown")
        context_parts.append(f"# From {filename}:\n{chunk}")

    return "\n\n---\n\n".join(context_parts)

