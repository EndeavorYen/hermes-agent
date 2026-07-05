def test_visual_test_coverage_report_counts_test_functions(tmp_path):
    from scripts.visual_test_coverage_report import count_test_functions

    test_file = tmp_path / "test_demo.py"
    test_file.write_text(
        "def test_one():\n    assert True\n\n"
        "async def test_two():\n    assert True\n\n"
        "def helper():\n    pass\n",
        encoding="utf-8",
    )

    assert count_test_functions([test_file]) == 2


def test_visual_test_coverage_report_fails_below_threshold(monkeypatch, tmp_path):
    from scripts import visual_test_coverage_report

    source_file = tmp_path / "source.py"
    source_file.write_text(
        "def covered():\n    return 1\n\n"
        "def missed():\n    return 2\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_source.py"
    test_file.write_text("def test_source():\n    assert True\n", encoding="utf-8")

    monkeypatch.setattr(
        visual_test_coverage_report,
        "run_targeted_tests_with_trace",
        lambda root, test_paths: (0, {(str(source_file), 1): 1, (str(source_file), 2): 1}),
    )

    report = visual_test_coverage_report.build_visual_test_coverage_report(
        repo_root=tmp_path,
        target_files=[source_file],
        test_paths=[test_file],
        min_line_coverage=0.9,
    )

    assert report["success"] is False
    assert report["coverage"]["files"][0]["line_coverage"] < 0.9
    assert "line_coverage_below_threshold:source.py" in report["failures"]


def test_visual_test_coverage_report_cli_json_no_run(capsys):
    from scripts.visual_test_coverage_report import main

    code = main(["--json", "--no-run-tests"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"success": true' in out
    assert '"mode": "contract-only"' in out
