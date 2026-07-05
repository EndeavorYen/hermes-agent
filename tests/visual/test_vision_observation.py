from agent.visual.judges.vision_observation import empty_vision_observation
from agent.visual.judges.vision_observation import normalize_vision_observation


def test_normalize_vision_observation_clamps_scores_and_drops_unknowns():
    result = normalize_vision_observation(
        {
            "subject_quality": 1.7,
            "composition": -0.2,
            "artifact_defects": ["blurred_face", "extra_fingers"],
            "raw_prompt": "private prompt text",
            "unknown": "drop me",
            "confidence": 0.8,
            "evidence": {
                "summary": "clear subject, no stretch",
                "private_path": "/Users/simon/.hermes/cache/private.png",
                "provider_response": {"raw": "do not keep"},
            },
        }
    )

    assert result["subject_quality"] == 1.0
    assert result["composition"] == 0.0
    assert result["artifact_defects"] == ["blurred_face", "extra_fingers"]
    assert result["confidence"] == 0.8
    assert result["evidence"] == {"summary": "clear subject, no stretch"}
    assert "raw_prompt" not in result
    assert "unknown" not in result


def test_normalize_vision_observation_defaults_missing_dimensions_to_none_safe_values():
    result = normalize_vision_observation({"confidence": "not-a-number"})

    assert result["confidence"] == 0.0
    assert result["artifact_defects"] == []
    assert result["evidence"] == {}
    assert "subject_quality" not in result


def test_empty_vision_observation_returns_zero_confidence_reason():
    result = empty_vision_observation("vision_unavailable")

    assert result == {
        "confidence": 0.0,
        "artifact_defects": [],
        "evidence": {"reason": "vision_unavailable"},
    }


def test_vision_observation_contract_exports_from_judges_package():
    from agent.visual.judges import empty_vision_observation as exported_empty
    from agent.visual.judges import normalize_vision_observation as exported_normalize

    assert exported_empty("x")["confidence"] == 0.0
    assert exported_normalize({"confidence": 0.5})["confidence"] == 0.5
