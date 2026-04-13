#!/usr/bin/env python3
"""convo-porter: Export conversations between Claude Code and Codex CLI to portable markdown."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CLAUDE_DIR = Path.home() / ".claude"
CODEX_DIR = Path.home() / ".codex"
EXPORTS_DIR = CLAUDE_DIR / "exports"


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class ToolInteraction:
    tool_name: str
    input_summary: str
    output: str = ""
    call_id: str = ""


@dataclass
class Turn:
    role: str  # "user", "assistant", "compaction"
    content: str
    timestamp: str = ""
    thinking: str = ""
    tools: list[ToolInteraction] = field(default_factory=list)


@dataclass
class ConversationMeta:
    source: str = ""
    session_id: str = ""
    cwd: str = ""
    git_branch: str = ""
    model: str = ""


@dataclass
class Conversation:
    meta: ConversationMeta = field(default_factory=ConversationMeta)
    turns: list[Turn] = field(default_factory=list)


# ─── Session Discovery ────────────────────────────────────────────────────────


def encode_project_path(path: str) -> str:
    """Encode a project path to Claude's directory naming convention."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", path)


def _reverse_lines(path: Path):
    """Yield lines from a file in reverse order, reading chunks from the end."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        remainder = b""
        while pos > 0:
            chunk_size = min(8192, pos)
            pos -= chunk_size
            f.seek(pos)
            chunk = f.read(chunk_size) + remainder
            lines = chunk.split(b"\n")
            remainder = lines[0]
            for line in reversed(lines[1:]):
                stripped = line.strip()
                if stripped:
                    yield stripped.decode("utf-8", errors="replace")
        if remainder.strip():
            yield remainder.strip().decode("utf-8", errors="replace")


def discover_claude_sessions(limit: int = 20) -> list:
    """Discover Claude Code sessions from history.jsonl (reverse-scanned)."""
    history_path = CLAUDE_DIR / "history.jsonl"
    if not history_path.exists():
        return []

    sessions = {}
    for line in _reverse_lines(history_path):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"warn: skipping malformed history entry: {e}", file=sys.stderr)
            continue
        sid = record.get("sessionId")
        if not sid or sid in sessions:
            continue
        project = record.get("project", "")
        encoded = encode_project_path(project)
        jsonl_path = CLAUDE_DIR / "projects" / encoded / f"{sid}.jsonl"
        if jsonl_path.exists():
            sessions[sid] = {
                "session_id": sid,
                "source": "claude",
                "project": project,
                "path": str(jsonl_path),
                "display": record.get("display", ""),
                "timestamp": record.get("timestamp", 0),
            }
        if len(sessions) >= limit:
            break
    return list(sessions.values())


def discover_codex_sessions(limit: int = 20) -> list:
    """Discover Codex sessions from session files."""
    sessions_dir = CODEX_DIR / "sessions"
    if not sessions_dir.exists():
        return []

    files = sorted(
        sessions_dir.rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    results = []
    for f in files[:limit]:
        meta = {}
        try:
            with open(f) as fh:
                for fline in fh:
                    fline = fline.strip()
                    if not fline:
                        continue
                    rec = json.loads(fline)
                    if rec.get("type") == "session_meta":
                        meta = rec.get("payload", {})
                        break
        except (json.JSONDecodeError, OSError) as e:
            print(f"warn: could not read Codex session {f}: {e}", file=sys.stderr)

        sid = meta.get("id", f.stem)
        cwd = meta.get("cwd", "")
        git_info = meta.get("git", {})
        results.append({
            "session_id": sid,
            "source": "codex",
            "project": cwd,
            "path": str(f),
            "display": "",
            "timestamp": int(f.stat().st_mtime * 1000),
            "git_branch": git_info.get("branch", ""),
        })
    return results


def find_current_claude_session() -> Optional[dict]:
    """Find the current Claude Code session by walking ancestor PIDs."""
    pid = os.getpid()
    sessions_dir = CLAUDE_DIR / "sessions"
    if not sessions_dir.exists():
        return None

    visited = set()
    while pid and pid > 1 and pid not in visited:
        visited.add(pid)
        session_file = sessions_dir / f"{pid}.json"
        if session_file.exists():
            try:
                data = json.loads(session_file.read_text())
                sid = data.get("sessionId", "")
                cwd = data.get("cwd", "")
                encoded = encode_project_path(cwd)
                jsonl_path = CLAUDE_DIR / "projects" / encoded / f"{sid}.jsonl"
                if jsonl_path.exists():
                    return {
                        "session_id": sid,
                        "source": "claude",
                        "project": cwd,
                        "path": str(jsonl_path),
                    }
            except (json.JSONDecodeError, OSError) as e:
                print(f"warn: could not read session file {session_file}: {e}",
                      file=sys.stderr)
        try:
            result = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True, text=True, timeout=5,
            )
            pid = int(result.stdout.strip())
        except (ValueError, subprocess.SubprocessError):
            break
    return None


def find_current_codex_session() -> Optional[dict]:
    """Find the most recent Codex session."""
    sessions = discover_codex_sessions(limit=1)
    return sessions[0] if sessions else None


# ─── Unified Session Resolution ──────────────────────────────────────────────


def resolve_session(session_id=None, current=False, source=None) -> dict:
    """Unified session resolution: --current, prefix match, or most-recent fallback.

    Raises SystemExit on failure (not found, ambiguous prefix).
    """
    if current:
        session = None
        if source in ("claude", None):
            session = find_current_claude_session()
        if not session and source in ("codex", None):
            session = find_current_codex_session()
        if not session:
            print("Could not detect current session.", file=sys.stderr)
            sys.exit(1)
        return session

    if session_id:
        pool = []
        if source in ("claude", None):
            pool.extend(discover_claude_sessions(limit=100))
        if source in ("codex", None):
            pool.extend(discover_codex_sessions(limit=100))
        matches = [s for s in pool if s["session_id"].startswith(session_id)]
        if not matches:
            print(f"Session '{session_id}' not found.", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(f"Ambiguous prefix '{session_id}': matches {len(matches)} sessions "
                  f"(use a longer prefix).", file=sys.stderr)
            sys.exit(1)
        return matches[0]

    # Fallback: try current, then most recent
    session = None
    if source in ("claude", None):
        session = find_current_claude_session()
    if not session and source in ("codex", None):
        session = find_current_codex_session()
    if not session:
        candidates = []
        if source in ("claude", None):
            candidates.extend(discover_claude_sessions(limit=1))
        if source in ("codex", None):
            candidates.extend(discover_codex_sessions(limit=1))
        if candidates:
            candidates.sort(key=lambda s: s.get("timestamp", 0), reverse=True)
            session = candidates[0]
    if not session:
        print("No session found.", file=sys.stderr)
        sys.exit(1)
    return session


def _print_resolved(session: dict) -> None:
    """Print which session was resolved, so the user can catch mistakes."""
    sid = session["session_id"][:8]
    source = session["source"]
    project = session.get("project", "")
    display = session.get("display", "")
    label = display[:60] if display else project
    print(f"Resolved {source} session {sid} ({label})", file=sys.stderr)


# ─── Tool Input Summarization ─────────────────────────────────────────────────


def summarize_claude_tool(name: str, input_data: dict) -> str:
    """Produce a short label for a Claude Code tool call."""
    if name in ("Read", "Edit", "Write"):
        return input_data.get("file_path", str(input_data)[:200])
    if name == "Bash":
        cmd = input_data.get("command", "")
        return cmd[:200] + ("..." if len(cmd) > 200 else "")
    if name in ("Grep", "Glob"):
        return input_data.get("pattern", str(input_data)[:200])
    if name == "Agent":
        return input_data.get("description", str(input_data)[:200])
    s = str(input_data)
    return s[:200] + ("..." if len(s) > 200 else "")


def summarize_codex_tool(name: str, arguments) -> str:
    """Produce a short label for a Codex tool call."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (json.JSONDecodeError, TypeError):
        return str(arguments)[:200]

    if name in ("exec_command", "shell"):
        cmd = args.get("cmd", args.get("command", ""))
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        s = str(cmd)
        return s[:200] + ("..." if len(s) > 200 else "")
    if name == "apply_patch":
        patch = str(args)
        match = re.search(r"[ab]/(\S+)", patch)
        return match.group(1) if match else patch[:200]
    s = str(args)
    return s[:200] + ("..." if len(s) > 200 else "")


