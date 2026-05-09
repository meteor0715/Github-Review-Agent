# Milestone 2 — Agents & LLM Logic

## What this milestone covers

Milestone 2 is the core AI brain of the project. We build the agent system that
actually analyses pull request code, finds problems, and formats them into GitHub
review comments.

Topics covered:

- What an LLM is and how it works conceptually
- LangChain and why we use it
- LCEL (LangChain Expression Language) — the `|` chain pattern
- The Factory design pattern (`llm_factory.py`)
- Prompt engineering and few-shot examples
- The Agent vs Chain decision
- Temperature and why we set it to 0.2
- Structured output parsing from LLMs
- The Orchestrator pattern
- The Formatter agent and GitHub Review API shape
- Unit testing with mocks (why and how)

---

## 1. What is an LLM?

An LLM (Large Language Model) is a neural network trained on vast amounts of text
to predict "what word comes next given all previous words". That sounds simple, but
at scale (billions of parameters, trillions of tokens of training data) it develops
emergent capabilities: code understanding, reasoning, following instructions, etc.

### Tokens, not words

LLMs don't process words — they process **tokens** (roughly 3/4 of a word on average).

```
"Hello, world!"  →  ["Hello", ",", " world", "!"]  →  [15339, 11, 1917, 0]
```

This matters for us because:

- Ollama's Llama3 has a **context window** of ~8192 tokens
- A large PR diff could exceed this limit
- That's why we split analysis per-file (one LLM call per file, not the whole diff)

### How we call the LLM

We never call Ollama directly with raw HTTP. We use LangChain, which abstracts it.

---

## 2. LangChain

### What is LangChain?

LangChain is a Python framework for building applications powered by LLMs. It provides:

```
┌─────────────────────────────────────────────────────────┐
│                       LangChain                         │
│                                                         │
│  LLM wrappers   → ChatOllama, ChatOpenAI, ChatGemini    │
│  Prompt templates → ChatPromptTemplate, SystemMessage   │
│  Output parsers  → StrOutputParser, JsonOutputParser    │
│  Memory          → conversation history management      │
│  Chains (LCEL)   → pipe LLMs together with |           │
│  Vector stores   → ChromaDB, Pinecone integration       │
│  Agents          → LLMs that use tools in a loop        │
└─────────────────────────────────────────────────────────┘
```

### Why LangChain instead of calling Ollama directly?

You COULD call Ollama directly with httpx:

```python
import httpx
response = httpx.post("http://localhost:11434/api/generate", json={
    "model": "llama3",
    "prompt": "Review this code: ..."
})
```

But then if you switch from Ollama to OpenAI, you rewrite every call.
LangChain wraps all providers behind the same interface:

```python
# Same code works for Ollama, OpenAI, Gemini — just swap the class
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

llm = ChatOllama(model="llama3")   # swap to ChatOpenAI() without touching agent code
response = llm.invoke("Review this code...")
```

This is the **Dependency Inversion Principle** — depend on abstractions, not concretions.

---

## 3. The Factory Pattern — `llm_factory.py`

### What is the Factory pattern?

Instead of every agent creating an LLM instance directly, they all call a single
`get_llm()` function. That function is the "factory" — it handles the construction
details.

```python
# WITHOUT factory (scattered, repetitive, hard to change):
# In orchestrator.py:
llm = ChatOllama(model="llama3", base_url="http://localhost:11434", temperature=0.2)

# In code_analysis_agent.py:
llm = ChatOllama(model="llama3", base_url="http://localhost:11434", temperature=0.2)

# In formatter_agent.py:
llm = ChatOllama(model="llama3", base_url="http://localhost:11434", temperature=0.2)

# Problem: To change the model, you edit 3+ files. Easy to miss one.


# WITH factory (centralised, single change point):
# In agents/llm_factory.py:
def get_llm(temperature=0.2):
    model = os.getenv("OLLAMA_MODEL", "llama3")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return ChatOllama(model=model, base_url=base_url, temperature=temperature)

# In every agent:
from agents.llm_factory import get_llm
llm = get_llm()  # ← one line, reads from env vars, consistent
```

