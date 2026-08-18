---
name: export-to-claude
description: Export the current Codex or Cursor Agent conversation into Claude Code.
argument-hint: "[target-claude-session-id] [--tail N]"
disable-model-invocation: true
---

# Export to Claude

Export the current conversation into Claude Code's native session format.

1. Determine the current harness without asking the user:
   - Use `cursor` when running in Cursor Agent (including when `CURSOR_AGENT_CHAT_ID` is present).
   - Otherwise use `codex` when running in Codex.
   - If already running in Claude Code, stop because source and target are the same.
2. Parse the arguments. A session ID means `--into <id>`; `--tail N` limits the exported turns.
3. Run one of these commands, substituting the detected source and preserving any requested flags:

   ```text
   __BINARY__ inject --current --source codex --target claude
   __BINARY__ inject --current --source cursor --target claude
   ```

4. Report the CLI's full `Open:` command and session path. Never shorten the session ID.