# ─── Truncation ───────────────────────────────────────────────────────────────


def truncate_block(text: str, max_lines: int) -> str:
    """Keep first half + last half with a truncation marker if text exceeds max_lines."""
    if not text:
        return text
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    half = max_lines // 2
    removed = len(lines) - max_lines
    return "\n".join(
        lines[:half] + [f"[... {removed} lines truncated ...]"] + lines[-half:]
    )


# ─── Claude Code Parser ──────────────────────────────────────────────────────


CLAUDE_SKIP_TYPES = frozenset({
    "file-history-snapshot", "system", "last-prompt",
    "custom-title", "queue-operation", "agent-name",
})


def parse_claude_session(path: str, opts) -> Conversation:
    """Parse a Claude Code session JSONL into a Conversation."""
    conv = Conversation()
    conv.meta.source = "claude-code"

    session_dir = Path(path).parent / Path(path).stem
    tool_results_dir = session_dir / "tool-results"

    pending_tools: dict = {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"warn: skipping malformed Claude record: {e}", file=sys.stderr)
                continue

            rtype = record.get("type", "")
            if rtype in CLAUDE_SKIP_TYPES:
                continue
            if record.get("isSidechain"):
                continue

            timestamp = record.get("timestamp", "")
            message = record.get("message", {})

            # Populate meta from first non-sidechain user record
            if rtype == "user" and not conv.meta.session_id:
                conv.meta.session_id = record.get("sessionId", "")
                conv.meta.cwd = record.get("cwd", "")
                conv.meta.git_branch = record.get("gitBranch", "")

            if rtype == "user":
                content = message.get("content", "")
                if isinstance(content, str):
                    conv.turns.append(Turn(
                        role="user", content=content, timestamp=timestamp,
                    ))
                elif isinstance(content, list):
                    for block in content:
                        if block.get("type") != "tool_result":
                            continue
                        tool_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")
                        # Normalise list-of-blocks to string
                        if isinstance(result_content, list):
                            parts = []
                            for rb in result_content:
                                if isinstance(rb, dict):
                                    parts.append(rb.get("text", str(rb)))
                                else:
                                    parts.append(str(rb))
                            result_content = "\n".join(parts)
                        result_content = str(result_content)
                        # Resolve persisted-output references
                        if "<persisted-output" in result_content or not result_content:
                            persisted = tool_results_dir / f"{tool_id}.txt"
                            if persisted.exists():
                                try:
                                    result_content = persisted.read_text()
                                except OSError:
                                    result_content = "[Output file not found]"
                            elif not result_content:
                                result_content = "[Output file not found]"
                        if tool_id in pending_tools:
                            pending_tools[tool_id].output = truncate_block(
                                result_content, opts.max_tool_lines,
                            )

            elif rtype == "assistant":
                content_blocks = message.get("content", [])
                if not isinstance(content_blocks, list):
                    continue

                if not conv.meta.model:
                    conv.meta.model = message.get("model", "")

                text_parts, thinking_parts, tools = [], [], []

                for block in content_blocks:
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "thinking" and opts.include_thinking:
                        thinking_parts.append(block.get("thinking", ""))
                    elif btype == "tool_use":
                        tool_id = block.get("id", "")
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {})
                        ti = ToolInteraction(
                            tool_name=tool_name,
                            input_summary=summarize_claude_tool(tool_name, tool_input),
                            call_id=tool_id,
                        )
                        tools.append(ti)
                        pending_tools[tool_id] = ti

                conv.turns.append(Turn(
                    role="assistant",
                    content="\n\n".join(text_parts),
                    timestamp=timestamp,
                    thinking="\n\n".join(thinking_parts),
                    tools=tools,
                ))

            elif rtype == "progress":
                data = record.get("data", {})
                if data.get("type") == "hook_progress":
                    continue

    return conv


