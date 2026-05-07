"""
Parses unified diff format into a structured per-file, per-hunk, per-line representation
for consumption by the agent pipeline.
"""


def parse_diff(raw_diff: str) -> list[dict]:
    """
    Parse a unified diff string.

    Returns a list of file diffs:
    [
        {
            "filename": "src/foo.py",
            "hunks": [
                {
                    "header": "@@ -1,5 +1,7 @@",
                    "lines": [
                        {"type": "context" | "added" | "removed", "line_no": int, "content": str}
                    ]
                }
            ]
        }
    ]
    """
    # TODO: A3.2 — implement full unified diff parser
    pass
