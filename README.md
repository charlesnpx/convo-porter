# convo-porter

Export and import conversations between **Claude Code** and **OpenAI Codex CLI**.

Both tools store sessions as JSONL with different schemas. convo-porter parses either format into portable markdown that can be imported into the other tool as background context.

## Install

```bash
./install.sh
```

This creates symlinks so both tools can find the commands/skills:
- Claude Code: `/export` and `/import` slash commands
- Codex CLI: `$convo-porter` and `$convo-import` skills

## Usage

### Direct CLI

```bash
# List sessions from both tools
python3 convo_porter.py list
python3 convo_porter.py list --source claude --limit 10

# Export the current session
python3 convo_porter.py export --current --source claude

# Export a specific session by ID (prefix match)
python3 convo_porter.py export ce68816b

# Export from Codex, last 20 turns only
python3 convo_porter.py export --current --source codex --tail 20

# Export with thinking blocks included
python3 convo_porter.py export --current --include-thinking
```

### From Claude Code

```
/export                     # Export current session
/export --source codex      # Export most recent Codex session
/export list                # Browse and pick a session
/import                     # Browse exports and pick one
/import path/to/export.md   # Import a specific file
```

### From Codex CLI

```
$convo-porter               # Export current session
$convo-porter list          # Browse sessions
$convo-import               # Browse exports and pick one
$convo-import path.md       # Import a specific file
```

## Export format

Exports are markdown files with YAML frontmatter, stored in `~/.claude/exports/` by default. Tool calls are wrapped in `<details>` tags for collapsibility. The format is designed to be human-readable and machine-parseable for import.

## Requirements

- Python 3.9+
- No external dependencies (stdlib only)
