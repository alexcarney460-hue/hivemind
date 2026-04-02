---
description: Teach the hivemind — share a discovery, pattern, or technique so all agents on all devices learn it
argument-hint: "[category] [what you learned]"
allowed-tools: ["Bash"]
---

# Teach the Hivemind

Any agent can teach the entire network. The learning propagates to every future session on every device.

Parse `$ARGUMENTS` to extract category and the lesson.

## Categories
- **pattern** — a reusable approach that worked ("for Supabase RLS, always create a policy per table")
- **insight** — something discovered during work ("YieldRadar's API returns dates in UTC not local")  
- **technique** — a method that's faster/better ("use git worktrees instead of branches for parallel work")
- **warning** — something to avoid ("the /api/sync endpoint times out above 500 rows")
- **context** — project-specific knowledge others need ("Blue Label's Stripe is in test mode")

## Execution

Insert the learning with high confidence (agent-discovered learnings start at 0.7, human corrections at 0.8, manual teaches at 0.9):

```bash
sqlite3 ~/hivemind.db "INSERT INTO learnings (category, rule, context, source_session, confidence) VALUES ('$CATEGORY', '$RULE', 'Taught by agent on $(hostname) at $(date)', '$(hostname):teach', 0.9)"
```

Also broadcast to the message bus so active agents get it immediately:

```bash
sqlite3 ~/hivemind.db "INSERT INTO messages (sender, recipient, channel, content, msg_type, priority) VALUES ('$(hostname):teach', '*', 'learnings', 'NEW LEARNING [$CATEGORY]: $RULE', 'learning', 3)"
```

Confirm what was taught and how many agents will receive it:

```bash
echo "Learning stored."
sqlite3 ~/hivemind.db "SELECT COUNT(*) || ' active agents will receive this learning' FROM agents WHERE status='active'"
```

## Examples
- `/teach pattern "When querying Supabase from Next.js server components, always use the service role key not anon key"`
- `/teach warning "brain.db contacts table has duplicates — always dedupe by email before inserting"`
- `/teach technique "Use sqlite3 -json for machine-readable output instead of -column"`
- `/teach insight "Motion Ventures SMS list has 12% bounce rate — filter before bulk sends"`
- `/teach context "YieldRadar Supabase project not yet created — use alexcarney460 account"`
