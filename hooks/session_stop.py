#!/usr/bin/env python3
"""Stop hook — extracts learnings from the session and stores them.

Sends a system message telling Claude to extract and save learnings
before the session ends.
"""

import json
import sys
import os


def main():
    result = {
        "systemMessage": (
            "HIVEMIND SESSION ENDING — Before closing:\n"
            "1. Extract any corrections/preferences the user gave this session\n"
            "2. For each, run: sqlite3 ~/hivemind.db \"INSERT INTO learnings (category, rule, context, confidence) "
            "VALUES ('<category>', '<rule>', '<context>', 0.7)\"\n"
            "   Categories: correction, preference, pattern, mistake, insight\n"
            "3. Post a summary message for other agents: sqlite3 ~/hivemind.db "
            "\"INSERT INTO messages (sender, channel, content, msg_type) "
            "VALUES ('session:closing', 'general', '<what was accomplished and what is next>', 'handoff')\"\n"
            "4. Mark this agent inactive: sqlite3 ~/hivemind.db "
            "\"UPDATE agents SET status='inactive', ended_at=CURRENT_TIMESTAMP "
            "WHERE pid=" + str(os.getpid()) + "\"\n"
            "5. Update primer.md as usual"
        )
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
