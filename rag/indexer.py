"""
RAG Indexer — chunks and embeds repository source files into ChromaDB
using Ollama's nomic-embed-text embedding model.
Run this once (or on demand) to build/refresh the vector index.
"""


def index_repository(repo_path: str, collection_name: str = "codebase") -> None:
    """
    Walk repo_path, chunk all source files, embed them with Ollama,
    and store in ChromaDB.

    Args:
        repo_path: Local path to the repository to index
        collection_name: ChromaDB collection to store embeddings in
    """
    # TODO: B2.1 — implement chunking (LangChain RecursiveCharacterTextSplitter)
    # TODO: B2.1 — embed with OllamaEmbeddings(model="nomic-embed-text")
    # TODO: B2.1 — persist to ChromaDB
    pass
