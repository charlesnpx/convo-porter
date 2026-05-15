from convo_porter import delegated_install_result


def test_delegated_install_result_accepts_tools_target_without_files(tmp_path):
    result = delegated_install_result("plan", "tools", install_root=str(tmp_path / "stage"))

    assert result["targets"] == {"tools": {"files": []}}

