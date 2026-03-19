#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
CODEX_DIR="$HOME/.codex"

echo "convo-porter installer"
echo "======================"
echo "Repo: $REPO_DIR"
echo ""

# ── Claude Code command ───────────────────────────────────────────────
mkdir -p "$CLAUDE_DIR/commands"

dst="$CLAUDE_DIR/commands/export-to-codex.md"
# Remove old symlink or file
[ -L "$dst" ] && rm "$dst"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/claude/commands/export-to-codex.md" > "$dst"
echo "  Installed $dst"

# ── Codex skill ──────────────────────────────────────────────────────
mkdir -p "$CODEX_DIR/skills/export-to-claude/agents"

dst="$CODEX_DIR/skills/export-to-claude/SKILL.md"
# Remove old symlink to directory if present
[ -L "$CODEX_DIR/skills/export-to-claude" ] && rm "$CODEX_DIR/skills/export-to-claude" && mkdir -p "$CODEX_DIR/skills/export-to-claude/agents"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/codex/skills/export-to-claude/SKILL.md" > "$dst"
echo "  Installed $dst"

cp "$REPO_DIR/codex/skills/export-to-claude/agents/openai.yaml" "$CODEX_DIR/skills/export-to-claude/agents/openai.yaml"
echo "  Installed $CODEX_DIR/skills/export-to-claude/agents/openai.yaml"

echo ""
echo "Done. Available commands:"
echo "  Claude Code:  /export-to-codex"
echo "  Codex CLI:    \$export-to-claude"
