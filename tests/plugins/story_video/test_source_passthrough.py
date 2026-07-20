from __future__ import annotations

import hashlib
import json

from plugins.story_video.source_passthrough import (
    extract_user_screenplay,
    parse_user_screenplay,
    prepare_local_adult_passthrough,
)
from plugins.story_video.state import OperatorCall, StoryVideoStateStore
from plugins.story_video.tools import _project_content_rating, validate_phase


def _request(*, duplicate: bool = False) -> str:
    screenplay = """【場景一：深夜】
旁白：[夜深了，房間只剩微弱的燈光。]
小美：[走向小王面前]「你好。」
小王：[驚訝地看著小美]「你...你好。」
小美：[安靜地點頭]
"""
    blocks = f"```text\n{screenplay}```"
    if duplicate:
        blocks += f"\n以下重貼一次：\n```text\n{screenplay}```"
    return (
        "請把以下已完成的 NSFW 劇本做成全黑背景字幕影片，不要產圖。\n"
        + blocks
        + "\n多角色配音：旁白用 Vivian，小美用 Serena，小王用 Uncle_Fu。"
    )


def test_extract_user_screenplay_deduplicates_repeated_long_block() -> None:
    extracted = extract_user_screenplay(_request(duplicate=True))

    assert extracted.deduplicated_blocks == 1
    assert extracted.text.count("【場景一：深夜】") == 1
    assert "以下重貼一次" not in extracted.text


def test_extract_user_screenplay_collapses_near_duplicate_missing_scene_heading() -> None:
    full = "【場景一：深夜】\n旁白：[夜深了。]\n小美：[走近]「你好。」\n" * 20
    without_heading = full.removeprefix("【場景一：深夜】\n")
    request = f"NSFW 全黑字幕\n```\n{without_heading}```\n```\n{full}```"

    extracted = extract_user_screenplay(request)

    assert extracted.deduplicated_blocks == 1
    assert extracted.text.startswith("【場景一：深夜】")


def test_inline_fence_without_language_keeps_first_source_line() -> None:
    request = "NSFW 全黑字幕\n```旁白：[第一句。]\n小美：[走近]「你好。」```"

    extracted = extract_user_screenplay(request)

    assert extracted.text.startswith("旁白：[第一句。]")
    assert "小美" in extracted.text


def test_short_unstructured_source_uses_explicit_narrator_voice() -> None:
    request = (
        "故事劇本 (NSFW)\n```這是一小段已完成的文本。```\n"
        "多角色配音：旁白用 Vivian。"
    )
    extracted = extract_user_screenplay(request)

    parsed = parse_user_screenplay(extracted.text, request)

    assert parsed.speakers[0]["speaker_id"] == "旁白"
    assert parsed.speakers[0]["voice_id"] == "Vivian"
    assert parsed.utterances[0]["display_text"] == "這是一小段已完成的文本。"


def test_parse_user_screenplay_separates_spoken_text_from_actions() -> None:
    extracted = extract_user_screenplay(_request())
    parsed = parse_user_screenplay(extracted.text, _request())

    assert [row["display_name"] for row in parsed.speakers] == [
        "旁白",
        "小美",
        "小王",
    ]
    assert [row["voice_id"] for row in parsed.speakers] == [
        "Vivian",
        "Serena",
        "Uncle_Fu",
    ]
    assert [row["display_text"] for row in parsed.utterances] == [
        "夜深了，房間只剩微弱的燈光。",
        "你好。",
        "你...你好。",
    ]
    assert parsed.utterances[1]["action"] == "走向小王面前"
    assert parsed.utterances[2]["action"] == "驚訝地看著小美"
    assert "安靜地點頭" not in [
        row["display_text"] for row in parsed.utterances
    ]


