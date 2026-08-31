import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import convo_porter
from convo_porter import (
    Conversation,
    ConversationMeta,
    ToolInteraction,
    Turn,
    delegated_install_result,
)


def test_delegated_install_result_accepts_tools_target_without_files(tmp_path):
    result = delegated_install_result("plan", "tools", install_root=str(tmp_path / "stage"))

    assert result["targets"] == {"tools": {"files": []}}


def test_shared_agent_install_targets_use_open_agents_directory(tmp_path):
    stage = tmp_path / "stage"

    codex = delegated_install_result("plan", "codex", install_root=str(stage))
    cursor = delegated_install_result("plan", "cursor", install_root=str(stage))
    all_targets = delegated_install_result("plan", "all", install_root=str(stage))

    codex_paths = [entry["path"] for entry in codex["targets"]["codex"]["files"]]
    cursor_paths = [entry["path"] for entry in cursor["targets"]["cursor"]["files"]]
    assert codex_paths == cursor_paths
    assert len(codex_paths) == 6
    assert all("/.agents/skills/export-to-" in path for path in codex_paths)
    assert all("/.codex/" not in path and "/.cursor/" not in path for path in codex_paths)
    assert set(all_targets["targets"]) == {"claude", "codex"}
    assert len(all_targets["targets"]["claude"]["files"]) == 2


def test_delegated_install_stages_all_templates(tmp_path):
    stage = tmp_path / "stage"
    result = delegated_install_result(
        "install", "all", perform=True, install_root=str(stage),
    )

    files = [
        Path(entry["path"])
        for target in result["targets"].values()
        for entry in target["files"]
    ]
    assert len(files) == 8
    assert all(path.exists() for path in files)
    templates = [path.read_text() for path in files if path.name.endswith(".md")]
    assert all("__BINARY__" not in template for template in templates)
    assert all("convo-porter inject" in template for template in templates)
    module_path = str(Path(convo_porter.__file__).resolve())
    assert all(module_path not in template for template in templates)


def test_legacy_codex_skill_cleanup_only_removes_managed_skill(tmp_path, monkeypatch):
    codex_dir = tmp_path / "codex"
    legacy = codex_dir / "skills" / "export-to-claude"
    (legacy / "agents").mkdir(parents=True)
    (legacy / "SKILL.md").write_text(
        """---
name: export-to-claude
---
# Export to Claude
Inject the current Codex session into Claude Code's native session format.
/run/convo-porter inject --current --source codex --target claude
Finally, show the `claude --resume <id>` command.
""",
    )
    (legacy / "agents" / "openai.yaml").write_text("interface: {}\n")
    monkeypatch.setattr(convo_porter, "CODEX_DIR", codex_dir)

    removed = convo_porter._cleanup_legacy_codex_skill()

    assert len(removed) == 2
    assert not legacy.exists()


def test_legacy_codex_skill_cleanup_preserves_unrecognized_skill(tmp_path, monkeypatch):
    codex_dir = tmp_path / "codex"
    legacy = codex_dir / "skills" / "export-to-claude"
    legacy.mkdir(parents=True)
    skill_path = legacy / "SKILL.md"
    skill_path.write_text("name: export-to-claude\ncustom implementation\n")
    monkeypatch.setattr(convo_porter, "CODEX_DIR", codex_dir)

    removed = convo_porter._cleanup_legacy_codex_skill()

    assert removed == []
    assert skill_path.exists()


def _read_jsonl(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_codex_export_omits_source_provider_and_model_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path / "codex")
    monkeypatch.setattr(convo_porter, "_codex_cli_version", lambda: "0.151.0")
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
    assert "base_instructions" not in session_meta["payload"]
    assert "anthropic" not in serialized
    assert source_model not in serialized


def test_codex_rollout_headers_include_required_parseability_fields(tmp_path, monkeypatch):
    cwd = str(tmp_path / "project")
    monkeypatch.setattr(convo_porter, "CODEX_DIR", tmp_path / "codex")
    monkeypatch.setattr(convo_porter, "_codex_cli_version", lambda: "0.151.0")
    conv = Conversation(
        meta=ConversationMeta(cwd=cwd, git_branch="main"),
        turns=[Turn(role="user", content="hello")],
    )

    session_id, jsonl_path = convo_porter.write_as_codex_session(conv)
    records = _read_jsonl(jsonl_path)
    session_meta = records[0]
    turn_context = records[1]

    assert session_meta["type"] == "session_meta"
    meta_payload = session_meta["payload"]
    assert meta_payload["id"] == session_id
    assert meta_payload["session_id"] == session_id
    assert meta_payload["timestamp"]
    assert meta_payload["cwd"] == cwd
    assert meta_payload["originator"] == "convo_porter"
    assert meta_payload["cli_version"]
    assert meta_payload["source"] in {
        "cli", "vscode", "exec", "mcp", "custom", "internal", "subagent",
    }

    assert turn_context["type"] == "turn_context"
    context_payload = turn_context["payload"]
    assert context_payload["cwd"] == cwd
    assert context_payload["approval_policy"] == "never"
    assert context_payload["sandbox_policy"] == {"type": "danger-full-access"}
    assert context_payload["model"] == "gpt-5.1-codex"
    assert context_payload["summary"] == "auto"


