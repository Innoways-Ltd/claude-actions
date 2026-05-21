#!/usr/bin/env python3
"""Extract the '## Summary' (or '## Answer') section from Claude's output.

Reads from stdin (typically /tmp/claude-job/output.log), finds the LAST
markdown heading (level 2 or 3) whose text matches the configured keywords
and prints the content from that heading up to the next same-or-higher-level
heading (or EOF).

Default keywords: summary | 汇总 | 摘要 | 总结  (case-insensitive).

You can override with:
    extract-summary.py [fallback_lines] [--keywords "summary|answer|答案"]

The end-detector matches headings at any level (h1-h6) so a level-1
heading after the section correctly terminates it.

If no such heading is found, falls back to the last N lines wrapped in
a triple-backtick code block (so raw non-markdown content still
displays cleanly).
"""
import argparse
import re
import sys


DEFAULT_KEYWORDS = r"(summary|汇总|摘要|总结)"
# For matching the heading itself: only h2/h3 (avoids treating a
# top-level title as the section).
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
# For detecting the end of the section: any level h1-h6.
ANY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def extract(text: str, fallback_lines: int = 50, keywords: str = DEFAULT_KEYWORDS) -> str:
    keyword_re = re.compile(keywords, re.IGNORECASE)
    lines = text.splitlines()

    last_idx = -1
    last_level = 0
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if not m:
            continue
        heading_text = m.group(2)
        if keyword_re.search(heading_text):
            last_idx = i
            last_level = len(m.group(1))

    if last_idx < 0:
        # Fallback: last N lines, wrapped in code block
        tail = lines[-fallback_lines:] if len(lines) > fallback_lines else lines
        body = "\n".join(tail).rstrip()
        return f"```\n{body}\n```"

    # End: next heading at the SAME or HIGHER level (h1 stops h2/h3 too).
    end_idx = len(lines)
    for j in range(last_idx + 1, len(lines)):
        m = ANY_HEADING_RE.match(lines[j])
        if m and len(m.group(1)) <= last_level:
            end_idx = j
            break

    return "\n".join(lines[last_idx:end_idx]).rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fallback_lines", nargs="?", type=int, default=50)
    parser.add_argument("--keywords", default=DEFAULT_KEYWORDS,
                        help="Regex of section keywords (default: summary|汇总|摘要|总结)")
    args = parser.parse_args()

    text = sys.stdin.read()
    print(extract(text, args.fallback_lines, args.keywords))
    return 0


if __name__ == "__main__":
    sys.exit(main())