# ─── Codex Parser ─────────────────────────────────────────────────────────────


CODEX_SYSTEM_MARKERS = (
    "environment_context", "AGENTS.md", "# System Instructions",
    "You are operating", "Current working directory:",
    "# Codex CLI", "platform:", "shell:",
)


def _is_system_context(text: str) -> bool:
    """Return True if text looks like Codex system context, not user input.

    Fragile: these markers are derived from Codex's current system prompt format.
    If Codex changes its prompt structure, this heuristic may silently include
    system context in user turns or silently drop real user input.
    """
    head = text[:500]
    return any(m in head for m in CODEX_SYSTEM_MARKERS)


def _strip_codex_cmd_wrapper(output) -> str:
    """Strip Command:/.../Output: prefix from Codex exec_command results."""
    if not isinstance(output, str):
        output = str(output)
    m = re.match(r"^Command:.*?\nOutput:\n(.*)", output, re.DOTALL)
    return m.group(1) if m else output


def parse_codex_session(path: str, opts) -> Conversation:
    """Parse a Codex session JSONL into a Conversation."""
    conv = Conversation()
    conv.meta.source = "codex"

    pending_tools: dict = {}
    pending_thinking = ""

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"warn: skipping malformed Codex record: {e}", file=sys.stderr)
                continue

            rtype = record.get("type", "")
            timestamp = record.get("timestamp", "")
            payload = record.get("payload", {})

            # ── session_meta ──
            if rtype == "session_meta":
                conv.meta.session_id = payload.get("id", "")
                conv.meta.cwd = payload.get("cwd", "")
                git = payload.get("git", {})
                conv.meta.git_branch = git.get("branch", "")
                continue

            # ── turn_context ──
            if rtype == "turn_context":
                if not conv.meta.model:
                    conv.meta.model = payload.get("model", "")
                continue

            # ── event_msg ── skip
            if rtype == "event_msg":
                continue

            # ── compacted ──
            if rtype == "compacted":
                summary = payload.get("message", "")
                if summary:
                    conv.turns.append(Turn(
                        role="compaction", content=summary, timestamp=timestamp,
                    ))
                continue

            # ── response_item ──
            if rtype != "response_item":
                continue

            ptype = payload.get("type", "")

            # -- message --
            if ptype == "message":
                role = payload.get("role", "")
                if role == "developer":
                    continue
                content_blocks = payload.get("content", [])
                text_parts = []
                for block in content_blocks:
                    btype = block.get("type", "")
                    if btype == "input_text":
                        text = block.get("text", "")
                        if role == "user" and _is_system_context(text):
                            continue
                        text_parts.append(text)
                    elif btype == "output_text":
                        text_parts.append(block.get("text", ""))
                if not text_parts:
                    continue
                combined = "\n\n".join(text_parts)
                if role == "user":
                    conv.turns.append(Turn(
                        role="user", content=combined, timestamp=timestamp,
                    ))
                elif role == "assistant":
                    turn = Turn(
                        role="assistant", content=combined, timestamp=timestamp,
                    )
                    if pending_thinking:
                        turn.thinking = pending_thinking
                        pending_thinking = ""
                    conv.turns.append(turn)

            # -- reasoning --
            elif ptype == "reasoning":
                if not opts.include_thinking:
                    continue
                raw = payload.get("summary", "")
                if isinstance(raw, list):
                    text = "\n".join(
                        s.get("text", str(s)) if isinstance(s, dict) else str(s)
                        for s in raw
                    )
                else:
                    text = str(raw) if raw else ""
                if text:
                    # Attach to previous assistant turn, or buffer
                    if conv.turns and conv.turns[-1].role == "assistant":
                        conv.turns[-1].thinking = text
                    else:
                        pending_thinking = text

            # -- function_call --
            elif ptype == "function_call":
                name = payload.get("name", "")
                call_id = payload.get("call_id", "")
                arguments = payload.get("arguments", "{}")
                ti = ToolInteraction(
                    tool_name=name,
                    input_summary=summarize_codex_tool(name, arguments),
                    call_id=call_id,
                )
                pending_tools[call_id] = ti
                if conv.turns and conv.turns[-1].role == "assistant":
                    conv.turns[-1].tools.append(ti)
                else:
                    conv.turns.append(Turn(
                        role="assistant", content="", timestamp=timestamp,
                        tools=[ti],
                    ))

            # -- function_call_output --
            elif ptype == "function_call_output":
                call_id = payload.get("call_id", "")
                output = payload.get("output", "")
                output = _strip_codex_cmd_wrapper(output)
                if call_id in pending_tools:
                    pending_tools[call_id].output = truncate_block(
                        output, opts.max_tool_lines,
                    )

            # -- custom_tool_call --
            elif ptype == "custom_tool_call":
                name = payload.get("name", "")
                call_id = payload.get("call_id", "")
                input_data = payload.get("input", "{}")
                ti = ToolInteraction(
                    tool_name=name,
                    input_summary=summarize_codex_tool(name, input_data),
                    call_id=call_id,
                )
                pending_tools[call_id] = ti
                if conv.turns and conv.turns[-1].role == "assistant":
                    conv.turns[-1].tools.append(ti)
                else:
                    conv.turns.append(Turn(
                        role="assistant", content="", timestamp=timestamp,
                        tools=[ti],
                    ))

            # -- custom_tool_call_output --
            elif ptype == "custom_tool_call_output":
                call_id = payload.get("call_id", "")
                output = payload.get("output", "")
                if call_id in pending_tools:
                    pending_tools[call_id].output = truncate_block(
                        str(output), opts.max_tool_lines,
                    )

            # -- web_search_call --
            elif ptype == "web_search_call":
                if conv.turns and conv.turns[-1].role == "assistant":
                    conv.turns[-1].tools.append(ToolInteraction(
                        tool_name="web_search",
                        input_summary="[Web search performed]",
                    ))

    return conv


