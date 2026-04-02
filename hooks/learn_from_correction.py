#!/usr/bin/env python3
"""UserPromptSubmit hook — detects corrections in user messages.

Scans for correction signals ("don't", "stop", "wrong", "no,", "not that")
and flags them for learning extraction.
"""

import json
import sys
import re

CORRECTION_PATTERNS = [
    r"\bdon'?t\b",
    r"\bstop\b",
    r"\bwrong\b",
    r"^no[,.\s]",
    r"\bnot that\b",
    r"\bnever\b",
    r"\bavoid\b",
    r"\bI said\b",
    r"\bI told you\b",
    r"\bthat'?s not\b",
    r"\bwhy did you\b",
    r"\bundo\b",
    r"\brevert\b",
]


def main():
    try:
        input_data = json.load(sys.stdin)
        content = input_data.get("content", "")

        if not content:
            print(json.dumps({}))
            sys.exit(0)

        # Check for correction signals
        is_correction = any(re.search(p, content, re.IGNORECASE) for p in CORRECTION_PATTERNS)

        if is_correction:
            result = {
                "systemMessage": (
                    "CORRECTION DETECTED in user message. After addressing it, "
                    "extract the lesson and save to hivemind:\n"
                    "sqlite3 ~/hivemind.db \"INSERT INTO learnings "
                    "(category, rule, context, confidence) VALUES "
                    "('correction', '<what to do differently>', "
                    f"'User said: {content[:100]}', 0.8)\""
                )
            }
            print(json.dumps(result))
        else:
            print(json.dumps({}))

    except Exception:
        print(json.dumps({}))

    sys.exit(0)


if __name__ == "__main__":
    main()
