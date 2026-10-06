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

The first command installs the `convo-porter` binary. The second writes the export skills to `~/.claude/skills` for Claude Code and to `~/.agents/skills`, which both Codex and Cursor discover ([Agent Skills](https://agentskills.io/)). It also removes the pre-0.4 `export-to-*` skills and Claude commands that convo-porter installed.
`--install-root` is for delegated installers such as `mise-en-place`; it stages
files under the supplied directory as if it were `$HOME` and reports those
staged absolute paths in JSON.

Requires Python 3.10+. No external dependencies (stdlib only).

## Usage

### From any harness

Every harness gets the same three skills: `export:to-claude`, `export:to-codex`, and `export:to-cursor`. Invoke them as `/export:to-codex` in Claude Code and Cursor Agent, or `$export:to-codex` in Codex CLI.

```
/export:to-codex              # export the current session to a new Codex session
/export:to-codex --tail 10    # only the last 10 turns
/export:to-codex abc123       # append to existing Codex session abc123
/export:to-claude             # export to a new Claude Code session
/export:to-cursor             # export to a new Cursor Agent chat
```

Exporting into the harness you are already running is allowed. For example, `$export:to-codex` from Codex copies the current conversation into a new Codex session, which is useful for starting a clean copy under a different model or provider. A session cannot be appended into itself.

The CLI detects the running harness from its session environment (`CLAUDECODE`, `CODEX_THREAD_ID`, or `CURSOR_AGENT_CHAT_ID`), so the skills do not pass `--source`.

### Codex sessions on other providers

Codex sessions created with a non-OpenAI provider, such as Claude through a Responses proxy, are ordinary Codex rollouts and export the same way. Codex's resume picker lists only threads whose provider matches the active one, so an imported Codex session is registered under the provider of the Codex session running the export, or else the top-level `model_provider` in `~/.codex/config.toml`, or else `openai`. `codex resume <id>` opens the session regardless of the provider it is registered under.

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
convo-porter inject --current --target codex      # source detected from the environment
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
| `inject` | Parse a session and write it in a harness's native format, including the same harness |
| `install` | Write export skills to `~/.claude/skills/` and `~/.agents/skills/` |

### Common flags

| Flag | Commands | Description |
|------|----------|-------------|
| `--source` | all | Filter by harness: `claude`, `codex`, or `cursor` (`all` for `list`); optional for `inject --current` |
| `--current` | export, inject | Use the active session inferred from the current harness or workspace |
| `--tail N` | export, inject | Only include the last N turns |
| `--target` | inject | Target harness: `claude`, `codex`, or `cursor`, including the source harness |
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