# ─── Markdown Renderer ────────────────────────────────────────────────────────


def _parse_timestamp(ts) -> Optional[datetime]:
    """Parse an ISO timestamp string or millisecond int to datetime."""
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        return None


def _format_time(ts) -> str:
    dt = _parse_timestamp(ts)
    return dt.strftime("%H:%M:%S") if dt else ""


def _format_date(ts) -> str:
    dt = _parse_timestamp(ts)
    return dt.strftime("%Y-%m-%d") if dt else ""


def render_markdown(conv: Conversation, opts) -> str:
    """Render a Conversation to portable markdown."""
    meta = conv.meta
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    first_ts = conv.turns[0].timestamp if conv.turns else ""
    date = _format_date(first_ts) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    short_id = meta.session_id[:8] if meta.session_id else "unknown"
    exportable_count = sum(1 for t in conv.turns if t.role in ("user", "assistant"))

    lines = [
        "---",
        f"source: {meta.source}",
        f"session_id: {meta.session_id}",
        f"exported_at: {now}",
    ]
    if meta.cwd:
        lines.append(f"cwd: {meta.cwd}")
    if meta.git_branch:
        lines.append(f"git_branch: {meta.git_branch}")
    if meta.model:
        lines.append(f"model: {meta.model}")
    lines.append(f"turns: {exportable_count}")
    lines.extend(["---", ""])

    # Header
    lines.append("# Conversation Export")
    lines.append("")
    lines.append(f"**Source**: {meta.source} | **Session**: `{short_id}` | **Date**: {date}")
    header_extra = []
    if meta.cwd:
        header_extra.append(f"**CWD**: `{meta.cwd}`")
    if meta.git_branch:
        header_extra.append(f"**Branch**: `{meta.git_branch}`")
    if header_extra:
        lines.append(" | ".join(header_extra))
    lines.extend(["", "---"])

    # Turns
    turn_num = 0
    for turn in conv.turns:
        if turn.role == "compaction":
            time_str = _format_time(turn.timestamp)
            time_part = f" ({time_str})" if time_str else ""
            lines.extend(["", f"## Context Compaction{time_part}", ""])
            for cline in turn.content.split("\n"):
                lines.append(f"> {cline}")
            lines.extend(["", "---"])
            continue

        turn_num += 1
        role_label = "User" if turn.role == "user" else "Assistant"
        time_str = _format_time(turn.timestamp)
        time_part = f" ({time_str})" if time_str else ""

        lines.extend(["", f"## Turn {turn_num} -- {role_label}{time_part}", ""])

        if turn.thinking:
            lines.extend([
                "<details>",
                "<summary>Thinking</summary>",
                "",
                turn.thinking,
                "",
                "</details>",
                "",
            ])

        if turn.content:
            lines.extend([turn.content, ""])

        for tool in turn.tools:
            summary_label = f"Tool: {tool.tool_name}"
            if tool.input_summary:
                summary_label += f" -- {tool.input_summary}"
            lines.extend(["<details>", f"<summary>{summary_label}</summary>", ""])
            if tool.output:
                lines.extend(["```", tool.output, "```"])
            else:
                lines.append("*(no output captured)*")
            lines.extend(["", "</details>", ""])

        lines.append("---")

    return "\n".join(lines)


