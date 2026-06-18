#!/usr/bin/env python3
"""Generate the Developer and Formula HTML entry points from the canonical
index.html so the three files can never drift apart.

index.html is the single source of truth. The two variants differ ONLY by:
  * <title> text
  * an extra `formula-mode` body class (formula view)

Mode behaviour itself is driven at runtime by the body class and by filename
checks (app.js detects index_developer.html; tia-shared-sync.js detects
index_formulas.html), so no other markup needs to differ.

Run after editing index.html:
    python scripts/build_html_variants.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "index.html"

TITLE_TAG = "<title>Traffic Impact Assessment</title>"
BODY_TAG = '<body class="app-locked input-color-mode">'

VARIANTS = {
    "index_developer.html": {
        "title": "<title>Traffic Impact Assessment - Developer</title>",
        "body": BODY_TAG,  # developer mode is driven by filename, not a body class
    },
    "index_formulas.html": {
        "title": "<title>Traffic Impact Assessment - Formula Detailed</title>",
        "body": '<body class="app-locked input-color-mode formula-mode">',
    },
}


def main() -> None:
    if not SOURCE.exists():
        sys.exit(f"Source not found: {SOURCE}")

    # Operate on bytes so the source's exact line endings (CRLF) and UTF-8
    # encoding are preserved byte-for-byte apart from the intended swaps.
    html = SOURCE.read_bytes().decode("utf-8")
    if TITLE_TAG not in html:
        sys.exit(f"Expected title tag not found in {SOURCE.name}: {TITLE_TAG!r}")
    if BODY_TAG not in html:
        sys.exit(f"Expected body tag not found in {SOURCE.name}: {BODY_TAG!r}")

    for filename, repl in VARIANTS.items():
        out = html.replace(TITLE_TAG, repl["title"], 1)
        if repl["body"] != BODY_TAG:
            out = out.replace(BODY_TAG, repl["body"], 1)
        dest = REPO / filename
        # Write raw bytes => no newline translation, preserving CRLF + UTF-8.
        dest.write_bytes(out.encode("utf-8"))
        print(f"  Wrote {filename} ({len(out):,} chars)")

    print("HTML variants regenerated from index.html.")


if __name__ == "__main__":
    main()