def test_prepare_local_adult_passthrough_is_deterministic_and_planning_valid(
    tmp_path,
) -> None:
    store = StoryVideoStateStore(tmp_path)
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=OperatorCall(
            action="start",
            topic="已完成的成人劇本",
            visual_mode="black_subtitle",
        ),
        original_request=_request(duplicate=True),
    )

    result = prepare_local_adult_passthrough(context)
    second = prepare_local_adult_passthrough(context)

    assert result["source_sha256"] == second["source_sha256"]
    assert result["utterance_count"] == 3
    assert result["deduplicated_blocks"] == 1
    assert result["image_generation"] == "forbidden"
    source_path = context.project_dir / "source_screenplay.txt"
    assert result["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    content_profile = json.loads(
        (context.project_dir / "content_profile.json").read_text(encoding="utf-8")
    )
    assert content_profile == {
        "schema": "story_video_content_profile_v1",
        "rating": "adult_explicit",
        "activation_status": "active",
        "minimum_viewer_age": 18,
        "policy_profile_id": "adult-explicit-local-passthrough-v1",
        "writer_profile_id": "user-supplied-source-passthrough-v1",
        "review_profile_id": "deterministic-source-integrity-v1",
        "provider_capability_status": "available",
        "source_policy": "verbatim-user-supplied-screenplay",
        "visual_policy": "black-subtitle-only",
        "generation_policy": "no-expansion",
    }
    proof = validate_phase(context)
    assert proof.ok is True, (proof.missing, proof.violations)


def test_adult_passthrough_compiles_adult_action_tone_without_speaking_action(
    tmp_path,
) -> None:
    request = (
        "請把以下已完成的 NSFW 劇本做成全黑背景字幕影片，不要產圖。\n"
        "```text\n【場景一：深夜】\n"
        "小美：[帶著壓抑的渴望靠近耳邊，壓低聲音]「再靠近一點。」\n```\n"
        "多角色配音：小美用 Serena。"
    )
    store = StoryVideoStateStore(tmp_path)
    context = store.create_or_load(
        source_key="source-adult-tone",
        session_id="session-adult-tone",
        call=OperatorCall(
            action="start",
            topic="已完成的成人劇本",
            visual_mode="black_subtitle",
        ),
        original_request=request,
    )

    prepare_local_adult_passthrough(context)

    ledger = json.loads(
        (context.project_dir / "dialogue_ledger.json").read_text(encoding="utf-8")
    )
    row = ledger["utterances"][0]
    assert ledger["content_rating"] == "adult_explicit"
    assert row["tone"]["tone_id"] == "adult.desirous"
    assert row["display_text"] == "再靠近一點。"
    assert "渴望" not in row["display_text"]
    proof = validate_phase(context)
    assert proof.ok is True, (proof.missing, proof.violations)
    assert _project_content_rating(context) == "adult_explicit"


def test_prepare_local_adult_passthrough_fails_closed_outside_black_subtitle(
    tmp_path,
) -> None:
    store = StoryVideoStateStore(tmp_path)
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=OperatorCall(
            action="start",
            topic="已完成的成人劇本",
            visual_mode="story_visual",
        ),
        original_request=_request(),
    )

    try:
        prepare_local_adult_passthrough(context)
    except ValueError as exc:
        assert "black_subtitle" in str(exc)
    else:  # pragma: no cover - makes the fail-closed contract explicit
        raise AssertionError("adult passthrough must reject visual generation mode")


def test_planning_rejects_passthrough_manifest_from_another_run(tmp_path) -> None:
    store = StoryVideoStateStore(tmp_path)
    context = store.create_or_load(
        source_key="source-1",
        session_id="session-1",
        call=OperatorCall(
            action="start",
            topic="已完成的成人劇本",
            visual_mode="black_subtitle",
        ),
        original_request=_request(),
    )
    prepare_local_adult_passthrough(context)
    path = context.project_dir / "source_passthrough_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["run_id"] = "another-run"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    proof = validate_phase(context)

    assert proof.ok is False
    assert (
        "adult source passthrough manifest run identity mismatch"
        in proof.violations
    )