# ─── List Command ─────────────────────────────────────────────────────────────


def cmd_list(args):
    """List available sessions from both tools."""
    sessions = []
    if args.source in ("claude", "both"):
        sessions.extend(discover_claude_sessions(limit=args.limit))
    if args.source in ("codex", "both"):
        sessions.extend(discover_codex_sessions(limit=args.limit))

    sessions.sort(key=lambda s: s.get("timestamp", 0), reverse=True)
    sessions = sessions[: args.limit]

    if not sessions:
        print("No sessions found.")
        return

    print(f"{'Source':<10} {'Session ID':<40} {'Project':<50} {'Display'}")
    print("-" * 140)
    for s in sessions:
        sid = s["session_id"][:36]
        project = s.get("project", "")
        if len(project) > 48:
            project = "..." + project[-45:]
        display = s.get("display", "")[:50]
        print(f"{s['source']:<10} {sid:<40} {project:<50} {display}")


# ─── Export Command ───────────────────────────────────────────────────────────


def cmd_export(args):
    """Export a session to portable markdown."""
    session = resolve_session(args.session_id, args.current, args.source)
    _print_resolved(session)

    # Parse
    source = session["source"]
    path = session["path"]

    if source == "claude":
        conv = parse_claude_session(path, args)
    else:
        conv = parse_codex_session(path, args)

    # Apply --tail
    if args.tail and args.tail > 0:
        conv.turns = conv.turns[-args.tail :]

    # Check for empty
    exportable = [t for t in conv.turns if t.role in ("user", "assistant")]
    if not exportable:
        print("No exportable turns in this session.", file=sys.stderr)
        sys.exit(1)

    # Render
    md = render_markdown(conv, args)

    # Write output
    if args.output:
        out_path = Path(args.output)
    else:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        short_id = conv.meta.session_id[:8] if conv.meta.session_id else "unknown"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = EXPORTS_DIR / f"{source}-{short_id}-{ts}.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)

    size_kb = out_path.stat().st_size / 1024
    if size_kb > 500:
        print(
            f"Warning: output is {size_kb:.0f}KB -- consider using --tail N",
            file=sys.stderr,
        )
    print(f"Exported {len(exportable)} turns to {out_path} ({size_kb:.1f}KB)")


# ─── Session Writers ──────────────────────────────────────────────────────────


_BASE64_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]{100,}")
_PERSIST_THRESHOLD = 10_000  # bytes — persist outputs larger than this
_PREVIEW_SIZE = 2048


def _strip_base64(text: str) -> str:
    """Replace base64 data URIs with a placeholder."""
    if not isinstance(text, str):
        text = str(text)
    return _BASE64_RE.sub("[base64 image omitted]", text)


def _persist_tool_output(output: str, call_id: str, tool_results_dir: Path) -> str:
    """Persist large tool output to disk, return inline content for the JSONL.

    Small outputs are returned as-is.  Large outputs are written to
    ``tool_results_dir/<call_id>.txt`` and replaced with a
    ``<persisted-output>`` reference plus a 2 KB preview — the same
    format Claude Code uses natively.
    """
    output = _strip_base64(output)

    if len(output) <= _PERSIST_THRESHOLD:
        return output

    tool_results_dir.mkdir(parents=True, exist_ok=True)
    # Use a short filename derived from the call_id
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", call_id)[-16:] or "out"
    out_path = tool_results_dir / f"{safe_id}.txt"
    out_path.write_text(output)

    size_kb = len(output) / 1024
    preview = output[:_PREVIEW_SIZE]
    return (
        f"<persisted-output>\n"
        f"Output too large ({size_kb:.1f}KB). "
        f"Full output saved to: {out_path}\n\n"
        f"Preview (first 2KB):\n{preview}\n"
        f"</persisted-output>"
    )


def _sanitize_output(text: str, max_lines: int) -> str:
    """Strip base64, truncate — used by the Codex writer which has no tool-results dir."""
    text = _strip_base64(text)
    text = truncate_block(text, max_lines)
    if len(text) > _PERSIST_THRESHOLD * 3:
        keep = _PERSIST_THRESHOLD
        text = text[:keep] + "\n[... content truncated ...]\n" + text[-_PREVIEW_SIZE:]
    return text


