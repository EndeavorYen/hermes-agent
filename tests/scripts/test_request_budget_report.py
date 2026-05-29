from pathlib import Path

import importlib.util


def _load_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "request_budget_report.py"
    spec = importlib.util.spec_from_file_location("request_budget_report", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SAMPLE_LOG = """
2026-05-28 02:11:31,865 INFO [s1] run_agent: request_budget.v1 {"api_calls":1,"model":"gpt-5.5","model_call_count":1,"model_request_ms":14716,"model_ttfb_max_ms":7281,"model_ttfb_ms":7281,"model_ttfb_source":"stream_delta","platform":"slack","provider":"openai-codex","reason":"text_response(finish_reason=stop)","session_id":"s1","skill_index_build_ms":52,"skill_index_tokens":4477,"tool_call_count":0,"tool_execution_ms":0,"tool_names":[],"tool_schema_bytes":7572,"tool_schema_count":6,"tool_schema_tokens":1893,"total_ms":14788,"turn_id":"1"}
2026-05-28 02:16:08,288 INFO [s1] run_agent: request_budget.v1 {"api_calls":5,"model":"gpt-5.5","model_call_count":5,"model_request_ms":56798,"model_ttfb_max_ms":19943,"model_ttfb_ms":12953,"model_ttfb_source":"response_complete","platform":"slack","provider":"openai-codex","reason":"text_response(finish_reason=stop)","session_id":"s1","skill_index_build_ms":0,"skill_index_tokens":4477,"tool_call_count":4,"tool_execution_ms":185342,"tool_names":["skill_view","image_generate,image_generate,image_generate"],"tool_schema_bytes":72255,"tool_schema_count":56,"tool_schema_tokens":18064,"total_ms":242428,"turn_id":"2"}
2026-05-28 02:16:09,388 INFO gateway.platforms.base: request_budget.gateway_delivery.v1 {"chat_id":"D123","delivery_kind":"text","delivery_succeeded":true,"gateway_delivery_ms":494,"platform":"slack","response_chars":173,"session_key":"agent:main:slack:dm:D123"}
"""


def test_parse_budget_log_extracts_turns_and_delivery(tmp_path):
    report = _load_module()
    log_path = tmp_path / "agent.log"
    log_path.write_text(SAMPLE_LOG, encoding="utf-8")

    parsed = report.parse_logs([log_path])

    assert len(parsed.turns) == 2
    assert len(parsed.deliveries) == 1
    slow = parsed.turns[1]
    assert slow.timestamp == "2026-05-28 02:16:08,288"
    assert slow.tool_names_split == ["skill_view", "image_generate", "image_generate", "image_generate"]
    assert slow.bottleneck == "tool"
    assert slow.total_s == 242.4


def test_parse_budget_log_deduplicates_mirrored_entries(tmp_path):
    report = _load_module()
    agent_log = tmp_path / "agent.log"
    gateway_log = tmp_path / "gateway.log"
    agent_log.write_text(SAMPLE_LOG, encoding="utf-8")
    gateway_log.write_text(SAMPLE_LOG, encoding="utf-8")

    parsed = report.parse_logs([agent_log, gateway_log])

    assert len(parsed.turns) == 2
    assert len(parsed.deliveries) == 1


def test_build_report_summarizes_slowest_turns_and_context_pressure(tmp_path):
    report = _load_module()
    log_path = tmp_path / "agent.log"
    log_path.write_text(SAMPLE_LOG, encoding="utf-8")
    parsed = report.parse_logs([log_path])

    text = report.render_markdown(parsed, limit=5)

    assert "# Request Budget Report" in text
    assert "## Slowest Turns" in text
    assert "| Time | Platform | Model | Total | Model | Tool | TTFB | Calls | Bottleneck | Tools |" in text
    assert "| 02:16:08 | slack | gpt-5.5 | 242.4s | 56.8s | 185.3s | 13.0s | 5/4 | tool | image_generate x3, skill_view |" in text
    assert "tool schema p50: 9,979 tokens" in text
    assert "skill index p50: 4,477 tokens" in text
    assert "gateway delivery max: 494ms" in text


def test_cli_writes_markdown_report(tmp_path, capsys):
    report = _load_module()
    log_path = tmp_path / "agent.log"
    log_path.write_text(SAMPLE_LOG, encoding="utf-8")

    rc = report.main(["--log", str(log_path), "--limit", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Turns parsed: 2" in out
    assert "02:16:08" in out
    assert "02:11:31" not in out
