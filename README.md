# convo-porter

Transfer conversation context among **Claude Code**, **OpenAI Codex CLI**, and **Cursor Agent**.

Each harness stores conversations differently. convo-porter parses Claude and Codex JSONL plus Cursor's SQLite/protobuf graph, then injects portable conversation content into another harness's native format.

Imported sessions intentionally omit source model, provider, approval, mode, and other runtime settings. The destination harness uses its own configured defaults on the next generated turn.

## Install

```bash
pipx install git+https://github.com/charlesnpx/convo-porter.git
convo-porter install
convo-porter install --install --target all --json --install-root /tmp/porter-skill-stage
```

The first command installs the `convo-porter` binary. The second writes Claude commands and shared [Agent Skills](https://agentskills.io/) under `~/.agents/skills`, which both Codex and Cursor discover.
`--install-root` is for delegated installers such as `mise-en-place`; it stages
files under the supplied directory as if it were `$HOME` and reports those
staged absolute paths in JSON.

Requires Python 3.10+. No external dependencies (stdlib only).

## Usage

### From Claude Code

Use `/export-to-codex` or `/export-to-cursor`:

```
/export-to-codex              # export current session to a new Codex session
/export-to-codex --tail 10    # only the last 10 turns
/export-to-codex abc123       # append to existing Codex session abc123
/export-to-cursor             # create a new Cursor Agent chat
```

### From Codex CLI

Use `$export-to-claude` or `$export-to-cursor`:

```
$export-to-claude              # export current session to a new Claude session
$export-to-claude --tail 10    # only the last 10 turns
$export-to-claude abc123       # append to existing Claude session abc123
$export-to-cursor              # create a new Cursor Agent chat
```

### From Cursor Agent

Use `/export-to-claude` or `/export-to-codex`:

```
/export-to-claude              # create a new Claude Code session
/export-to-claude abc123       # append to an existing Claude session
/export-to-codex               # create a new Codex session
/export-to-codex abc123        # append to an existing Codex session
```

Codex and Cursor share the target-oriented skills installed under `~/.agents/skills`. A self-target skill may be visible in the shared list, but it refuses to export a harness into itself.

### Direct CLI

```bash
# List sessions from all three harnesses
convo-porter list
convo-porter list --source claude --limit 10

# Export a session to portable markdown
convo-porter export --current --source claude
convo-porter export ce68816b --tail 20
convo-porter export --current --include-thinking

# Inject a session into a target harness's native format
convo-porter inject --source codex --target claude --current
convo-porter inject abc123 --source claude --target codex --tail 10
convo-porter inject --current --source cursor --target claude
convo-porter inject --current --source codex --target cursor

# Append to an existing target session
convo-porter inject --source codex --target claude --current --into def456
```

### Commands

| Command | Description |
|---------|-------------|
| `list` | List available sessions from Claude Code, Codex CLI, and/or Cursor Agent |
| `export` | Export a session to portable markdown (saved to `~/.claude/exports/`) |
| `inject` | Parse a session from one harness and write it in another harness's native format |
| `install` | Write Claude commands to `~/.claude/` and shared skills to `~/.agents/` |

### Common flags

| Flag | Commands | Description |
|------|----------|-------------|
| `--source` | all | Filter by harness: `claude`, `codex`, or `cursor` (`all` for `list`) |
| `--current` | export, inject | Use the active session inferred from the current harness or workspace |
| `--tail N` | export, inject | Only include the last N turns |
| `--target` | inject | Target harness: `claude`, `codex`, or `cursor` |
| `--into ID` | inject | Append to Claude or Codex (Cursor-target append is not supported) |
| `--include-thinking` | export, inject | Include thinking/reasoning blocks |
| `--max-tool-lines` | export, inject | Max lines per tool output (default 50) |

## How it works

1. **Parse** the source session into a common intermediate representation (turns with roles, tool calls, and outputs)
2. **Convert** tool calls into portable target representations without carrying provider options
3. **Write** the result as a native session file that the target tool can resume

Cursor chats live under `~/.cursor/chats/<workspace-hash>/<chat-id>/`. convo-porter creates a content-addressed protobuf blob graph in `store.db` plus Cursor's discovery metadata. Imported tool calls remain structured in generic prompt history and are rendered as readable activity in the visible graph; Cursor-specific tool protobuf variants are not synthesized.

Large tool outputs (>10KB) are persisted to disk with a preview, matching Claude Code's native `tool-results/` format. Base64 image data is stripped automatically.

## Export format

The `export` command produces markdown with YAML frontmatter:

```markdown
---
source: claude-code
session_id: ce68816b-...
exported_at: 2026-03-19T12:00:00Z
cwd: /Users/you/project
model: claude-opus-4-6
turns: 12
---

## Turn 1 -- User (10:30:15)

What does this function do?

## Turn 2 -- Assistant (10:30:22)

<details>
<summary>Tool: Read -- src/main.py</summary>

...

</details>

It handles request routing...
```

Tool calls are wrapped in collapsible `<details>` tags. Exports are saved to `~/.claude/exports/` by default.

## License

MIT