def _atomic_write_jsonl(path: Path, records: list) -> None:
    """Write records to a JSONL file atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


# Maps source tool names → Claude Code tool names for tool_use blocks.
_CLAUDE_TOOL_MAP = {
    "exec_command": "Bash", "shell": "Bash", "write_stdin": "Bash",
    "apply_patch": "Edit", "view_image": "Read",
    # Claude-native names pass through
    "Read": "Read", "Edit": "Edit", "Write": "Write", "Bash": "Bash",
    "Grep": "Grep", "Glob": "Glob", "Agent": "Agent",
}


def _to_claude_tool_use(tool: ToolInteraction) -> dict:
    """Build a Claude Code tool_use content block from a ToolInteraction."""
    name = _CLAUDE_TOOL_MAP.get(tool.tool_name, "Bash")
    if name == "Bash":
        inp = {"command": tool.input_summary or tool.tool_name}
    elif name in ("Read", "Write"):
        inp = {"file_path": tool.input_summary or "unknown"}
    elif name == "Edit":
        inp = {"file_path": tool.input_summary or "unknown",
               "old_string": "", "new_string": ""}
    elif name in ("Grep", "Glob"):
        inp = {"pattern": tool.input_summary or "*"}
    elif name == "Agent":
        inp = {"prompt": tool.input_summary or "", "description": tool.input_summary or ""}
    else:
        inp = {"command": tool.input_summary or tool.tool_name}
    return {"type": "tool_use", "id": tool.call_id, "name": name, "input": inp}


def _find_target_session(target_tool: str, target_id: str) -> Optional[dict]:
    """Find a target session by ID prefix in the given tool."""
    pool = (discover_claude_sessions(limit=100) if target_tool == "claude"
            else discover_codex_sessions(limit=100))
    matches = [s for s in pool if s["session_id"].startswith(target_id)]
    if not matches:
        return None
    if len(matches) > 1:
        print(f"Ambiguous target prefix '{target_id}': matches {len(matches)} "
              f"sessions in {target_tool} (use a longer prefix).", file=sys.stderr)
        sys.exit(1)
    return matches[0]


def _last_claude_uuid(path: str) -> Optional[str]:
    """Read the last record's uuid from a Claude JSONL for chaining."""
    last_uuid = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if "uuid" in rec:
                    last_uuid = rec["uuid"]
            except json.JSONDecodeError:
                continue
    return last_uuid


def write_as_claude_session(conv: Conversation, append_to: Optional[dict] = None,
                            max_tool_lines: int = 50) -> tuple:
    """Write a Conversation as Claude Code JSONL with proper tool_use/tool_result pairing.

    Large tool outputs are persisted to a tool-results/ directory with a
    <persisted-output> reference in the JSONL, matching Claude Code's native format.

    Returns (session_id, jsonl_path).
    """
    import uuid as uuid_mod

    if append_to:
        session_id = append_to["session_id"]
        jsonl_path = Path(append_to["path"])
        prev_uuid = _last_claude_uuid(str(jsonl_path))
        cwd = append_to.get("project", conv.meta.cwd or str(Path.home()))
    else:
        session_id = str(uuid_mod.uuid4())
        cwd = conv.meta.cwd or str(Path.home())
        encoded = encode_project_path(cwd)
        project_dir = CLAUDE_DIR / "projects" / encoded
        project_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = project_dir / f"{session_id}.jsonl"
        prev_uuid = None

    git_branch = conv.meta.git_branch or ""
    model = conv.meta.model or "imported"

    # tool-results dir lives alongside the JSONL: {sessionId}/tool-results/
    tool_results_dir = jsonl_path.parent / session_id / "tool-results"

    def _base(uuid_val, ts):
        return {
            "parentUuid": prev_uuid,
            "isSidechain": False,
            "userType": "external",
            "cwd": cwd,
            "sessionId": session_id,
            "version": "1.0.0",
            "gitBranch": git_branch,
            "uuid": uuid_val,
            "timestamp": ts,
        }

    records = []

    for turn in conv.turns:
        if turn.role == "compaction":
            continue

        ts = turn.timestamp or datetime.now(timezone.utc).isoformat()

        if turn.role == "user":
            record_uuid = str(uuid_mod.uuid4())
            rec = _base(record_uuid, ts)
            rec["type"] = "user"
            rec["message"] = {"role": "user", "content": turn.content}
            records.append(rec)
            prev_uuid = record_uuid

        elif turn.role == "assistant":
            record_uuid = str(uuid_mod.uuid4())

            content = []
            if turn.content:
                content.append({"type": "text", "text": turn.content})

            tool_pairs = []
            for tool in turn.tools:
                if not tool.call_id:
                    tool.call_id = f"toolu_imported_{uuid_mod.uuid4().hex[:12]}"
                content.append(_to_claude_tool_use(tool))
                tool_pairs.append((tool.call_id, tool))

            rec = _base(record_uuid, ts)
            rec["type"] = "assistant"
            rec["message"] = {
                "model": model,
                "id": f"msg_imported_{record_uuid[:8]}",
                "type": "message",
                "role": "assistant",
                "content": content,
                "stop_reason": "tool_use" if tool_pairs else "end_turn",
            }
            records.append(rec)
            prev_uuid = record_uuid

            if tool_pairs:
                result_uuid = str(uuid_mod.uuid4())
                result_blocks = []
                for call_id, tool in tool_pairs:
                    output = _persist_tool_output(
                        tool.output or "", call_id, tool_results_dir,
                    )
                    result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": output,
                    })
                rec = _base(result_uuid, ts)
                rec["type"] = "user"
                rec["message"] = {"role": "user", "content": result_blocks}
                records.append(rec)
                prev_uuid = result_uuid

    if append_to:
        with open(jsonl_path, "a") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
    else:
        _atomic_write_jsonl(jsonl_path, records)

    if not append_to:
        first_user = next((t for t in conv.turns if t.role == "user"), None)
        display_text = first_user.content[:80] if first_user else "imported session"
        display = f"[Imported from {conv.meta.source}] {display_text}"
        history_entry = {
            "display": display,
            "timestamp": int(datetime.now().timestamp() * 1000),
            "project": cwd,
            "sessionId": session_id,
        }
        with open(CLAUDE_DIR / "history.jsonl", "a") as f:
            f.write(json.dumps(history_entry) + "\n")

    return session_id, str(jsonl_path)


