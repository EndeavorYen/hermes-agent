from __future__ import annotations

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.prompt_arsenal import (
    approved_prompt_arsenal_entries,
    build_prompt_arsenal_context,
    prompt_requests_arsenal_lookup,
    record_prompt_draft_arsenal_entry,
)


def test_record_prompt_draft_entry_feeds_approved_prompt_arsenal(tmp_path):
    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()

    entry_id = record_prompt_draft_arsenal_entry(
        ledger,
        user_prompt="固定這位角色，替換不同服裝與構圖，請給我 prompt 就好，不須產圖",
        prompt_response=(
            "Use the references as a collective identity lock. Create a premium 2D anime key visual "
            "with cinematic low-angle composition, refined fabric texture, clean hands, and clear lighting logic."
        ),
        platform="slack",
        channel_id="C123",
        thread_id="1700000000.000100",
        message_id="1700000000.000200",
    )

    assert entry_id
    entries = approved_prompt_arsenal_entries(
        ledger,
        request_category="anime_character",
        limit=2,
    )
    assert len(entries) == 1
    assert "collective identity lock" in entries[0]["prompt_mediated"]
    assert entries[0]["feedback_id"] == ""
    assert entries[0]["prompt_role"] == "prompt_only_success_pattern"


def test_record_prompt_draft_entry_dedupes_same_prompt_pair(tmp_path):
    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    kwargs = {
        "user_prompt": "幫我修改 prompt，服裝更性感",
        "prompt_response": "Premium anime prompt with sensual ceremonial outfit and cinematic lighting logic.",
    }

    first = record_prompt_draft_arsenal_entry(ledger, **kwargs)
    second = record_prompt_draft_arsenal_entry(ledger, **kwargs)

    assert first == second
    assert len(ledger._list("visual_shadow_updates")) == 1


def test_prompt_arsenal_lookup_trigger_builds_concise_context(tmp_path):
    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    record_prompt_draft_arsenal_entry(
        ledger,
        user_prompt="動漫角色 prompt 就好",
        prompt_response="Anime key visual prompt with art-directed silhouette, expressive face, and layered lighting.",
    )

    assert prompt_requests_arsenal_lookup("請翻 prompt 庫，幫我生成一版狐耳角色 prompt")
    context = build_prompt_arsenal_context(
        ledger,
        "請翻 prompt 庫，幫我生成一版狐耳角色 prompt",
        limit=2,
    )

    assert "Visual Prompt Arsenal" in context
    assert "Anime key visual prompt" in context
    assert "Do not copy stale subject details" in context
