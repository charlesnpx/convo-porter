---
name: export-to-cursor
description: |
  Export the current Claude Code session into a new Cursor Agent chat.
  Use when transferring context to Cursor or continuing work there.
allowed-tools:
  - Bash
argument-hint: "[--tail N]"
---

# Export to Cursor

Inject the current Claude Code session into a new Cursor Agent chat. Cursor-target append is not supported.

1. Accept `--tail N` to export only the last N turns. Reject a target session ID.
2. Run:

   ```text
   __BINARY__ inject --current --source claude --target cursor
   ```

3. Report the turns exported, session path, and the full `cursor-agent --resume <id>` command from the CLI output.
