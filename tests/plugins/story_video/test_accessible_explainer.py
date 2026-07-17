from __future__ import annotations

from plugins.story_video.accessible_explainer import (
    ACCESSIBLE_EXPLAINER_PROFILE_ID,
    build_explanation_profile,
    resolve_explanation_mode,
    validate_explanation_bundle,
    validate_explanation_profile,
)


def _content_profile(mode: str = "accessible") -> dict:
    return {
        "explanation_profile_id": ACCESSIBLE_EXPLAINER_PROFILE_ID,
        "explanation_mode": mode,
        "supplemental_writer_profile_ids": [ACCESSIBLE_EXPLAINER_PROFILE_ID],
    }


def _review_report(*, include_newcomer_editor: bool = True) -> dict:
    reviewers = []
    if include_newcomer_editor:
        reviewers.append({
            "reviewer_id": "newcomer_comprehension_editor",
            "status": "PASS",
            "score": 92,
            "findings": [],
        })
    return {
        "reviewers": reviewers,
        "accessibility_metrics": {
            "schema": "story_video_accessibility_metrics_v1",
            "status": "PASS",
            "unexplained_jargon": [],
            "baby_talk_detected": False,
            "precision_loss_detected": False,
            "concept_bridges": [
                {
                    "term": "總需求",
                    "segment_id": "S00",
                    "concrete_anchor": "街上的店家同時少了客人",
                    "plain_explanation": "大家少花錢，店家就更難賣出商品",
                    "precision_boundary": "這是理解景氣循環的入口，不是完整模型",
                }
            ],
        },
    }


def test_accessible_explanation_is_the_default_without_childish_tone() -> None:
    profile = build_explanation_profile("故事影片：凱因斯經濟學｜5 分鐘。全自動")

    assert profile["mode"] == "accessible"
    assert profile["activation"] == "default"
    assert profile["scope"] == "explanatory_beats_only"
    assert profile["baby_talk_forbidden"] is True
    assert profile["precision_loss_forbidden"] is True
    assert validate_explanation_profile(profile) == ()


def test_operator_can_choose_advanced_or_professional_explanation() -> None:
    assert resolve_explanation_mode("請做進階版，保留較多技術細節") == "advanced"
    assert resolve_explanation_mode("專業版") == "professional"
    assert resolve_explanation_mode("專業版，不要淺白化") == "professional"
    assert resolve_explanation_mode("停用科普淺白化 skill") == "professional"


def test_do_not_be_childish_does_not_disable_accessible_explanation() -> None:
    assert resolve_explanation_mode("淺顯易懂，但不要幼稚化") == "accessible"
    assert resolve_explanation_mode("不要太艱深，讓一般人也懂") == "accessible"


def test_accessible_bundle_requires_bound_profile_and_newcomer_review() -> None:
    profile = build_explanation_profile("故事影片：凱因斯經濟學")
    ledger = {"production_type": "science_explainer"}

    assert (
        validate_explanation_bundle(
            profile=profile,
            content_profile=_content_profile(),
            review_report=_review_report(),
            ledger=ledger,
            script_text="### S00\n一家店突然少了很多客人。",
        )
        == ()
    )

    missing_reviewer = validate_explanation_bundle(
        profile=profile,
        content_profile=_content_profile(),
        review_report=_review_report(include_newcomer_editor=False),
        ledger=ledger,
        script_text="### S00\n一家店突然少了很多客人。",
    )
    assert (
        "accessible explanation missing newcomer_comprehension_editor"
        in missing_reviewer
    )


def test_accessible_explainer_rejects_unexplained_jargon_and_fake_simplicity() -> None:
    profile = build_explanation_profile("故事影片：凱因斯經濟學")
    report = _review_report()
    report["accessibility_metrics"]["unexplained_jargon"] = ["邊際消費傾向"]
    report["accessibility_metrics"]["precision_loss_detected"] = True

    violations = validate_explanation_bundle(
        profile=profile,
        content_profile=_content_profile(),
        review_report=report,
        ledger={"production_type": "science_explainer"},
        script_text="### S00\n邊際消費傾向下降。",
    )

    assert "accessibility_metrics unexplained_jargon is not empty" in violations
    assert "accessibility_metrics precision_loss_detected is not false" in violations


def test_professional_mode_keeps_binding_but_does_not_require_newcomer_review() -> None:
    profile = build_explanation_profile("專業版，不要淺白化")

    assert (
        validate_explanation_bundle(
            profile=profile,
            content_profile=_content_profile("professional"),
            review_report={"reviewers": []},
            ledger={"production_type": "science_explainer"},
            script_text="### S00\n專業文本。",
        )
        == ()
    )
