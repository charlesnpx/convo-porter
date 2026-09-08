import json
import re
import sqlite3

import convo_porter
from convo_porter import Conversation, ConversationMeta, ToolInteraction, Turn


def test_register_codex_thread_upserts_and_skips_old_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path)
    session_id = "imported-session"
    rollout_path = tmp_path / "sessions" / "rollout.jsonl"
    cwd = str(tmp_path / "project")
    conv = Conversation(
        meta=ConversationMeta(source="claude-code", cwd=cwd),
        turns=[Turn(role="user", content="Please restore this thread")],
    )

    assert convo_porter._register_codex_thread(session_id, rollout_path, conv) is None

    db_path = tmp_path / "state_5.sqlite"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE threads (
              id TEXT PRIMARY KEY,
              rollout_path TEXT,
              created_at INTEGER,
              updated_at INTEGER,
              source TEXT,
              model_provider TEXT,
              cwd TEXT,
              title TEXT,
              sandbox_policy TEXT,
              approval_mode TEXT,
              tokens_used INTEGER,
              has_user_event INTEGER,
              archived INTEGER,
              cli_version TEXT,
              first_user_message TEXT,
              memory_mode TEXT,
              thread_source TEXT,
              created_at_ms INTEGER,
              updated_at_ms INTEGER,
              preview TEXT,
              recency_at INTEGER,
              recency_at_ms INTEGER,
              history_mode TEXT
            )
            """,
        )
        connection.execute(
            "INSERT INTO threads (id, cwd, title, first_user_message, preview) "
            "VALUES (?, '', '', '', '')",
            (session_id,),
        )
        connection.commit()
    finally:
        connection.close()

    convo_porter._register_codex_thread(session_id, rollout_path, conv)
    convo_porter._register_codex_thread(session_id, rollout_path, conv)

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT rollout_path, history_mode, title, cwd FROM threads WHERE id = ?",
            (session_id,),
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) == 1
    rollout, history_mode, title, stored_cwd = rows[0]
    assert rollout == str(rollout_path)
    assert history_mode == "legacy"
    assert title == "Please restore this thread (imported from Claude Code)"
    assert stored_cwd == cwd


def test_register_codex_thread_degrades_on_schema_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path)
    db_path = tmp_path / "state_5.sqlite"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE threads (
              id TEXT PRIMARY KEY,
              rollout_path TEXT,
              created_at INTEGER,
              updated_at INTEGER,
              source TEXT,
              model_provider TEXT,
              cwd TEXT,
              title TEXT,
              sandbox_policy TEXT,
              approval_mode TEXT,
              tokens_used INTEGER,
              has_user_event INTEGER,
              archived INTEGER,
              cli_version TEXT,
              first_user_message TEXT,
              memory_mode TEXT,
              thread_source TEXT,
              created_at_ms INTEGER,
              updated_at_ms INTEGER,
              preview TEXT,
              recency_at INTEGER,
              recency_at_ms INTEGER,
              history_mode TEXT,
              workspace_id TEXT NOT NULL
            )
            """,
        )
        connection.commit()
    finally:
        connection.close()

    conv = Conversation(
        meta=ConversationMeta(source="claude-code", cwd=str(tmp_path / "project")),
        turns=[Turn(role="user", content="Please restore this thread")],
    )

    assert convo_porter._register_codex_thread(
        "schema-drift-session", tmp_path / "sessions" / "rollout.jsonl", conv
    ) is None


def test_codex_export_sanitizes_cursor_call_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path / "codex")
    monkeypatch.setattr(convo_porter, "_codex_cli_version", lambda: "0.0.0")
    composite_id = (
        "call-a0aed434-d86d-4bbc-a629-b7a06d6aedf6-283\n"
        "fc_182eff1b-ab8e-9fa6-ae85-0c93c77af666_0"
    )
    valid_id = "call_abc123"
    conv = Conversation(
        turns=[Turn(
            role="assistant",
            content="",
            tools=[
                ToolInteraction(
                    tool_name="exec_command",
                    input_summary="echo cursor",
                    output="ok",
                    call_id=composite_id,
                ),
                ToolInteraction(
                    tool_name="exec_command",
                    input_summary="echo valid",
                    output="ok",
                    call_id=valid_id,
                ),
            ],
        )],
    )

    _, jsonl_path = convo_porter.write_as_codex_session(conv)
    with open(jsonl_path, encoding="utf-8") as rollout:
        records = [json.loads(line) for line in rollout]
    function_calls = [
        record["payload"]
        for record in records
        if record["payload"].get("type") == "function_call"
    ]
    function_outputs = [
        record["payload"]
        for record in records
        if record["payload"].get("type") == "function_call_output"
    ]

    assert len(composite_id) == 87
    sanitized_id = function_calls[0]["call_id"]
    assert sanitized_id == function_outputs[0]["call_id"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sanitized_id)
    assert sanitized_id != composite_id
    assert function_calls[1]["call_id"] == valid_id
    assert function_outputs[1]["call_id"] == valid_id
