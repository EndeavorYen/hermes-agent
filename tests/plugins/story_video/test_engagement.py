from plugins.story_video.engagement import (
    compile_engagement_directives,
    normalize_audience_profile,
    normalize_engagement_profile,
    validate_engagement_ledger,
)


def _shot(index: int, **overrides) -> dict:
    shot = {
        "shot_id": f"S00_SH{index:02d}",
        "engagement_role": "build",
        "attention_hook": "觀眾先看見結果，再追問原因",
        "story_moment": "主體完成一個能改變理解的可見動作",
        "action_consequence": "動作立刻留下可辨識的結果",
        "composition_energy": "curious",
        "viewer_emotion": "curiosity",
        "engagement_criteria": ["the decisive instant is readable in one glance"],
        "visual_truth_mode": "direct_evidence",
    }
    shot.update(overrides)
    return shot


def _ledger(shots: list[dict], **overrides) -> dict:
    ledger = {
        "quality_contract_version": 3,
        "audience_profile": {
            "age_band": "general",
            "knowledge_level": "newcomer",
            "attention_style": "curious_explorer",
            "safety_intensity": "standard",
        },
        "engagement_profile": {
            "mode": "discovery_documentary",
            "energy": "balanced",
            "humor": "none",
            "sensationalism_forbidden": True,
        },
        "production_type": "documentary",
        "scenes": [{"scene_id": "S00", "shots": shots}],
    }
    ledger.update(overrides)
    return ledger


def test_default_profile_is_general_not_child_specific() -> None:
    assert normalize_audience_profile({}) == {
        "age_band": "general",
        "knowledge_level": "newcomer",
        "attention_style": "curious_explorer",
        "safety_intensity": "standard",
    }
    assert normalize_engagement_profile({})["mode"] == "discovery_documentary"


def test_explicit_young_explorer_compiles_without_topic_cliches() -> None:
    ledger = _ledger(
        [_shot(0)],
        audience_profile={
            "age_band": "early_childhood",
            "knowledge_level": "newcomer",
            "attention_style": "concrete_fast",
            "safety_intensity": "gentle",
        },
        engagement_profile={
            "mode": "young_explorer",
            "energy": "high",
            "humor": "light",
            "sensationalism_forbidden": True,
        },
    )

    directives = " ".join(compile_engagement_directives(ledger, _shot(0)))

    assert "early_childhood" in directives
    assert "young_explorer" in directives
    assert "decisive visible instant" in directives
    assert "chase" not in directives.lower()
    assert "dust" not in directives.lower()


def test_v2_ledger_does_not_require_engagement_fields() -> None:
    report = validate_engagement_ledger(
        {"quality_contract_version": 2, "scenes": [{"scene_id": "S00", "shots": [{}]}]}
    )

    assert report.ok is True
    assert report.violations == ()


def test_v3_ledger_requires_universal_engagement_fields() -> None:
    report = validate_engagement_ledger(_ledger([{"shot_id": "S00_SH00"}]))

    assert report.ok is False
    assert "S00_SH00.story_moment" in report.violations
    assert "S00_SH00.visual_truth_mode" in report.violations


def test_v3_ledger_rejects_unknown_engagement_energy_and_humor() -> None:
    report = validate_engagement_ledger(
        _ledger(
            [_shot(0)],
            engagement_profile={
                "mode": "discovery_documentary",
                "energy": "maximum_everywhere",
                "humor": "random_gags",
                "sensationalism_forbidden": True,
            },
        )
    )

    assert "engagement_profile.energy:maximum_everywhere" in report.violations
    assert "engagement_profile.humor:random_gags" in report.violations


def test_intentional_breathe_requires_calm_reason() -> None:
    report = validate_engagement_ledger(
        _ledger([_shot(0, engagement_role="breathe", composition_energy="calm")])
    )

    assert "S00_SH00.calm_reason" in report.violations

    passing = validate_engagement_ledger(
        _ledger(
            [
                _shot(
                    0,
                    engagement_role="breathe",
                    composition_energy="calm",
                    calm_reason="讓觀眾消化剛揭示的因果關係",
                )
            ]
        )
    )
    assert passing.ok is True


def test_three_repeated_roles_require_an_intentional_reason() -> None:
    report = validate_engagement_ledger(
        _ledger([_shot(0), _shot(1), _shot(2)])
    )

    assert "repeated_engagement_role_without_reason:build:3" in report.violations
    assert "repeated_composition_energy_without_reason:curious:3" in report.violations


def test_mixed_evidence_and_reconstruction_requires_bridge() -> None:
    report = validate_engagement_ledger(
        _ledger([_shot(0, visual_truth_mode="mixed_evidence_reconstruction")])
    )

    assert "S00_SH00.evidence_bridge" in report.violations

    passing = validate_engagement_ledger(
        _ledger(
            [
                _shot(
                    0,
                    visual_truth_mode="mixed_evidence_reconstruction",
                    evidence_bridge="先呈現可見證據，再明確轉入有根據的重建",
                )
            ]
        )
    )
    assert passing.ok is True


def test_topic_adapter_changes_method_without_forcing_spectacle() -> None:
    shot = _shot(0, visual_truth_mode="process")
    science = " ".join(
        compile_engagement_directives(
            _ledger([shot], production_type="science_explainer"), shot
        )
    )
    cooking = " ".join(
        compile_engagement_directives(_ledger([shot], production_type="cooking"), shot)
    )

    assert "mechanism, discovery, or scale" in science
    assert "transformation, texture, or reveal" in cooking
    assert "spectacle" not in cooking.lower()
