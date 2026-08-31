import sqlite3

import convo_porter
from convo_porter import Conversation, ConversationMeta, Turn


def test_register_codex_thread_upserts_and_skips_old_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path)
    monkeypatch.setattr(convo_porter, "_codex_cli_version", lambda: "0.151.0")
    session_id = "imported-session"
    rollout_path = tmp_path / "sessions" / "rollout.jsonl"
    cwd = str(tmp_path / "project")
    conv = Conversation(
        meta=ConversationMeta(cwd=cwd),
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
