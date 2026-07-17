import json
from pathlib import Path

import convo_porter
from convo_porter import Conversation, ConversationMeta, Turn, delegated_install_result


def test_delegated_install_result_accepts_tools_target_without_files(tmp_path):
    result = delegated_install_result("plan", "tools", install_root=str(tmp_path / "stage"))

    assert result["targets"] == {"tools": {"files": []}}


def _read_jsonl(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_codex_export_omits_source_provider_and_model_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path / "codex")
    source_model = "claude-3-5-sonnet-20241022"
    conv = Conversation(
        meta=ConversationMeta(
            source="claude",
            cwd=str(tmp_path / "project"),
            git_branch="main",
            model=source_model,
        ),
        turns=[
            Turn(role="user", content="hello"),
            Turn(role="assistant", content="assistant response"),
        ],
    )

    _, jsonl_path = convo_porter.write_as_codex_session(conv)
    records = _read_jsonl(jsonl_path)
    serialized = "\n".join(json.dumps(record) for record in records)
    session_meta = next(record for record in records if record["type"] == "session_meta")
    turn_context = next(record for record in records if record["type"] == "turn_context")

    assert "model_provider" not in session_meta["payload"]
    assert "model" not in turn_context["payload"]
    assert "anthropic" not in serialized
    assert source_model not in serialized


def test_claude_export_uses_synthetic_model_for_imported_assistant_records(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CLAUDE_DIR", tmp_path / "claude")
    source_model = "gpt-5.6-terra"
    conv = Conversation(
        meta=ConversationMeta(
            source="codex",
            cwd=str(tmp_path / "project"),
            git_branch="main",
            model=source_model,
        ),
        turns=[
            Turn(role="user", content="hello"),
            Turn(role="assistant", content="assistant response"),
        ],
    )

    _, jsonl_path = convo_porter.write_as_claude_session(conv)
    records = _read_jsonl(jsonl_path)
    assistant_records = [
        record for record in records
        if record["type"] == "assistant"
    ]
    serialized = "\n".join(json.dumps(record) for record in records)

    assert assistant_records
    assert all(
        record["message"]["model"] == "<synthetic>"
        for record in assistant_records
    )
    assert source_model not in serialized
