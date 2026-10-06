---
name: "export:to-cursor"
description: Export the current Claude Code, Codex, or Cursor Agent conversation into Cursor Agent, including from Cursor Agent itself.
argument-hint: "[--tail N]"
disable-model-invocation: true
allowed-tools:
  - Bash
---

# Export to Cursor

Export the current conversation into Cursor Agent's native session format. This always creates a new Cursor Agent chat; appending to an existing Cursor chat is not supported. Exporting from Cursor Agent into Cursor Agent is allowed and copies the current conversation into a new chat.

1. Do not ask the user which harness is running; the CLI detects it from the session environment.
2. Accept `--tail N`. Reject a target chat ID: Cursor imports always create a new chat.
3. Run this command, adding any requested flags:

   ```text
   __BINARY__ inject --current --target cursor
   ```

   If the CLI reports that it could not detect the harness, rerun with `--source claude`, `--source codex`, or `--source cursor` for the harness you are running in.

4. Report the turns exported, the `File:` path, and the CLI's `Open:` command (`cursor-agent --resume <id>`) verbatim. Never shorten the session ID.
