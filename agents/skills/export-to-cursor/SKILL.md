---
name: export-to-cursor
description: Export the current Codex conversation into a new Cursor Agent chat.
argument-hint: "[--tail N]"
disable-model-invocation: true
---

# Export to Cursor

Export the current conversation into a new Cursor Agent chat. Cursor-target append is not supported.

1. Determine the current harness without asking the user:
   - Use `codex` when running in Codex.
   - Use `claude` if a compatible host exposes this shared skill from Claude Code.
   - If already running in Cursor Agent, stop because source and target are the same.
2. Accept `--tail N`; reject a target session ID because Cursor imports always create a new chat.
3. Run one of these commands, substituting the detected source and preserving `--tail`:

   ```text
   __BINARY__ inject --current --source codex --target cursor
   __BINARY__ inject --current --source claude --target cursor
   ```

4. Report the CLI's full `Open:` command and session path. Never shorten the chat ID.
