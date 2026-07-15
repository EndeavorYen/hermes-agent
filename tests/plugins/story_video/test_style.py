from plugins.story_video.style import (
    compile_style_directive,
    validate_style_bible,
)


def _ledger(**overrides):
    ledger = {
        "quality_contract_version": 4,
        "visual_style": "cinematic natural-history reconstruction",
        "style_bible": {
            "style_id": "natural-history-theatrical-v1",
            "anchor_shot_id": "S00_SH00",
            "medium": "camera-real cinematic factual reconstruction",
            "palette": "mineral earth, storm teal, restrained amber highlights",
            "lighting": "motivated directional light with atmospheric depth",
            "lens_language": "low intimate wide lenses plus evidence close-ups",
            "texture": "credible skin, rock, dust, mist, and filmic grain",
            "atmosphere": "awe, discovery tension, and clean color separation",
            "subject_treatment": "hero subject dominant, factual anatomy preserved",
            "forbidden_drift": [
                "flat museum stock photography",
                "illustration or painterly rendering",
                "glossy CGI or toy-like surfaces",
            ],
        },
        "scenes": [
            {
                "scene_id": "S00",
                "shots": [
                    {"shot_id": "S00_SH00"},
                    {"shot_id": "S00_SH01"},
                ],
            }
        ],
    }
    ledger.update(overrides)
    return ledger


def test_v4_requires_complete_style_bible_and_real_anchor_shot() -> None:
    missing = _ledger()
    missing.pop("style_bible")
    unknown_anchor = _ledger()
    unknown_anchor["style_bible"]["anchor_shot_id"] = "S99_SH99"

    assert "style_bible" in validate_style_bible(missing).violations
    assert (
        "style_bible.anchor_shot_id:unknown:S99_SH99"
        in validate_style_bible(unknown_anchor).violations
    )


def test_style_directive_locks_one_visual_language_and_forbids_drift() -> None:
    directive = compile_style_directive(_ledger())

    assert "Style bible lock: natural-history-theatrical-v1" in directive
    assert "mineral earth, storm teal" in directive
    assert "flat museum stock photography" in directive
    assert "Do not reinterpret the medium, palette, lighting, lens language" in directive


def test_complete_style_bible_passes() -> None:
    report = validate_style_bible(_ledger())

    assert report.ok is True
    assert report.metrics["style_id"] == "natural-history-theatrical-v1"