def write_as_codex_session(conv: Conversation, append_to: Optional[dict] = None,
                           max_tool_lines: int = 50) -> tuple:
    """Write a Conversation as Codex JSONL with proper function_call/output pairing.

    Returns (session_id, jsonl_path).
    """
    import uuid as uuid_mod

    cwd = conv.meta.cwd or str(Path.home())
    git_branch = conv.meta.git_branch or ""
    model = conv.meta.model or "imported"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    if append_to:
        session_id = append_to["session_id"]
        jsonl_path = Path(append_to["path"])
    else:
        session_id = str(uuid_mod.uuid4())
        now_dt = datetime.now(timezone.utc)
        date_dir = CODEX_DIR / "sessions" / now_dt.strftime("%Y/%m/%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        ts_slug = now_dt.strftime("%Y-%m-%dT%H-%M-%S")
        jsonl_path = date_dir / f"rollout-{ts_slug}-{session_id}.jsonl"

    records = []

    if not append_to:
        records.append({
            "type": "session_meta",
            "timestamp": now_iso,
            "payload": {
                "id": session_id, "timestamp": now_iso, "cwd": cwd,
                "originator": "convo_porter", "cli_version": "0.0.0",
                "source": "import", "model_provider": "anthropic",
                "git": {"commit_hash": "", "branch": git_branch},
                "base_instructions": {"text": ""},
            },
        })
        records.append({
            "type": "turn_context",
            "timestamp": now_iso,
            "payload": {"turn_id": str(uuid_mod.uuid4()), "cwd": cwd, "model": model},
        })

    for turn in conv.turns:
        if turn.role == "compaction":
            continue

        ts = turn.timestamp or now_iso

        if turn.role == "user":
            records.append({
                "type": "response_item", "timestamp": ts,
                "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": turn.content}],
                },
            })

        elif turn.role == "assistant":
            # Emit assistant message (text only)
            if turn.content:
                records.append({
                    "type": "response_item", "timestamp": ts,
                    "payload": {
                        "type": "message", "role": "assistant",
                        "phase": "final_answer",
                        "content": [{"type": "output_text", "text": turn.content}],
                    },
                })

            # Emit each tool as a function_call + function_call_output pair
            for tool in turn.tools:
                call_id = tool.call_id or f"call_imported_{uuid_mod.uuid4().hex[:12]}"
                args = json.dumps({"command": tool.input_summary or tool.tool_name})
                records.append({
                    "type": "response_item", "timestamp": ts,
                    "payload": {
                        "type": "function_call",
                        "name": tool.tool_name,
                        "call_id": call_id,
                        "arguments": args,
                    },
                })
                output = _sanitize_output(tool.output or "", max_tool_lines)
                records.append({
                    "type": "response_item", "timestamp": ts,
                    "payload": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output,
                    },
                })

    if append_to:
        with open(jsonl_path, "a") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
    else:
        _atomic_write_jsonl(jsonl_path, records)

    return session_id, str(jsonl_path)


# ─── Inject Command ──────────────────────────────────────────────────────────


