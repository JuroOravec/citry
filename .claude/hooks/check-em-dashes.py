#!/usr/bin/env python3
"""
Em-dash detector for Citry docs and source.

Per CLAUDE.md house style: no em dashes (U+2014) in agent docs, code
comments, or docstrings. This PostToolUse hook scans Edit/Write outputs
and warns Claude (via hookSpecificOutput.additionalContext) when em
dashes remain, so they can be fixed before the next turn.

Why warn instead of block: the warn-to-Claude mode keeps the UX silent
for the user when Claude does the right thing; the warning lands in
Claude's next-turn context so the fix happens immediately.

Scope per file type:
- .md   : flag em dashes anywhere outside fenced code blocks (``` ... ```).
          Prose is the target; code examples may legitimately show them.
- .rs / .py / .pyi : em dashes essentially never belong in Rust/Python
          source, comments, or docstrings, so flag anywhere.

Reads PostToolUse JSON on stdin:
  {"tool_input": {"file_path": "..."}, "tool_response": {"filePath": "..."}}

Outputs (only when violations found):
  {"hookSpecificOutput": {
     "hookEventName": "PostToolUse",
     "additionalContext": "<file:line excerpts>"}}

Silent (exit 0, no stdout) when:
- input isn't a .md/.rs/.py/.pyi file
- file can't be read
- no em dashes in scanned content
"""
import json
import sys

CODE_EXT = (".md", ".rs", ".py", ".pyi")
EM = "—"  # em dash


def blank_md_code_fences(src: str) -> str:
    """
    Replace the contents of fenced code blocks (``` or ~~~) with blank
    lines, preserving line count so reported line numbers stay aligned.

    Heuristic, not a full Markdown parser. A fence is a line whose first
    non-space run is at least three backticks or tildes. Everything from a
    fence opener up to and including the matching closer is blanked.
    """
    out = []
    in_fence = False
    fence_char = ""
    for line in src.split("\n"):
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if is_fence:
            char = stripped[0]
            if not in_fence:
                in_fence = True
                fence_char = char
                out.append("")  # blank the opener line too
                continue
            if char == fence_char:
                in_fence = False
                fence_char = ""
                out.append("")  # blank the closer line
                continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    fp = data.get("tool_input", {}).get("file_path") or data.get(
        "tool_response", {}
    ).get("filePath")
    if not fp or not fp.endswith(CODE_EXT):
        sys.exit(0)

    try:
        with open(fp, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        sys.exit(0)

    orig_lines = content.split("\n")
    scanned = blank_md_code_fences(content) if fp.endswith(".md") else content
    scanned_lines = scanned.split("\n")

    findings = []
    for i, line in enumerate(scanned_lines, 1):
        if EM in line:
            # Report the ORIGINAL line so the user sees their actual source.
            excerpt = orig_lines[i - 1].strip()
            if len(excerpt) > 120:
                excerpt = excerpt[:117] + "..."
            findings.append(f"  {fp}:{i}: {excerpt}")

    if not findings:
        sys.exit(0)

    msg = (
        f"Em dash ({EM}) found. Per CLAUDE.md house style, em dashes are not "
        f"allowed in agent docs, code comments, or docstrings. Replace with a "
        f"hyphen, a comma, parentheses, or recast as two sentences:\n"
        + "\n".join(findings)
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": msg,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
