---
name: "export:to-codex"
description: Export the current Claude Code, Codex, or Cursor Agent conversation into Codex CLI, including from Codex CLI itself.
argument-hint: "[target-codex-session-id] [--tail N]"
disable-model-invocation: true
allowed-tools:
  - Bash
---

# Export to Codex

Export the current conversation into Codex CLI's native session format. Without a session ID this creates a new Codex session. Exporting from Codex CLI into Codex CLI is allowed: it copies the current conversation into a new Codex session, or appends it to another existing one.

1. Do not ask the user which harness is running; the CLI detects it from the session environment.
2. Parse the arguments. A session ID means `--into <id>`; `--tail N` limits the exported turns.
3. Run this command, adding any requested flags:

   ```text
   __BINARY__ inject --current --target codex
   ```

   If the CLI reports that it could not detect the harness, rerun with `--source claude`, `--source codex`, or `--source cursor` for the harness you are running in.

4. Report the turns exported, the `File:` path, and the CLI's `Open:` command (`codex resume <id>`) verbatim. Never shorten the session ID.
