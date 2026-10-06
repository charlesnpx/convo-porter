import json
import os
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
    expected_id = "call_2b5e490eb1714c7ba345fb71550587aee92304aa"
    assert function_calls[0]["call_id"] == expected_id
    assert function_outputs[0]["call_id"] == expected_id
    assert function_calls[1]["call_id"] == valid_id
    assert function_outputs[1]["call_id"] == valid_id


def _create_threads_table(db_path, extra_rows=()):
    connection = sqlite3.connect(db_path)
    try:
        columns = (
            "id TEXT PRIMARY KEY, rollout_path TEXT, created_at INTEGER, updated_at INTEGER, "
            "source TEXT, model_provider TEXT, cwd TEXT, title TEXT, sandbox_policy TEXT, "
            "approval_mode TEXT, tokens_used INTEGER, has_user_event INTEGER, archived INTEGER, "
            "cli_version TEXT, first_user_message TEXT, memory_mode TEXT, thread_source TEXT, "
            "created_at_ms INTEGER, updated_at_ms INTEGER, preview TEXT, recency_at INTEGER, "
            "recency_at_ms INTEGER, history_mode TEXT"
        )
        connection.execute(f"CREATE TABLE threads ({columns})")
        for thread_id, provider in extra_rows:
            connection.execute(
                "INSERT INTO threads (id, model_provider) VALUES (?, ?)", (thread_id, provider),
            )
        connection.commit()
    finally:
        connection.close()


def _registered_provider(db_path, session_id):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(
            "SELECT model_provider FROM threads WHERE id = ?", (session_id,),
        ).fetchone()[0]
    finally:
        connection.close()


def test_register_codex_thread_uses_the_exporting_threads_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", "running-thread")
    db_path = tmp_path / "state_5.sqlite"
    _create_threads_table(db_path, [("running-thread", "pi_claude")])
    (tmp_path / "config.toml").write_text('model_provider = "openai_http"\n')
    conv = Conversation(turns=[Turn(role="user", content="hello")])

    convo_porter._register_codex_thread("imported", tmp_path / "rollout.jsonl", conv)

    assert _registered_provider(db_path, "imported") == "pi_claude"


def test_register_codex_thread_falls_back_to_configured_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    db_path = tmp_path / "state_5.sqlite"
    _create_threads_table(db_path)
    (tmp_path / "config.toml").write_text(
        'model = "gpt"\nmodel_provider = "openai_http"  # proxy\n\n'
        '[profiles.other]\nmodel_provider = "ollama"\n',
    )
    conv = Conversation(turns=[Turn(role="user", content="hello")])

    convo_porter._register_codex_thread("imported", tmp_path / "rollout.jsonl", conv)

    assert _registered_provider(db_path, "imported") == "openai_http"


def test_register_codex_thread_defaults_to_openai_without_config(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    db_path = tmp_path / "state_5.sqlite"
    _create_threads_table(db_path)
    conv = Conversation(turns=[Turn(role="user", content="hello")])

    convo_porter._register_codex_thread("imported", tmp_path / "rollout.jsonl", conv)

    assert _registered_provider(db_path, "imported") == "openai"


def test_find_current_codex_session_prefers_codex_thread_id(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path)
    day = tmp_path / "sessions" / "2026" / "10" / "06"
    day.mkdir(parents=True)
    current = day / "rollout-2026-10-06T10-00-00-current-thread.jsonl"
    newer = day / "rollout-2026-10-06T11-00-00-newer-thread.jsonl"
    current.write_text(json.dumps({"type": "session_meta", "payload": {"id": "current-thread"}}) + "\n")
    newer.write_text(json.dumps({"type": "session_meta", "payload": {"id": "newer-thread"}}) + "\n")
    modified = current.stat().st_mtime
    os.utime(newer, (modified + 60, modified + 60))

    monkeypatch.setenv("CODEX_THREAD_ID", "current-thread")
    assert convo_porter.find_current_codex_session()["session_id"] == "current-thread"

    monkeypatch.delenv("CODEX_THREAD_ID")
    assert convo_porter.find_current_codex_session()["session_id"] == "newer-thread"
