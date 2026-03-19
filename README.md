# convo-porter

Transfer conversation context between **Claude Code** and **OpenAI Codex CLI**.

Both tools store sessions as JSONL with different schemas. convo-porter parses either format and injects it into the other tool's native session format, so context carries over seamlessly when switching between tools.

## Install

```bash
pipx install git+https://github.com/charlesnpx/convo-porter.git
convo-porter install
```

The first command installs the `convo-porter` binary. The second writes slash-command and skill templates so both tools can invoke it natively.

Requires Python 3.10+. No external dependencies (stdlib only).

## Usage

### From Claude Code

Use the `/export-to-codex` slash command:

```
/export-to-codex              # export current session to a new Codex session
/export-to-codex --tail 10    # only the last 10 turns
/export-to-codex abc123       # append to existing Codex session abc123
```

### From Codex CLI

Use the `$export-to-claude` skill:

```
$export-to-claude              # export current session to a new Claude session
$export-to-claude --tail 10    # only the last 10 turns
$export-to-claude abc123       # append to existing Claude session abc123
```

### Direct CLI

```bash
# List sessions from both tools
convo-porter list
convo-porter list --source claude --limit 10

# Export a session to portable markdown
convo-porter export --current --source claude
convo-porter export ce68816b --tail 20
convo-porter export --current --include-thinking

# Inject a session into the other tool's native format
convo-porter inject --source codex --target claude --current
convo-porter inject abc123 --source claude --target codex --tail 10

# Append to an existing target session
convo-porter inject --source codex --target claude --current --into def456
```

### Commands

| Command | Description |
|---------|-------------|
| `list` | List available sessions from Claude Code and/or Codex CLI |
| `export` | Export a session to portable markdown (saved to `~/.claude/exports/`) |
| `inject` | Parse a session from one tool and write it as a native session in the other |
| `install` | Write slash-command and skill templates to `~/.claude/` and `~/.codex/` |

### Common flags

| Flag | Commands | Description |
|------|----------|-------------|
| `--source` | all | Filter by tool: `claude` or `codex` |
| `--current` | export, inject | Use the current active session (detected via PID) |
| `--tail N` | export, inject | Only include the last N turns |
| `--target` | inject | Target tool: `claude` or `codex` |
| `--into ID` | inject | Append to an existing target session (prefix match) |
| `--include-thinking` | export, inject | Include thinking/reasoning blocks |
| `--max-tool-lines` | export, inject | Max lines per tool output (default 50) |

## How it works

1. **Parse** the source session's JSONL into a common intermediate representation (turns with roles, tool calls, and outputs)
2. **Convert** tool calls between formats (e.g., Codex `function_call` to Claude `tool_use`/`tool_result`)
3. **Write** the result as a native session file that the target tool can resume

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