def _cursor_opts(include_thinking=True, max_tool_lines=50):
    return SimpleNamespace(
        include_thinking=include_thinking,
        max_tool_lines=max_tool_lines,
    )


def _cursor_store_metadata(path):
    connection = sqlite3.connect(path)
    try:
        encoded = connection.execute(
            "SELECT value FROM meta WHERE key = '0'",
        ).fetchone()[0]
        return json.loads(bytes.fromhex(encoded).decode("utf-8"))
    finally:
        connection.close()


def test_cursor_round_trip_preserves_content_and_omits_runtime_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CURSOR_DIR", tmp_path / "cursor")
    source_model = "claude-opus-vendor-source-model"
    conv = Conversation(
        meta=ConversationMeta(
            source="claude-code",
            cwd=str(tmp_path / "project"),
            git_branch="main",
            model=source_model,
        ),
        turns=[
            Turn(role="user", content="please inspect the build"),
            Turn(
                role="assistant",
                content="I inspected it.",
                thinking="Check the logs first.",
                tools=[ToolInteraction(
                    tool_name="Read",
                    input_summary="build.log",
                    output="failure details",
                    call_id="call-portable-1",
                )],
            ),
        ],
    )

    session_id, store_path = convo_porter.write_as_cursor_session(conv)
    store_path = Path(store_path)
    chat_meta = json.loads((store_path.parent / "meta.json").read_text())
    store_meta = _cursor_store_metadata(store_path)

    assert session_id == store_path.parent.name
    assert chat_meta["hasConversation"] is True
    assert chat_meta["cwd"] == str(tmp_path / "project")
    assert set(store_meta) == {
        "agentId", "latestRootBlobId", "name", "createdAt", "blobEncryptionKey",
    }
    forbidden = {
        "lastUsedModel", "approvalMode", "mode", "isRunEverything",
        "providerOptions", "encrypted_model", "model_provider",
    }
    assert forbidden.isdisjoint(store_meta)

    connection = sqlite3.connect(store_path)
    try:
        blobs = connection.execute("SELECT id, data FROM blobs").fetchall()
    finally:
        connection.close()
    assert blobs
    assert all(hashlib.sha256(data).hexdigest() == blob_id for blob_id, data in blobs)
    serialized = b"\n".join(data for _, data in blobs)
    assert source_model.encode() not in serialized
    assert b"providerOptions" not in serialized

    parsed = convo_porter.parse_cursor_session(str(store_path), _cursor_opts())
    assert parsed.meta.source == "cursor"
    assert parsed.meta.session_id == session_id
    assert parsed.meta.cwd == str(tmp_path / "project")
    assert parsed.turns[0].role == "user"
    assert parsed.turns[0].content == "please inspect the build"
    assistant = parsed.turns[1]
    assert assistant.role == "assistant"
    assert "I inspected it." in assistant.content
    assert "Imported tool activity" in assistant.content
    assert assistant.thinking == "Check the logs first."
    assert len(assistant.tools) == 1
    assert assistant.tools[0].tool_name == "Read"
    assert assistant.tools[0].input_summary == '{"summary": "build.log"}'
    assert assistant.tools[0].output == "failure details"


def test_cursor_writer_persists_a_complete_referenced_blob_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(convo_porter, "CURSOR_DIR", tmp_path / "cursor")
    conv = Conversation(
        meta=ConversationMeta(cwd=str(tmp_path / "project")),
        turns=[
            Turn(role="user", content="inspect it"),
            Turn(role="assistant", content="done", thinking="checking"),
        ],
    )

    _, store_path = convo_porter.write_as_cursor_session(conv)
    connection = sqlite3.connect(store_path)
    try:
        blobs = dict(connection.execute("SELECT id, data FROM blobs"))
    finally:
        connection.close()

    root_id = _cursor_store_metadata(store_path)["latestRootBlobId"]
    assert root_id in blobs
    root = blobs[root_id]
    prompt_refs = convo_porter._pb_byte_values(root, 1)
    turn_refs = convo_porter._pb_byte_values(root, 8)
    assert prompt_refs
    assert turn_refs
    assert all(reference.hex() in blobs for reference in prompt_refs + turn_refs)

    for turn_reference in turn_refs:
        turn = blobs[turn_reference.hex()]
        agent = convo_porter._pb_first_bytes(turn, 1)
        assert agent is not None
        graph_refs = (
            convo_porter._pb_byte_values(agent, 1)
            + convo_porter._pb_byte_values(agent, 2)
        )
        assert graph_refs
        assert all(reference.hex() in blobs for reference in graph_refs)


