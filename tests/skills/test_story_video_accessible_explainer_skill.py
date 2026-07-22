from __future__ import annotations

from pathlib import Path


SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "creative"
    / "story-video-accessible-explainer"
)


def test_accessible_explainer_skill_is_modular_and_operator_controllable() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    lowered = text.lower()

    assert "name: story-video-accessible-explainer" in text
    assert "Use when" in text
    assert "explanatory_profile.json" not in text
    assert "explanation_profile.json" in text
    assert "accessible" in text
    assert "advanced" in text
    assert "professional" in text
    assert "baby talk" in lowered
    assert "concrete intuition" in lowered
    assert "formal term" in lowered
    assert "precision boundary" in lowered
    assert "story-video-production-pipeline" in text


def test_accessible_explainer_skill_has_a_separate_quality_contract() -> None:
    contract = (
        SKILL_ROOT / "references" / "accessible-explanation-contract.md"
    ).read_text(encoding="utf-8")

    assert "story_video_accessible_explanation_v1" in contract
    assert "story_video_accessibility_metrics_v1" in contract
    assert "newcomer_comprehension_editor" in contract
    assert "unexplained_jargon" in contract
    assert "precision_loss_detected" in contract
