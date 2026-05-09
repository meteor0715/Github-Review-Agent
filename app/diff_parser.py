"""
Diff Parser — parses unified diff format into a structured per-file representation.

What is a unified diff?
------------------------
When you open a PR on GitHub and fetch the raw diff, it looks like this:

    diff --git a/src/app.py b/src/app.py
    index a1b2c3d..e4f5g6h 100644
    --- a/src/app.py
    +++ b/src/app.py
    @@ -10,6 +10,8 @@ def connect():
         host = "localhost"
    +    password = "supersecret123"
    +    db.connect(password)
         return True

Anatomy:
  diff --git a/... b/...  → file header, tells us the filename
  --- a/src/app.py        → old version of file
  +++ b/src/app.py        → new version of file
  @@ -10,6 +10,8 @@      → hunk header: old file starts at line 10, new file starts at line 10
  lines with no prefix   → context (unchanged lines, shown for reference)
  lines starting with +  → added lines (new code)
  lines starting with -  → removed lines (deleted code)

Why do we need to parse this?
------------------------------
Our agents need:
  1. Which file is being changed (for tagging findings with the right filename)
  2. Which lines were ADDED (we only review new code — deleted code is gone)
  3. What line number each added line is at (for posting inline GitHub comments)
"""

import re


def parse_diff(raw_diff: str) -> list[dict]:
    """
    Parse a unified diff string into a structured list of file diffs.

    Args:
        raw_diff: Raw unified diff string (from GitHub API or git diff)

    Returns:
        List of file diff dicts:
        [
            {
                "filename": "src/app.py",
                "added_lines": "password = ...\ndb.connect(...)\n",
                "hunks": [
                    {
                        "new_start": 10,   ← line number in new file where hunk starts
                        "lines": [
                            {"type": "context", "line_no": 10, "content": "    host = 'localhost'"},
                            {"type": "added",   "line_no": 11, "content": "    password = 'supersecret123'"},
                        ]
                    }
                ]
            }
        ]
    """
    file_diffs = []
    current_file = None
    current_hunk = None
    new_line_no = 0  # tracks line number in the new (right-side) file

    for line in raw_diff.splitlines():

        # ── File header: "diff --git a/src/app.py b/src/app.py"
        if line.startswith("diff --git"):
            # Save previous file if exists
            if current_file:
                if current_hunk:
                    current_file["hunks"].append(current_hunk)
                    current_hunk = None
                file_diffs.append(current_file)

            current_file = {
                "filename": "",
                "added_lines": "",
                "hunks": [],
            }
            continue

        # ── New file path: "+++ b/src/app.py"
        # We use +++ (new file) not --- (old file) because we want the NEW filename
        if line.startswith("+++ b/"):
            if current_file is not None:
                current_file["filename"] = line[6:]  # strip "+++ b/"
            continue

        # Skip the --- line (old file path) — we don't need it
        if line.startswith("--- "):
            continue

        # Skip binary file markers and index lines
        if line.startswith("index ") or line.startswith("Binary "):
            continue

        # ── Hunk header: "@@ -10,6 +10,8 @@ def connect():"
        # The regex captures the new file start line from "+10,8"
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match and current_file is not None:
            if current_hunk:
                current_file["hunks"].append(current_hunk)

            new_line_no = int(hunk_match.group(1))
            current_hunk = {
                "new_start": new_line_no,
                "lines": [],
            }
            continue

        # ── Content lines
        if current_file is None or current_hunk is None:
            continue

        if line.startswith("+"):
            # Added line — strip the leading '+'
            content = line[1:]
            current_hunk["lines"].append({
                "type": "added",
                "line_no": new_line_no,
                "content": content,
            })
            current_file["added_lines"] += content + "\n"
            new_line_no += 1

        elif line.startswith("-"):
            # Removed line — does NOT advance new_line_no (it doesn't exist in new file)
            current_hunk["lines"].append({
                "type": "removed",
                "line_no": None,
                "content": line[1:],
            })

        else:
            # Context line (no prefix or space prefix)
            content = line[1:] if line.startswith(" ") else line
            current_hunk["lines"].append({
                "type": "context",
                "line_no": new_line_no,
                "content": content,
            })
            new_line_no += 1

    # Don't forget the last file
    if current_file:
        if current_hunk:
            current_file["hunks"].append(current_hunk)
        file_diffs.append(current_file)

    # Filter out files with no filename (malformed diff sections)
    return [f for f in file_diffs if f["filename"]]

