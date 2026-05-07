"""
RAG Retriever — given a PR diff, retrieves the most relevant existing
code snippets from ChromaDB to provide agents with broader codebase context.
"""


def retrieve_context(diff_text: str, collection_name: str = "codebase", top_k: int = 5) -> str:
    """
    Retrieve top-k relevant code chunks from ChromaDB for the given diff.

    Args:
        diff_text: The raw diff string or a query derived from the diff
        collection_name: ChromaDB collection to query
        top_k: Number of chunks to retrieve

    Returns:
        Concatenated context string to inject into agent prompts
    """
    # TODO: B2.2 — query ChromaDB using OllamaEmbeddings(model="nomic-embed-text")
    # TODO: B2.3 — return formatted context string
    pass