This follows the **DRY principle** (Don't Repeat Yourself) and the
**Open/Closed Principle** (open for extension — add new model types by editing the
factory only, closed for modification — agents never change when the LLM changes).

### What is `temperature`?

Temperature controls the randomness of the LLM's output.

```
Temperature 0.0:  Fully deterministic. Same input always produces same output.
                  Good for: classification, factual lookups, exact answers
                  Risk: can be repetitive/boring, lacks nuance

Temperature 1.0:  Very random/creative. Different output every time.
                  Good for: creative writing, brainstorming, jokes
                  Risk: may generate false information ("hallucinate")

Temperature 0.2:  Slightly randomised. Mostly consistent, minor variations.
                  Good for: code review — consistent but can rephrase naturally
```

We use `0.2` for analysis (consistent findings) and `0.3` for the summary
(slightly more natural language variety).

---

## 4. LCEL — LangChain Expression Language

### What is LCEL?

LCEL is the `|` pipe operator pattern in LangChain for chaining components.

```python
chain = prompt | llm | output_parser
result = chain.invoke({"variable": "value"})
```

This looks like Unix pipes:

```bash
cat file.txt | grep "error" | head -10
```

Each component receives the output of the previous one.

### The full chain we use:

```
ChatPromptTemplate  →  formats the prompt with variables filled in
         |
         ▼
    ChatOllama      →  sends formatted prompt to Ollama, gets response
         |
         ▼
  StrOutputParser   →  extracts the text string from the response object
         |
         ▼
     Your code       →  receives a clean string, parses JSON from it
```

### Why StrOutputParser?

When you call `ChatOllama.invoke()`, it returns an `AIMessage` object:

```python
AIMessage(content='[{"line": 5, "severity": "HIGH", ...}]', ...)
```

`StrOutputParser` extracts just the `.content` string so you get:

```python
'[{"line": 5, "severity": "HIGH", ...}]'
```

This is neater than doing `response.content` everywhere — the parser is part
of the chain.

### Example from our code

```python
# From code_analysis_agent.py
chain = _BUG_PROMPT | get_llm() | StrOutputParser()
raw = chain.invoke({"code_snippet": added_code})
# raw is now a plain string containing JSON (or markdown-wrapped JSON)
findings = _parse_json_response(raw)
```

---

## 5. Prompt Engineering

### What is a prompt?

The prompt is the instruction you send to the LLM. Quality of output depends
enormously on prompt quality. This is called **prompt engineering**.

### System message vs Human message

LLMs trained for chat (like Llama3-chat) understand two roles:

```
System message:  Background context, persona, rules, output format instructions
                 Stays constant across all calls to this chain

Human message:   The actual input that changes each time
                 (in our case, the code snippet to review)
```

### Few-shot examples in prompts

Without an example, LLMs sometimes add prose around the JSON:

```
"I found these issues in the code:
[{"line": 5, "severity": "HIGH", ...}]
I hope this helps!"
```

With a few-shot example showing the EXACT expected format, the LLM learns to
just return the JSON:

```
[{"line": 5, "severity": "HIGH", ...}]
```

This is why our system prompts include an `Example output:` section:

```python
_BUG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert code reviewer...
Return ONLY a JSON array...

Example output:
[
  {{"line": 12, "severity": "HIGH", "message": "...", "suggestion": "..."}}
]"""),
    ("human", "Code diff to review:\n\n{code_snippet}"),
])
```

Note the `{{}}` double braces in the example — this is because LangChain uses
single `{}` for template variables (like `{code_snippet}`). To include literal
curly braces in the prompt, you escape them by doubling: `{{` → `{`.

### Why three separate prompts (bugs, security, quality)?

**One prompt trying to do everything:**

```
"Review this code for bugs, security issues, AND code quality problems"
```

Problems:

- LLM splits attention across all three concerns
- More likely to miss subtle issues
- Response format gets complicated
- If it fails, you lose ALL analysis

**Separate focused prompts (our approach):**

```python
analyze_bugs(snippet)      # LLM only thinks about bugs
analyze_security(snippet)  # LLM only thinks about security
analyze_quality(snippet)   # LLM only thinks about quality
```

Benefits:

- Focused → better detection per category
- Independent failure — security still runs even if bug analysis has an issue
- Easy to tune prompts per category
- Clearer findings (each tagged with its category)

This is the **Single Responsibility Principle** applied to prompts.

---

## 6. Agent vs Chain — Why we chose direct chains

### What is a LangChain Agent (ReAct loop)?

```
LLM decides which tool to call
    │
    ▼
Tool executes
    │
    ▼
LLM sees result, decides next tool
    │
    ▼
(repeat until LLM says "done")
```

This is called **ReAct** (Reasoning + Acting). The LLM reasons about what to
do next and acts by calling tools. Good for open-ended tasks like:
"Research this topic, find relevant papers, summarise them"

### Why NOT ReAct for our code review?

```
Problem 1: Local models (Llama3) sometimes loop infinitely in ReAct
           or hallucinate tool calls that don't exist.

Problem 2: We already KNOW the steps: analyze bugs → analyze security → analyze quality.
           We don't need the LLM to decide the order.

Problem 3: ReAct is harder to test (non-deterministic loop count).

Problem 4: ReAct adds latency — extra LLM calls just deciding what to do.
```

### What we use instead: Sequential chains

```python
def run_code_analysis_agent(diff, context=""):
    for file_diff in diff:
        snippet = file_diff["added_lines"]
        analyze_bugs(snippet)       # LLM call 1: focused on bugs
        analyze_security(snippet)   # LLM call 2: focused on security
        analyze_quality(snippet)    # LLM call 3: focused on quality
```

We control the flow. Each LLM call has ONE job. Predictable, testable, fast.

---

## 7. JSON Parsing from LLM Output — `_parse_json_response`

LLMs are probabilistic — they don't return perfectly formatted JSON 100% of the
time. They often wrap JSON in markdown code fences:

````
The code has these issues:
```json
[{"line": 5, "severity": "HIGH", "message": "..."}]
````

Let me know if you need more analysis.

````

Our `_parse_json_response` handles this robustly:

```python
def _parse_json_response(raw: str) -> list[dict]:
    # Step 1: Strip ```json ... ``` markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Step 2: Find the JSON array — skip any prose before/after it
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        return []  # No array found → no findings (safe default)

    # Step 3: Parse JSON — return empty list on malformed JSON
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
````

Why return `[]` on failure instead of raising an exception?

- The pipeline should not crash because one LLM call returned bad JSON
- An empty findings list means "no issues found" — wrong but safe
- Logging catches this for debugging

This is the **Fail-Safe Default** principle: when something goes wrong,
default to the safer option (no findings) rather than crashing.

---

## 8. The Formatter Agent

### Why a separate formatter?

The Code Analysis Agent knows about CODE PROBLEMS.
The Formatter Agent knows about GITHUB API FORMAT.

These are different concerns. Mixing them violates **Single Responsibility**.
If GitHub changes their comment API format, we only edit the formatter.
If we want to add a new analysis type (e.g. performance), we don't touch the formatter.

### GitHub Review API shape

```python
# What GitHub's Pull Request Review API expects:
{
    "commit_id": "abc123sha",
    "body": "Overall review summary (markdown)",
    "event": "COMMENT",   # or APPROVE or REQUEST_CHANGES
    "comments": [
        {
            "path": "src/app.py",   # file path relative to repo root
            "line": 42,             # line number in the NEW file (1-indexed)
            "side": "RIGHT",        # RIGHT = new file, LEFT = old file
            "body": "🔴 **[HIGH — Security]**\nHardcoded password found.\n\n**Suggestion:** Use os.getenv()"
        }
    ]
}
```

### The `side: "RIGHT"` explained

A PR diff has two sides:

```
LEFT (old code):          RIGHT (new code):
-password = "hardcoded"   +password = os.getenv("DB_PASS")
```

We comment on `RIGHT` because we're reviewing the NEW code being added.
Commenting on `LEFT` would mean commenting on deleted code — useless.

### Why `line: 1` as fallback?

If the LLM returns `line: 0` (impossible) or a non-integer, GitHub's API
rejects the review with a 422 error. We default to line 1 (top of the file) —
not perfect, but the comment is still posted and visible.

---

## 9. The Orchestrator Pattern

### What does the Orchestrator do?

```
                    run_orchestrator(diff, rag_context)
                                │
                    ┌───────────┼───────────┐
                    │           │           │
                    ▼           ▼           ▼
          run_code_analysis_agent()
          (bugs + security + quality per file)
                                │
                                ▼ findings list
                    format_review_comments(findings)
                                │
                                ▼ comments list
                    build_review_summary(findings)
                                │
                                ▼
                    return {"summary": ..., "comments": [...]}
```

### Why not call everything from `webhook_handler.py`?

The webhook handler should only care about HTTP concerns:

- Is the signature valid?
- What event type is this?
- Return a 200 response quickly

The orchestrator handles business logic:

- What agents to call?
- In what order?
- What to do with the results?

This separation makes each piece independently testable. We can test the
orchestrator with mock agents. We can test the webhook handler without any agents.

### Structlog for logging

```python
import structlog
log = structlog.get_logger()

log.info("orchestrator.start", files_in_diff=len(diff))
log.info("orchestrator.analysis.done", total_findings=len(findings))
```

**structlog vs Python's built-in `logging`:**

|                    | `logging`                                    | `structlog`                                         |
| ------------------ | -------------------------------------------- | --------------------------------------------------- |
| Output format      | Text string: `"INFO 2026-05-08 Starting..."` | JSON: `{"event": "orchestrator.start", "files": 3}` |
| Machine-readable   | No                                           | Yes                                                 |
| Searchable in logs | Difficult                                    | Easy (filter by any field)                          |
| Context passing    | Manual                                       | Automatic                                           |

In production, structured logs are parsed by tools like Datadog, CloudWatch,
Elastic. Text logs are hard to query. This is why modern Python backends use structlog.

---

## 10. Unit Testing with Mocks

### Why mock the LLM?

```
Without mocking:
  - Tests call Ollama → Ollama must be running → tests fail in CI
  - LLM output varies → tests are flaky (pass sometimes, fail others)
  - Each test waits for LLM → test suite takes minutes

With mocking (unittest.mock):
  - Ollama not needed → tests run anywhere, including CI
  - Mocked output is fixed → tests are deterministic
  - No actual LLM call → tests complete in milliseconds
```

### How `unittest.mock.patch` works

```python
from unittest.mock import patch, MagicMock

# This replaces the real get_llm() with a fake during the test
@patch("agents.code_analysis_agent.get_llm")
def test_something(self, mock_get_llm):
    # mock_get_llm is now a MagicMock — any call to it returns another MagicMock
    # You can configure it:
    mock_get_llm.return_value = MagicMock()

    # When agent code calls get_llm(), it gets the fake, not the real ChatOllama
    result = analyze_bugs("some code")
    # assert without needing Ollama
```

`patch("agents.code_analysis_agent.get_llm")` patches `get_llm` IN THE MODULE
where it's used (code_analysis_agent), not where it's defined (llm_factory).
This is a common mistake — always patch where the function is IMPORTED, not
where it's DEFINED.

### Testing `_parse_json_response` — no mocking needed

`_parse_json_response` is pure Python (no external calls). We test it directly:

````python
def test_parses_json_wrapped_in_code_fence(self):
    from agents.code_analysis_agent import _parse_json_response
    raw = '```json\n[{"line": 1, "severity": "LOW", "message": "x", "suggestion": "y"}]\n```'
    result = _parse_json_response(raw)
    assert len(result) == 1  # should strip the fences and parse correctly
````

Testing pure functions (no side effects, no external calls) is fast and reliable.
Aim to write as much pure logic as possible — it's always easier to test.

---

## Interview Questions — Milestone 2 Topics

---

**Q1: What is LangChain and why did you use it instead of calling Ollama directly?**

> LangChain is a framework that provides a unified interface for LLMs, prompt
> management, output parsing, and chaining components together. We use it instead
> of raw HTTP calls to Ollama because it abstracts the LLM provider — the same
> agent code works with Ollama, OpenAI, or Gemini by swapping one class. It also
> provides LCEL (the pipe operator pattern) for composing prompts, LLMs, and parsers
> into clean, readable chains. This follows the Dependency Inversion Principle.

---

**Q2: What is LCEL and how does the pipe operator work?**

> LCEL (LangChain Expression Language) lets you chain components with the `|`
> operator: `chain = prompt | llm | parser`. When you call `chain.invoke(inputs)`,
> inputs are formatted into the prompt, the prompt goes to the LLM, the LLM output
> goes to the parser, and the parsed result is returned. Each component is a
> "runnable" implementing the same interface. This is the same concept as Unix
> pipes: each step's output is the next step's input.

---

**Q3: What is the difference between an LLM Agent (ReAct) and a simple LLM chain? Which did you use and why?**

> A ReAct agent lets the LLM decide which tool to call next in a loop — it reasons
> about the task and acts by calling tools repeatedly until it's confident the
> task is done. A simple chain executes a fixed sequence of LLM calls in a
> predetermined order. We used direct chains for three reasons: first, we know
> the steps upfront (bugs, security, quality), so we don't need the LLM to decide
> the order. Second, local models like Llama3 can loop or hallucinate tool calls
> in ReAct mode. Third, direct chains are deterministic and easier to test.

---

**Q4: What is prompt engineering and how did you apply it in this project?**

> Prompt engineering is the practice of designing LLM inputs to reliably produce
> desired outputs. We applied three techniques: First, system/human message separation
> — the system message sets the persona ("you are a security reviewer") and output
> format, while the human message provides the variable input (the code). Second,
> separation of concerns — three separate focused prompts (bugs, security, quality)
> instead of one prompt trying to do everything. Third, few-shot examples — the
> exact JSON structure expected is shown in the prompt so the model doesn't add
> prose around it.

---

**Q5: How do you handle unpredictable LLM output in production code?**

> LLMs are non-deterministic and sometimes return malformed output. We handle this
> in `_parse_json_response` with a three-step approach: strip markdown code fences
> (LLMs often wrap JSON in triple backticks), find the JSON array by scanning for
> `[` and `]` rather than assuming clean output, and catch `json.JSONDecodeError`
> returning an empty list as a safe default. The principle is fail-safe default:
> if the LLM returns gibberish, we treat it as "no findings" rather than crashing
> the pipeline.

---

**Q6: What is the Factory design pattern and where did you use it?**

> The Factory pattern centralises object creation in one place. In `llm_factory.py`,
> the `get_llm()` function creates and returns a configured `ChatOllama` instance.
> All agents call `get_llm()` instead of constructing ChatOllama themselves. If we
> change the model or add a new provider, we edit one function not every agent file.
> This follows DRY (Don't Repeat Yourself), the Open/Closed Principle (add new
> providers by extending the factory, existing agents unchanged), and Dependency
> Inversion (agents depend on the `get_llm` abstraction, not on ChatOllama directly).

---

**Q7: What is the Single Responsibility Principle and how did you apply it to your agents?**

> The Single Responsibility Principle states that a class or module should have only
> one reason to change. We applied it by creating separate agents for separate concerns:
> Code Analysis Agent finds problems (the reason it changes: we want to detect
> different types of issues). Formatter Agent converts findings to GitHub API shape
> (reason it changes: GitHub changes their API). Orchestrator Agent coordinates the
> pipeline (reason it changes: we change the overall flow). If GitHub changes
> their review API format, we only modify the formatter — no other agent changes.

---

**Q8: What is temperature in an LLM and how did you choose the value for this project?**

> Temperature is a parameter that controls the randomness of LLM output. At 0.0,
> the model always picks the most probable next token — fully deterministic.
> At 1.0+, low-probability tokens are chosen more often — creative but unreliable.
> We use 0.2 for code analysis because we want consistent findings: the same bug
> found on the same code, not varying descriptions. We use 0.3 for the summary
> because we want slightly more natural, varied language. For tasks like code
> review where accuracy matters more than creativity, lower temperature is better.

---

**Q9: Why do you mock the LLM in unit tests instead of testing against the real model?**

> Three reasons. First, reliability: Ollama must be running and the model downloaded
> for tests to work — this breaks CI pipelines and other developers' machines.
> Second, determinism: LLM output varies between calls at temperature > 0, making
> tests non-deterministic (pass sometimes, fail others). Third, speed: each LLM call
> takes 1-10 seconds; a test suite with dozens of LLM calls would take minutes.
> With mocks, the entire test suite runs in under a second. We test OUR parsing
> and orchestration logic, not whether Ollama produces correct output.

---

**Q10: What is the Orchestrator pattern and how does it differ from just calling everything in sequence?**

> The Orchestrator pattern uses a dedicated coordinator component that manages the
> flow between other components. Rather than the webhook handler directly calling
> each agent, the orchestrator owns that coordination logic. This matters because:
> the webhook handler can be tested independently of agents; the orchestrator can
> be tested by mocking the agents it calls; the coordination logic (order, error
> handling, logging) is in one place. In microservices, the orchestrator pattern
> is contrasted with the choreography pattern — in choreography, each service
> reacts to events independently with no central coordinator.

---

**Q11: What is a context window and how did it influence your design?**

> A context window is the maximum number of tokens an LLM can process in a single
> call. Llama3's is ~8192 tokens. A large PR diff with many files could easily
> exceed this. We designed around this constraint by processing the diff file by
> file: each LLM call receives only one file's added lines plus the RAG context.
> If any single file is too large, the LLM sees it truncated rather than refusing
> to process the whole PR. This is a common real-world constraint when working with
> LLMs on long documents.
