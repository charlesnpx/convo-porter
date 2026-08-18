---
name: export-to-codex
description: Export the current Cursor Agent conversation into Codex CLI.
argument-hint: "[target-codex-session-id] [--tail N]"
disable-model-invocation: true
---

# Export to Codex

Export the current conversation into Codex CLI's native session format.

1. Determine the current harness without asking the user:
   - Use `cursor` when running in Cursor Agent (including when `CURSOR_AGENT_CHAT_ID` is present).
   - Use `claude` if a compatible host exposes this shared skill from Claude Code.
   - If already running in Codex, stop because source and target are the same.
2. Parse the arguments. A session ID means `--into <id>`; `--tail N` limits the exported turns.
3. Run one of these commands, substituting the detected source and preserving any requested flags:

   ```text
   __BINARY__ inject --current --source cursor --target codex
   __BINARY__ inject --current --source claude --target codex
   ```

4. Report the CLI's full `Open:` command and session path. Never shorten the session ID.
