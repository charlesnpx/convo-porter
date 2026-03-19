---
name: export-to-claude
description: >
  Export the current Codex session into Claude Code as a native session.
  Use when the user wants to transfer context to Claude Code or continue
  work there. Trigger on: export to claude, send to claude, transfer to
  claude, porter.
argument-hint: "[target-claude-session-id] [--tail N]"
---

# Export to Claude

Inject the current Codex session into Claude Code's native session format.

## Workflow

1. Parse the user's arguments:
   - **No arguments**: create a new Claude Code session.
   - **A session ID**: append to that existing Claude Code session. Pass it as `--into <id>`.
   - **`--tail N`**: only export the last N turns.

2. Run the inject command:

   - New session:
     ```
     python3 __REPO_DIR__/convo_porter.py inject --current --source codex --target claude
     ```
   - Append to existing Claude session:
     ```
     python3 __REPO_DIR__/convo_porter.py inject --current --source codex --target claude --into <session-id>
     ```

3. Report the result: show the `claude --resume <id>` command so the user can open it.
