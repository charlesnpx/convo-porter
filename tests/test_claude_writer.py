import json

import convo_porter
from convo_porter import Conversation, ToolInteraction, Turn


def test_claude_export_sanitizes_composite_tool_ids_and_preserves_canonical_ids(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(convo_porter, "CLAUDE_DIR", tmp_path)
    composite_id = (
        "call-a0aed434-d86d-4bbc-a629-b7a06d6aedf6-283\n"
        "fc_182eff1b-ab8e-9fa6-ae85-0c93c77af666_0"
    )
    valid_id = "toolu_abc123"
    tools = [
        ToolInteraction(
            tool_name="exec_command", input_summary="echo", output="output", call_id=call_id,
        )
        for call_id in (composite_id, valid_id, "")
    ]
    conv = Conversation(turns=[Turn(role="assistant", content="", tools=tools)])

    _, jsonl_path = convo_porter.write_as_claude_session(conv)
    with open(jsonl_path, encoding="utf-8") as session:
        records = [json.loads(line) for line in session]

    assistant = next(r for r in records if r["type"] == "assistant")
    tool_use_ids = [
        block["id"] for block in assistant["message"]["content"]
        if block["type"] == "tool_use"
    ]
    result = next(
        r for r in records
        if r["type"] == "user" and isinstance(r["message"]["content"], list)
    )
    tool_result_ids = [block["tool_use_id"] for block in result["message"]["content"]]

    expected_id = "toolu_2b5e490eb1714c7ba345fb71550587aee92304aa"
    assert tool_use_ids[:2] == [expected_id, valid_id]
    assert tool_use_ids[2].startswith("toolu_imported_")
    assert len(tool_use_ids[2]) == len("toolu_imported_") + 12
    assert tool_result_ids == tool_use_ids
    assert [tool.call_id for tool in conv.turns[0].tools] == [composite_id, valid_id, ""]