def cmd_inject(args):
    """Inject a session from one tool into another's native format."""
    if args.source == args.target:
        print(f"Error: source and target must differ (both are '{args.source}').",
              file=sys.stderr)
        sys.exit(1)

    session = resolve_session(args.session_id, args.current, args.source)
    _print_resolved(session)

    # Parse source
    if session["source"] == "claude":
        conv = parse_claude_session(session["path"], args)
    else:
        conv = parse_codex_session(session["path"], args)

    if args.tail and args.tail > 0:
        conv.turns = conv.turns[-args.tail:]

    exportable = [t for t in conv.turns if t.role in ("user", "assistant")]
    if not exportable:
        print("No exportable turns.", file=sys.stderr)
        sys.exit(1)

    # Resolve --into target session
    append_to = None
    if args.into:
        append_to = _find_target_session(args.target, args.into)
        if not append_to:
            print(f"Target session '{args.into}' not found in {args.target}.", file=sys.stderr)
            sys.exit(1)

    verb = "Appended" if append_to else "Injected"

    mtl = args.max_tool_lines

    if args.target == "claude":
        sid, path = write_as_claude_session(conv, append_to=append_to, max_tool_lines=mtl)
        print(f"{verb} {len(exportable)} turns to Claude Code session {sid[:8]}")
        print(f"  File: {path}")
        print(f"  Open: claude --resume {sid} --dangerously-skip-permissions")
    elif args.target == "codex":
        sid, path = write_as_codex_session(conv, append_to=append_to, max_tool_lines=mtl)
        print(f"{verb} {len(exportable)} turns to Codex session {sid[:8]}")
        print(f"  File: {path}")
        print(f"  Open: codex resume {sid}")


# ─── Install Command ──────────────────────────────────────────────────────────


_EXPORT_TO_CODEX_MD = """\
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
     {binary} inject --current --source claude --target codex
     ```
   - Append to existing Codex session:
     ```
     {binary} inject --current --source claude --target codex --into <session-id>
     ```

3. Report the result: show the Codex session file path.
"""

_EXPORT_TO_CLAUDE_SKILL = """\
---
name: export-to-claude
description: >
  Export the current Codex session into Claude Code as a native session.
  Use when the user wants to transfer context to Claude Code or continue
  work there. Trigger on: export to claude, send to claude, transfer to
  claude, porter.
argument-hint: "[target-claude-session-id] [--tail N]"
---

# Export to Claude

Inject the current Codex session into Claude Code's native session format.

## Workflow

1. Parse the user's arguments:
   - **No arguments**: create a new Claude Code session.
   - **A session ID**: append to that existing Claude Code session. Pass it as `--into <id>`.
   - **`--tail N`**: only export the last N turns.

2. Run the inject command:

   - New session:
     ```
     {binary} inject --current --source codex --target claude
     ```
   - Append to existing Claude session:
     ```
     {binary} inject --current --source codex --target claude --into <session-id>
     ```

3. Report the result: show the `claude --resume <id>` command so the user can open it.
"""

_OPENAI_YAML = """\
interface:
  display_name: "Export to Claude"
  short_description: "Transfer current session to Claude Code"
  default_prompt: "Use $export-to-claude to inject the current session into Claude Code's native format."

policy:
  allow_implicit_invocation: true
"""


def cmd_install(args):
    """Install slash-command and skill templates for Claude Code and Codex CLI."""
    binary = shutil.which("convo-porter")
    if not binary:
        # Fallback: assume we're running from source
        binary = f"python3 {Path(__file__).resolve()}"

    # Claude Code command
    dst = CLAUDE_DIR / "commands" / "export-to-codex.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_EXPORT_TO_CODEX_MD.format(binary=binary))
    print(f"  Installed {dst}")

    # Codex skill
    skill_dir = CODEX_DIR / "skills" / "export-to-claude"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_EXPORT_TO_CLAUDE_SKILL.format(binary=binary))
    print(f"  Installed {skill_dir / 'SKILL.md'}")

    agents_dir = skill_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "openai.yaml").write_text(_OPENAI_YAML)
    print(f"  Installed {agents_dir / 'openai.yaml'}")

    print()
    print("Done. Available commands:")
    print("  Claude Code:  /export-to-codex")
    print("  Codex CLI:    $export-to-claude")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="convo-porter",
        description="Export conversations between Claude Code and Codex CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # install
    sub.add_parser("install", help="Install slash-command and skill templates")

    # list
    lp = sub.add_parser("list", help="List available sessions")
    lp.add_argument("--source", choices=["claude", "codex", "both"], default="both")
    lp.add_argument("--limit", type=int, default=20)

    # export
    ep = sub.add_parser("export", help="Export a session to markdown")
    ep.add_argument("session_id", nargs="?", default=None)
    ep.add_argument("--source", choices=["claude", "codex"], default=None)
    ep.add_argument("--current", action="store_true")
    ep.add_argument("--output", "-o", default=None)
    ep.add_argument("--max-tool-lines", type=int, default=50)
    ep.add_argument("--include-thinking", action="store_true")
    ep.add_argument("--tail", type=int, default=None)

    # inject
    ip = sub.add_parser("inject", help="Inject a session into another tool's native format")
    ip.add_argument("session_id", nargs="?", default=None)
    ip.add_argument("--source", choices=["claude", "codex"], required=True)
    ip.add_argument("--target", choices=["claude", "codex"], required=True)
    ip.add_argument("--into", default=None, help="Target session ID to append to (prefix match)")
    ip.add_argument("--current", action="store_true")
    ip.add_argument("--max-tool-lines", type=int, default=50)
    ip.add_argument("--include-thinking", action="store_true")
    ip.add_argument("--tail", type=int, default=None)

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "inject":
        cmd_inject(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
