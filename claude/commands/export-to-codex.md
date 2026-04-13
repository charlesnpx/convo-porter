---
name: export-to-codex
description: |
  Export the current Claude Code session into Codex CLI as a native session.
  Use when transferring context to Codex or continuing work there.
allowed-tools:
  - Bash
argument-hint: "[target-codex-session-id] [--tail N]"
---

# Export to Codex

Inject the current Claude Code session into Codex CLI's native session format.

## Workflow

1. Parse the user's arguments:
   - **No arguments**: create a new Codex session.
   - **A session ID**: append to that existing Codex session. Pass it as `--into <id>`.
   - **`--tail N`**: only export the last N turns.

2. Build and run the command:

   - New session:
     ```
     __BINARY__ inject --current --source claude --target codex
     ```
   - Append to existing Codex session:
     ```
     __BINARY__ inject --current --source claude --target codex --into <session-id>
     ```

3. Report the result from the CLI output. Include:
   - **Turns** exported (the number from the CLI output)
   - **Session file** path (the `File:` line from the CLI output)
   - **Resume command**: copy the `Open:` line from the CLI output verbatim — it is `codex resume <full-uuid>`. Do NOT shorten the UUID and do NOT change the subcommand (it is `resume`, not `--resume`).
