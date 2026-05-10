"""
LLM Factory — single place to create LangChain LLM instances.

Reads OLLAMA_BASE_URL and OLLAMA_MODEL from environment variables and returns
a configured ChatOllama instance. All agents import from here so if we ever
swap the model (e.g. llama3 → mistral), we change ONE line in ONE file.

Why a factory?
--------------
This is the Factory design pattern. Instead of every agent doing:
    llm = ChatOllama(model="llama3", base_url="http://localhost:11434")
...scattered across 5 files, they all call get_llm() here. If the model
name changes, you change it once. This is also called the DRY principle
(Don't Repeat Yourself).

Interview note: "We used a factory pattern to decouple agent logic from
LLM configuration, following the Open/Closed principle — open for extension
(add new model types) but closed for modification (existing agents untouched)."
"""

import os
from langchain_ollama import ChatOllama
from dotenv import load_dotenv

load_dotenv()


def get_llm(temperature: float = 0.2) -> ChatOllama:
    """
    Return a configured ChatOllama instance.

    Args:
        temperature: Controls randomness in LLM output.
                     0.0 = fully deterministic (same input → same output)
                     1.0 = very creative/random
                     We use 0.2 for code review — we want consistency,
                     but a little flexibility to rephrase suggestions.

    Returns:
        ChatOllama instance ready for use in LangChain chains and agents.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    return ChatOllama(
        model=model,
        base_url=base_url,
        temperature=temperature,
    )
