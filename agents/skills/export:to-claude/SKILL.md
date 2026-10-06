---
name: "export:to-claude"
description: Export the current Claude Code, Codex, or Cursor Agent conversation into Claude Code, including from Claude Code itself.
argument-hint: "[target-claude-session-id] [--tail N]"
disable-model-invocation: true
allowed-tools:
  - Bash
---

# Export to Claude

Export the current conversation into Claude Code's native session format. Without a session ID this creates a new Claude Code session. Exporting from Claude Code into Claude Code is allowed: it copies the current conversation into a new Claude Code session, or appends it to another existing one.

1. Do not ask the user which harness is running; the CLI detects it from the session environment.
2. Parse the arguments. A session ID means `--into <id>`; `--tail N` limits the exported turns.
3. Run this command, adding any requested flags:

   ```text
   __BINARY__ inject --current --target claude
   ```

   If the CLI reports that it could not detect the harness, rerun with `--source claude`, `--source codex`, or `--source cursor` for the harness you are running in.

4. Report the turns exported, the `File:` path, and the CLI's `Open:` command (`claude --resume <id>`) verbatim. Never shorten the session ID.