def test_cursor_writer_cleans_up_partial_chat_when_publish_fails(tmp_path, monkeypatch):
    cursor_dir = tmp_path / "cursor"
    monkeypatch.setattr(convo_porter, "CURSOR_DIR", cursor_dir)
    monkeypatch.setattr(
        convo_porter.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("publish failed")),
    )
    conv = Conversation(
        meta=ConversationMeta(cwd=str(tmp_path / "project")),
        turns=[Turn(role="user", content="hello")],
    )

    with pytest.raises(OSError, match="publish failed"):
        convo_porter.write_as_cursor_session(conv)

    chats_dir = cursor_dir / "chats"
    assert not any(path.name.startswith(".convo-porter-") for path in chats_dir.iterdir())
    assert not any(path.is_dir() and any(path.iterdir()) for path in chats_dir.iterdir())


def test_cursor_discovery_and_current_session_use_workspace_and_environment(tmp_path, monkeypatch):
    cursor_dir = tmp_path / "cursor"
    project = tmp_path / "project"
    monkeypatch.setattr(convo_porter, "CURSOR_DIR", cursor_dir)
    project.mkdir(exist_ok=True)
    monkeypatch.chdir(project)
    conv = Conversation(
        meta=ConversationMeta(source="codex", cwd=str(project)),
        turns=[Turn(role="user", content="hello"), Turn(role="assistant", content="hi")],
    )
    session_id, _ = convo_porter.write_as_cursor_session(conv)

    discovered = convo_porter.discover_cursor_sessions(cwd=str(project))
    assert [item["session_id"] for item in discovered] == [session_id]
    monkeypatch.setenv("CURSOR_AGENT_CHAT_ID", session_id)
    assert convo_porter.find_current_cursor_session()["session_id"] == session_id


def test_cursor_target_append_is_rejected_before_target_lookup(monkeypatch):
    args = SimpleNamespace(
        source="codex",
        target="cursor",
        session_id=None,
        current=True,
        tail=None,
        into="existing-chat",
        max_tool_lines=50,
        include_thinking=False,
    )
    monkeypatch.setattr(convo_porter, "resolve_session", lambda *a, **k: {
        "session_id": "source-id",
        "source": "codex",
        "path": "/tmp/source.jsonl",
        "project": "/tmp",
    })
    monkeypatch.setattr(convo_porter, "parse_codex_session", lambda *a, **k: Conversation(
        turns=[Turn(role="user", content="hello")],
    ))
    monkeypatch.setattr(
        convo_porter,
        "_find_target_session",
        lambda *a, **k: pytest.fail("target lookup should not run"),
    )

    with pytest.raises(SystemExit) as exc:
        convo_porter.cmd_inject(args)
    assert exc.value.code == 1


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("claude", "codex"),
        ("claude", "cursor"),
        ("codex", "claude"),
        ("codex", "cursor"),
        ("cursor", "claude"),
        ("cursor", "codex"),
    ],
)
def test_inject_dispatch_supports_all_six_directions(
    source, target, monkeypatch, capsys,
):
    args = SimpleNamespace(
        source=source,
        target=target,
        session_id=None,
        current=True,
        tail=None,
        into=None,
        max_tool_lines=50,
        include_thinking=False,
    )
    conversation = Conversation(turns=[Turn(role="user", content="hello")])
    monkeypatch.setattr(convo_porter, "resolve_session", lambda *a, **k: {
        "session_id": "source-id",
        "source": source,
        "path": "/tmp/source",
        "project": "/tmp",
    })
    monkeypatch.setattr(convo_porter, "parse_claude_session", lambda *a, **k: conversation)
    monkeypatch.setattr(convo_porter, "parse_codex_session", lambda *a, **k: conversation)
    monkeypatch.setattr(convo_porter, "parse_cursor_session", lambda *a, **k: conversation)
    called = []
    monkeypatch.setattr(
        convo_porter,
        "write_as_claude_session",
        lambda *a, **k: (called.append("claude") or ("target-id", "/tmp/target")),
    )
    monkeypatch.setattr(
        convo_porter,
        "write_as_codex_session",
        lambda *a, **k: (called.append("codex") or ("target-id", "/tmp/target")),
    )
    monkeypatch.setattr(
        convo_porter,
        "write_as_cursor_session",
        lambda *a, **k: (called.append("cursor") or ("target-id", "/tmp/target")),
    )

    convo_porter.cmd_inject(args)

    assert called == [target]
    output = capsys.readouterr().out
    if target == "claude":
        assert "Open: claude --resume target-id" in output
        assert "dangerously-skip-permissions" not in output


def test_protobuf_decoder_rejects_truncated_fields():
    with pytest.raises(ValueError, match="truncated"):
        convo_porter._pb_fields(b"\x0a\x05abc")


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
