"""
RAG Indexer — chunks and embeds repository source files into ChromaDB.

What is RAG (Retrieval-Augmented Generation)?
----------------------------------------------
RAG is a pattern that gives an LLM access to external knowledge it wasn't
trained on. Instead of just using the LLM's training data, you:
  1. Store your own documents in a vector database
  2. When the LLM needs context, RETRIEVE the most relevant documents
  3. AUGMENT the LLM prompt with those documents
  4. LLM GENERATES a better answer using both its training + your documents

Why do we need RAG for code review?
-------------------------------------
When reviewing a PR diff, the LLM only sees the changed lines. But to
understand if a bug is REALLY a bug, it needs to know:
  - How is this function called elsewhere?
  - What does this class's __init__ look like?
  - Is there already a pattern for error handling in this codebase?

RAG gives the agent that codebase context.

How ChromaDB works:
--------------------
ChromaDB is a vector database. A "vector" is just a list of numbers (floats)
that represents the MEANING of a piece of text in mathematical space.
Texts with similar meaning have vectors that are close together (low distance).

The pipeline here is:
  Source file → split into chunks → embed each chunk (text → vector)
  → store {vector + original text} in ChromaDB

Later, retriever.py does:
  Diff text → embed → find nearest vectors → return their original text
"""

import os
from pathlib import Path
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from dotenv import load_dotenv

load_dotenv()

# ─── File extensions we index ────────────────────────────────────────────────
# We only index code files, not binary files, lock files, or generated outputs.
# Indexing package-lock.json or .pyc files would add noise with no value.
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".cs", ".go", ".rs", ".rb",
    ".cpp", ".c", ".h", ".md", ".yaml", ".yml",
}

# Directories that should never be indexed
EXCLUDED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".pytest_cache", "chroma_db",
}


def _get_chroma_client() -> chromadb.PersistentClient:
    """
    Return a persistent ChromaDB client pointed at CHROMA_DB_PATH.

    PersistentClient vs in-memory Client:
    - chromadb.Client()          → in-memory, data lost when process exits
    - chromadb.PersistentClient() → saves to disk, survives restarts

    We use PersistentClient so the index survives between runs.
    """
    db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    return chromadb.PersistentClient(path=db_path)


def _get_embeddings() -> OllamaEmbeddings:
    """
    Return a configured OllamaEmbeddings instance.

    nomic-embed-text is a dedicated embedding model (different from llama3).
    We use a DIFFERENT model for embeddings vs generation because:
    - Embedding models are optimised to produce meaningful vector representations
    - Generation models (llama3) are optimised to produce text
    - Using a generation model for embeddings gives worse retrieval quality
    """
    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaEmbeddings(model=embed_model, base_url=base_url)


def _collect_files(repo_path: str) -> list[Path]:
    """
    Walk the repo and return paths of all supported source files.

    Args:
        repo_path: Root directory of the repository to index

    Returns:
        List of Path objects for each indexable file
    """
    root = Path(repo_path)
    files = []

    for path in root.rglob("*"):
        # Skip excluded directories anywhere in the path
        if any(excluded in path.parts for excluded in EXCLUDED_DIRS):
            continue
        if path.is_file() and path.suffix in SUPPORTED_EXTENSIONS:
            files.append(path)

    return files


def index_repository(repo_path: str, collection_name: str = "codebase") -> int:
    """
    Walk repo_path, chunk all source files, embed them, and store in ChromaDB.

    Chunking strategy — why RecursiveCharacterTextSplitter?
    --------------------------------------------------------
    We can't embed an entire file as one vector — it would be too long for
    the embedding model and too vague to retrieve precisely.

    RecursiveCharacterTextSplitter splits on ['\n\n', '\n', ' ', ''] in order,
    trying to keep semantically related code together (functions, classes).
    This is better than splitting at fixed character counts mid-function.

    chunk_size=1000 chars (~200 tokens) is a balance:
    - Too small: each chunk loses context (a function split across chunks)
    - Too large: retrieval is imprecise (chunk contains many unrelated things)

    chunk_overlap=200 chars: adjacent chunks share 200 characters so a
    function split across chunk boundaries still appears in one of them fully.

    Args:
        repo_path: Local path to the repository root to index
        collection_name: ChromaDB collection name (default "codebase")

    Returns:
        Number of chunks indexed
    """
    print(f"[Indexer] Scanning {repo_path}...")
    files = _collect_files(repo_path)
    print(f"[Indexer] Found {len(files)} files to index")

    if not files:
        return 0

    # Set up text splitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
    )

    # Prepare ChromaDB — get or create collection
    client = _get_chroma_client()
    # delete_collection_if_exists so re-indexing is always fresh
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass  # Collection didn't exist yet — that's fine
    collection = client.create_collection(name=collection_name)

    embeddings_fn = _get_embeddings()

    all_texts = []
    all_ids = []
    all_metadatas = []

    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue  # Skip unreadable files

        chunks = splitter.split_text(content)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_path}::chunk_{i}"
            all_texts.append(chunk)
            all_ids.append(chunk_id)
            all_metadatas.append({
                "filename": str(file_path),
                "chunk_index": i,
            })

    if not all_texts:
        return 0

    # Embed and store in batches of 50 to avoid memory issues on large repos
    batch_size = 50
    for i in range(0, len(all_texts), batch_size):
        batch_texts = all_texts[i : i + batch_size]
        batch_ids = all_ids[i : i + batch_size]
        batch_metas = all_metadatas[i : i + batch_size]

        vectors = embeddings_fn.embed_documents(batch_texts)
        collection.add(
            documents=batch_texts,
            embeddings=vectors,
            ids=batch_ids,
            metadatas=batch_metas,
        )
        print(f"[Indexer] Indexed batch {i // batch_size + 1} ({len(batch_texts)} chunks)")

    total = len(all_texts)
    print(f"[Indexer] Done — {total} chunks indexed into collection '{collection_name}'")
    return total

