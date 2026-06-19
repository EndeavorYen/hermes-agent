from __future__ import annotations

import json


def _write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )


def test_disabled_mediator_returns_original_prompt(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    mediated = mediate_image2_prompt(
        "simple product photo",
        config={"enabled": False, "memory_path": str(tmp_path / "memory.jsonl")},
        draft_fn=lambda prompt: "should not be used",
    )

    assert mediated.final_prompt == "simple product photo"
    assert mediated.strategy == "codex_direct"
    assert mediated.draft_prompt == ""


def test_hybrid_refine_uses_qwen_draft_but_preserves_element_locks(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    mediated = mediate_image2_prompt(
        "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，要性感但高級",
        config={
            "enabled": True,
            "memory_path": str(tmp_path / "memory.jsonl"),
            "qwen_json_contract": False,
        },
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: (
            "A glamorous woman in a city night scene, holding black stock flower (Anemone, matthiola), "
            "wearing a sleek evening dress with cinematic lighting."
        ),
    )

    assert mediated.strategy == "hybrid_refine"
    assert mediated.draft_model == "test-image-prompt-draft-model"
    assert "black lisianthus flowers, also known as eustoma" in mediated.final_prompt
    assert "satin evening gown" in mediated.final_prompt
    assert "rainy night in Taipei" in mediated.final_prompt
    assert "reference identity" in mediated.final_prompt
    assert mediated.object_locks_added.count("black lisianthus flowers, also known as eustoma") == 1
    assert "lisianthus flowers, also known as eustoma" not in mediated.object_locks_added
    assert "black roses" not in mediated.final_prompt
    assert "Anemone" not in mediated.final_prompt
    assert "matthiola" not in mediated.final_prompt
    assert "stock flower" not in mediated.final_prompt


def test_rejects_non_json_qwen_draft_when_json_contract_is_required(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    mediated = mediate_image2_prompt(
        "手拿黑色洋桔梗，成熟時尚雜誌感",
        config={
            "enabled": True,
            "memory_path": str(tmp_path / "memory.jsonl"),
            "qwen_json_contract": True,
        },
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: "A pretty gothic portrait holding black roses.",
    )

    assert mediated.qwen_validation_status == "malformed"
    assert mediated.draft_prompt == "A pretty gothic portrait holding black roses."
    assert "black roses" not in mediated.final_prompt
    assert "black lisianthus flowers, also known as eustoma" in mediated.final_prompt


def test_accepts_qwen_json_candidate_with_preserved_constraints(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    qwen_json = {
        "schema_version": "qwen_image_prompt_draft.v1",
        "candidates": [{
            "candidate_id": "q1",
            "positive_prompt": (
                "A mature fashion editorial portrait in a rainy night in Taipei, "
                "holding black lisianthus flowers, also known as eustoma, wearing a satin evening gown."
            ),
            "style_tags": ["fashion editorial"],
            "lighting": ["cinematic rain reflections"],
            "camera": ["85mm portrait"],
            "invented_elements": [],
            "risky_or_counterproductive_terms": [],
            "constraint_preservation_report": [
                {
                    "lock_id": "lock_1",
                    "expected": "black lisianthus flowers, also known as eustoma",
                    "status": "preserved",
                    "evidence": "candidate uses black lisianthus/eustoma",
                },
                {
                    "lock_id": "lock_2",
                    "expected": "satin evening gown",
                    "status": "preserved",
                    "evidence": "candidate uses satin evening gown",
                },
            ],
        }],
    }

    mediated = mediate_image2_prompt(
        "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，要性感但高級",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: json.dumps(qwen_json),
    )

    assert mediated.qwen_candidate_id == "q1"
    assert mediated.qwen_validation_status == "accepted"
    assert "black lisianthus flowers, also known as eustoma" in mediated.final_prompt
    assert "satin evening gown" in mediated.final_prompt


def test_extracts_qwen_json_candidate_from_wrapped_response(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    qwen_json = {
        "schema_version": "qwen_image_prompt_draft.v1",
        "candidates": [{
            "candidate_id": "q1",
            "positive_prompt": (
                "A mature magazine portrait holding black lisianthus flowers, "
                "also known as eustoma, with clean editorial lighting."
            ),
            "style_tags": ["fashion editorial"],
            "lighting": ["clean studio"],
            "camera": ["portrait"],
            "invented_elements": [],
            "risky_or_counterproductive_terms": [],
            "constraint_preservation_report": [{
                "lock_id": "flower_species_001",
                "expected": "black lisianthus flowers, also known as eustoma",
                "status": "preserved",
                "evidence": "candidate uses black lisianthus/eustoma",
            }],
        }],
    }

    mediated = mediate_image2_prompt(
        "手拿黑色洋桔梗，成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: "Sure, JSON follows:\n```json\n"
        + json.dumps(qwen_json)
        + "\n```",
    )

    assert mediated.qwen_candidate_id == "q1"
    assert mediated.qwen_validation_status == "accepted"


def test_extracts_typed_constraint_locks_for_phase3_intent_graph():
    from tools.image2_adaptive_mediator import extract_image2_intent

    intent = extract_image2_intent(
        "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，保留原本構圖和姿勢，要成熟時尚雜誌感"
    )
    locks = intent.to_dict()["constraint_locks"]
    categories = {lock["category"] for lock in locks}

    assert categories >= {"identity", "scene", "clothing", "object", "composition", "pose", "style"}
    assert {
        "category": "object",
        "canonical": "black lisianthus flowers, also known as eustoma",
        "source": "黑色洋桔梗",
        "hard": True,
    } in locks
    assert {
        "category": "identity",
        "canonical": "reference identity",
        "source": "reference identity",
        "hard": True,
    } in locks


def test_rejects_qwen_json_candidate_that_violates_must_keep(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    qwen_json = {
        "schema_version": "qwen_image_prompt_draft.v1",
        "candidates": [{
            "candidate_id": "q1",
            "positive_prompt": "A gothic portrait holding black roses in a rainy city.",
            "style_tags": ["gothic"],
            "lighting": ["moody"],
            "camera": ["portrait"],
            "invented_elements": ["black rose"],
            "risky_or_counterproductive_terms": [],
            "constraint_preservation_report": [{
                "lock_id": "flower_species_001",
                "expected": "black lisianthus flowers, also known as eustoma",
                "status": "violated",
                "found_problem": "candidate used black rose",
                "action": "reject_candidate",
            }],
        }],
    }

    mediated = mediate_image2_prompt(
        "手拿黑色洋桔梗，成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: json.dumps(qwen_json),
    )

    assert mediated.qwen_candidate_id == ""
    assert mediated.qwen_validation_status == "rejected"
    assert "black roses" not in mediated.final_prompt
    assert "black lisianthus flowers, also known as eustoma" in mediated.final_prompt


def test_accepts_top_level_qwen_candidate_shape_after_validation(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    qwen_json = {
        "schema_version": "qwen_image_prompt_draft.v1",
        "candidate_id": "q1",
        "positive_prompt": (
            "A fashion editorial portrait holding black lisianthus flowers, also known as eustoma, "
            "wearing a satin evening gown in a rainy night in Taipei."
        ),
        "style_tags": ["fashion editorial"],
        "lighting": ["rain reflections"],
        "camera": ["portrait"],
        "invented_elements": [],
        "risky_or_counterproductive_terms": [],
        "constraint_preservation_report": [{
            "lock_id": "flower",
            "expected": "black lisianthus flowers, also known as eustoma",
            "status": "preserved",
            "evidence": "uses black lisianthus/eustoma",
        }],
    }

    mediated = mediate_image2_prompt(
        "在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，要成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: json.dumps(qwen_json),
    )

    assert mediated.qwen_candidate_id == "q1"
    assert mediated.qwen_validation_status == "accepted"


def test_rejects_lily_substitution_for_lisianthus_lock(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    qwen_json = {
        "schema_version": "qwen_image_prompt_draft.v1",
        "candidate_id": "q1",
        "positive_prompt": "A fashion editorial portrait holding black lilies (lisianthus/eustoma).",
        "style_tags": ["fashion editorial"],
        "lighting": [],
        "camera": [],
        "invented_elements": ["black lilies"],
        "risky_or_counterproductive_terms": [],
        "constraint_preservation_report": [{
            "lock_id": "flower",
            "expected": "black lisianthus flowers, also known as eustoma",
            "status": "preserved",
            "evidence": "claims lisianthus/eustoma",
        }],
    }

    mediated = mediate_image2_prompt(
        "手拿黑色洋桔梗，要成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: json.dumps(qwen_json),
    )

    assert mediated.qwen_validation_status == "rejected"
    assert "black lilies" not in mediated.final_prompt
    assert "black lisianthus flowers, also known as eustoma" in mediated.final_prompt


def test_rejects_qwen_candidate_with_identity_clothing_and_scene_drift(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    qwen_json = {
        "schema_version": "qwen_image_prompt_draft.v1",
        "candidates": [{
            "candidate_id": "q1",
            "positive_prompt": (
                "A generic model with a different face in a Paris ballroom, "
                "wearing a leather jacket while holding black lisianthus flowers, also known as eustoma."
            ),
            "style_tags": ["fashion editorial"],
            "lighting": ["studio"],
            "camera": ["portrait"],
            "invented_elements": ["Paris ballroom", "leather jacket", "generic model"],
            "risky_or_counterproductive_terms": [],
            "constraint_preservation_report": [{
                "lock_id": "all",
                "expected": "reference identity, rainy night in Taipei, satin evening gown",
                "status": "preserved",
                "evidence": "claims all locks are preserved",
            }],
        }],
    }

    mediated = mediate_image2_prompt(
        "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，要成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: json.dumps(qwen_json),
    )

    problems = {
        item["found_problem"]
        for item in mediated.qwen_constraint_report
        if item.get("action") == "reject_candidate"
    }
    assert mediated.qwen_validation_status == "rejected"
    assert "reference identity weakened or replaced" in problems
    assert "clothing lock changed or contradicted" in problems
    assert "scene lock changed or contradicted" in problems
    assert "Paris ballroom" not in mediated.final_prompt
    assert "leather jacket" not in mediated.final_prompt


def test_final_prompt_compiler_uses_stable_section_order_for_hard_locks_first(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    qwen_json = {
        "schema_version": "qwen_image_prompt_draft.v1",
        "candidates": [{
            "candidate_id": "q1",
            "positive_prompt": (
                "A mature fashion editorial portrait in rainy night in Taipei, wearing a satin evening gown, "
                "holding black lisianthus flowers, also known as eustoma, premium studio lighting, 85mm camera."
            ),
            "style_tags": ["fashion editorial"],
            "lighting": ["premium studio lighting"],
            "camera": ["85mm portrait"],
            "invented_elements": [],
            "risky_or_counterproductive_terms": [],
            "constraint_preservation_report": [{
                "lock_id": "all",
                "expected": "reference identity, rainy night in Taipei, satin evening gown, black lisianthus",
                "status": "preserved",
                "evidence": "uses all visible locks",
            }],
        }],
    }

    mediated = mediate_image2_prompt(
        "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，保留原本構圖和姿勢，要成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: json.dumps(qwen_json),
    )

    final_prompt = mediated.final_prompt
    expected_order = [
        "Hard locks:",
        "Subject:",
        "Composition:",
        "Style and mood:",
        "Lighting and camera:",
        "Provider-safe framing:",
    ]
    positions = [final_prompt.index(section) for section in expected_order]
    assert positions == sorted(positions)
    assert "no bold editorial framing" not in final_prompt
    assert "explicit" not in final_prompt.lower()


def test_qwen_request_uses_compact_filtered_memory_hints(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    memory_path = tmp_path / "adaptive.jsonl"
    memory_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "attempt",
            "user_concept": "OLD RAW USER CONCEPT THAT MUST NOT BE SENT",
            "strategy": "hybrid_refine",
            "image2_status": "success",
            "worked_phrases": ["cinematic fashion-editorial lighting"],
            "avoid_phrases": ["black rose"],
            "object_locks_added": ["black lisianthus flowers, also known as eustoma"],
            "failure_class": ["object_drift"],
        }),
        encoding="utf-8",
    )
    captured_request = {}

    def draft_fn(prompt: str) -> str:
        captured_request.update(json.loads(prompt))
        return json.dumps({
            "schema_version": "qwen_image_prompt_draft.v1",
            "candidates": [{
                "candidate_id": "q1",
                "positive_prompt": "black lisianthus flowers, also known as eustoma, fashion editorial",
                "style_tags": [],
                "lighting": [],
                "camera": [],
                "invented_elements": [],
                "risky_or_counterproductive_terms": [],
                "constraint_preservation_report": [{
                    "lock_id": "flower_species_001",
                    "expected": "black lisianthus flowers, also known as eustoma",
                    "status": "preserved",
                    "evidence": "uses eustoma",
                }],
            }],
        })

    mediate_image2_prompt(
        "手拿黑色洋桔梗，成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(memory_path)},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=draft_fn,
    )

    hints = captured_request["compact_memory_hints"]
    assert hints["worked_phrases"] == ["cinematic fashion-editorial lighting"]
    assert hints["avoid_phrases"] == ["black rose"]
    assert hints["hard_lessons"] == [
        "Do not substitute black lisianthus flowers, also known as eustoma."
    ]
    assert "OLD RAW USER CONCEPT THAT MUST NOT BE SENT" not in json.dumps(
        hints,
        ensure_ascii=False,
    )


def test_qwen_request_keeps_json_contract_compact_for_local_model_stability():
    from tools.image2_adaptive_mediator import (
        build_qwen_image_prompt_draft_request,
        extract_image2_intent,
    )

    request = json.loads(build_qwen_image_prompt_draft_request(
        "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，保留原本構圖和姿勢，要成熟時尚雜誌感",
        extract_image2_intent(
            "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，保留原本構圖和姿勢，要成熟時尚雜誌感"
        ),
    ))

    assert request["output_schema"]["max_constraint_report_items"] == 4
    assert request["output_schema"]["positive_prompt_max_chars"] == 900
    assert "At most 4 constraint_preservation_report items" in request["rules"]


def test_exact_repeat_reuses_previous_success_without_calling_qwen(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    memory_path = tmp_path / "adaptive.jsonl"
    memory_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "attempt",
            "user_concept": "手拿黑色洋桔梗，成熟時尚雜誌感",
            "strategy": "hybrid_refine",
            "image2_status": "success",
            "final_prompt": "previous successful compiled Image2 prompt",
        }),
        encoding="utf-8",
    )

    def draft_fn(prompt: str) -> str:
        raise AssertionError("exact repeats should not call qwen")

    mediated = mediate_image2_prompt(
        "手拿黑色洋桔梗，成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(memory_path)},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=draft_fn,
    )

    assert mediated.strategy == "reuse_exact_success"
    assert mediated.draft_model == "memory"
    assert mediated.final_prompt == "previous successful compiled Image2 prompt"
    assert mediated.qwen_validation_status == "not_called_exact_repeat"


def test_strategy_reason_records_hard_lock_routing(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    mediated = mediate_image2_prompt(
        "固定 reference 人物面容，在台北雨夜穿緞面晚禮服，手拿黑色洋桔梗，保留原本構圖和姿勢，要成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(tmp_path / "memory.jsonl")},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: "",
    )

    assert mediated.strategy == "hybrid_refine"
    assert "hard locks" in mediated.strategy_reason
    assert mediated.to_public_dict()["strategy_reason"] == mediated.strategy_reason


def test_recent_blocked_attempt_routes_to_safe_reframe(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    memory_path = tmp_path / "adaptive.jsonl"
    memory_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "attempt",
            "user_concept": "成熟時尚棚拍人物，要性感但高級",
            "strategy": "hybrid_refine",
            "image2_status": "blocked",
            "failure_class": ["blocked"],
        }),
        encoding="utf-8",
    )

    mediated = mediate_image2_prompt(
        "成熟時尚棚拍人物，要性感但高級",
        config={"enabled": True, "memory_path": str(memory_path)},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: "should not be needed for safe reframe",
    )

    assert mediated.strategy == "safe_reframe"
    assert "blocked" in mediated.strategy_reason


def test_recent_object_drift_feedback_routes_to_element_lock_without_qwen(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    memory_path = tmp_path / "adaptive.jsonl"
    memory_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "user_feedback",
            "user_concept": "手拿黑色洋桔梗，要成熟時尚雜誌感",
            "strategy": "hybrid_refine",
            "image2_status": "feedback",
            "failure_class": ["object_drift"],
            "feedback_text": "花錯，物件漂移",
        }),
        encoding="utf-8",
    )

    def draft_fn(prompt: str) -> str:
        raise AssertionError("element_lock repair should not call qwen")

    mediated = mediate_image2_prompt(
        "手拿黑色洋桔梗，要成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(memory_path)},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=draft_fn,
    )

    assert mediated.strategy == "element_lock"
    assert "object_drift" in mediated.strategy_reason
    assert mediated.draft_prompt == ""


def test_recent_too_tame_feedback_keeps_hybrid_refine_with_intensity_reason(tmp_path):
    from tools.image2_adaptive_mediator import mediate_image2_prompt

    memory_path = tmp_path / "adaptive.jsonl"
    memory_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "user_feedback",
            "user_concept": "成熟時尚棚拍人物，要性感但高級",
            "strategy": "hybrid_refine",
            "image2_status": "feedback",
            "failure_class": ["too_tame"],
            "feedback_text": "太保守",
        }),
        encoding="utf-8",
    )

    mediated = mediate_image2_prompt(
        "成熟時尚棚拍人物，要性感但高級",
        config={"enabled": True, "memory_path": str(memory_path)},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=lambda prompt: "",
    )

    assert mediated.strategy == "hybrid_refine"
    assert "increase mature editorial intensity" in mediated.strategy_reason


def test_records_attempt_memory_as_jsonl(tmp_path):
    from tools.image2_adaptive_mediator import (
        mediate_image2_prompt,
        record_image2_mediator_attempt,
    )

    memory_path = tmp_path / "adaptive.jsonl"
    mediated = mediate_image2_prompt(
        "cinematic fashion portrait",
        config={"enabled": True, "memory_path": str(memory_path)},
        draft_fn=lambda prompt: "cinematic fashion portrait with premium lighting",
    )

    record_image2_mediator_attempt(
        mediated,
        image2_status="success",
        feedback_source="image2_error",
        failure_class=[],
        config={"enabled": True, "memory_path": str(memory_path)},
    )

    lines = memory_path.read_text().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["strategy"] == mediated.strategy
    assert payload["image2_status"] == "success"
    assert payload["intent"]["subject"] == "cinematic fashion portrait"
    assert payload["scores"]["safety_feasibility"] == 1
    assert payload["qwen_validation_status"] == mediated.qwen_validation_status
    assert payload["strategy_reason"] == mediated.strategy_reason


def test_records_attempt_to_split_attempts_jsonl_when_memory_dir_configured(tmp_path):
    from tools.image2_adaptive_mediator import (
        mediate_image2_prompt,
        record_image2_mediator_attempt,
    )

    memory_dir = tmp_path / "image2_memory"
    mediated = mediate_image2_prompt(
        "cinematic fashion portrait",
        config={"enabled": True, "memory_dir": str(memory_dir)},
    )

    record_image2_mediator_attempt(
        mediated,
        image2_status="success",
        config={"enabled": True, "memory_dir": str(memory_dir), "log_attempts": True},
    )

    attempt_path = memory_dir / "attempts.jsonl"
    assert attempt_path.exists()
    payload = json.loads(attempt_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["record_type"] == "attempt"
    assert payload["user_concept"] == "cinematic fashion portrait"
    assert payload["image2_status"] == "success"


def test_records_qwen_call_to_split_qwen_calls_jsonl_when_memory_dir_configured(tmp_path):
    from tools.image2_adaptive_mediator import record_qwen_call_health

    memory_dir = tmp_path / "image2_memory"

    record_qwen_call_health(
        status="accepted",
        latency_ms=100,
        model="test-image-prompt-draft-model",
        base_url="http://example.invalid:11434/v1",
        transport="curl",
        config={"enabled": True, "memory_dir": str(memory_dir), "log_attempts": True},
    )

    qwen_path = memory_dir / "qwen_calls.jsonl"
    assert qwen_path.exists()
    payload = json.loads(qwen_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["record_type"] == "qwen_call"
    assert payload["status"] == "accepted"


def test_summarizes_recent_mediator_memory(tmp_path):
    from tools.image2_adaptive_mediator import summarize_image2_mediator_memory

    memory_path = tmp_path / "adaptive.jsonl"
    memory_path.write_text(
        "\n".join([
            json.dumps({
                "timestamp": "2026-06-15T00:00:00+00:00",
                "record_type": "attempt",
                "user_concept": "portrait one",
                "strategy": "hybrid_refine",
                "image2_status": "success",
                "failure_class": [],
            }),
            json.dumps({
                "timestamp": "2026-06-15T00:01:00+00:00",
                "record_type": "attempt",
                "user_concept": "portrait two",
                "strategy": "safe_reframe",
                "image2_status": "blocked",
                "failure_class": ["blocked"],
            }),
            json.dumps({
                "timestamp": "2026-06-15T00:02:00+00:00",
                "record_type": "user_feedback",
                "user_concept": "portrait two",
                "strategy": "safe_reframe",
                "image2_status": "feedback",
                "failure_class": ["too_tame"],
                "feedback_text": "太保守",
            }),
        ]),
        encoding="utf-8",
    )

    summary = summarize_image2_mediator_memory(
        config={"memory_path": str(memory_path)},
        limit=2,
    )

    assert summary["attempt_count"] == 2
    assert summary["feedback_count"] == 1
    assert summary["status_counts"] == {"blocked": 1, "success": 1}
    assert summary["strategy_counts"] == {"hybrid_refine": 1, "safe_reframe": 1}
    assert summary["failure_class_counts"] == {"blocked": 1, "too_tame": 1}
    assert summary["sample_confidence"] == "low"
    assert [item["user_concept"] for item in summary["recent"]] == [
        "portrait two",
        "portrait two",
    ]


def test_summarizes_split_and_legacy_memory_without_dropping_history(tmp_path):
    from tools.image2_adaptive_mediator import summarize_image2_mediator_memory

    legacy_path = tmp_path / "legacy.jsonl"
    memory_dir = tmp_path / "image2_memory"
    memory_dir.mkdir()
    legacy_path.write_text(
        json.dumps({
            "timestamp": "2026-06-14T23:50:00+00:00",
            "record_type": "attempt",
            "user_concept": "legacy portrait",
            "strategy": "hybrid_refine",
            "image2_status": "success",
        }),
        encoding="utf-8",
    )
    (memory_dir / "attempts.jsonl").write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "attempt",
            "user_concept": "split portrait",
            "strategy": "safe_reframe",
            "image2_status": "blocked",
            "failure_class": ["blocked"],
        }),
        encoding="utf-8",
    )
    (memory_dir / "qwen_calls.jsonl").write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:01:00+00:00",
            "record_type": "qwen_call",
            "status": "accepted",
            "latency_ms": 2500,
        }),
        encoding="utf-8",
    )
    (memory_dir / "user_feedback.jsonl").write_text(
        json.dumps({
            "timestamp": "2026-06-15T00:02:00+00:00",
            "record_type": "user_feedback",
            "user_concept": "split portrait",
            "strategy": "safe_reframe",
            "image2_status": "feedback",
            "failure_class": ["too_tame"],
            "feedback_text": "太保守",
        }),
        encoding="utf-8",
    )

    summary = summarize_image2_mediator_memory(
        config={"memory_path": str(legacy_path), "memory_dir": str(memory_dir)},
        limit=4,
        now="2026-06-15T00:30:00+00:00",
    )

    assert summary["attempt_count"] == 2
    assert summary["feedback_count"] == 1
    assert summary["status_counts"] == {"blocked": 1, "success": 1}
    assert summary["qwen_health"]["status"] == "healthy"
    assert summary["qwen_health"]["call_count_24h"] == 1


def test_summarizes_qwen_health_from_attempt_memory(tmp_path):
    from tools.image2_adaptive_mediator import summarize_image2_mediator_memory

    memory_path = tmp_path / "adaptive.jsonl"
    memory_path.write_text(
        "\n".join([
            json.dumps({
                "timestamp": "2026-06-15T00:00:00+00:00",
                "record_type": "attempt",
                "user_concept": "portrait one",
                "strategy": "hybrid_refine",
                "image2_status": "success",
                "qwen_validation_status": "accepted",
            }),
            json.dumps({
                "timestamp": "2026-06-15T00:01:00+00:00",
                "record_type": "attempt",
                "user_concept": "portrait two",
                "strategy": "hybrid_refine",
                "image2_status": "success",
                "qwen_validation_status": "malformed",
            }),
        ]),
        encoding="utf-8",
    )

    summary = summarize_image2_mediator_memory(
        config={"memory_path": str(memory_path)},
        limit=2,
    )

    assert summary["qwen_health"]["status"] == "degraded"
    assert summary["qwen_health"]["status_counts"] == {"accepted": 1, "malformed": 1}
    assert summary["qwen_health"]["fallback_rate"] == 0.5
    assert summary["qwen_health"]["malformed_json_rate"] == 0.5


def test_records_qwen_call_health_event_as_jsonl(tmp_path):
    from tools.image2_adaptive_mediator import record_qwen_call_health

    memory_path = tmp_path / "adaptive.jsonl"

    record_qwen_call_health(
        status="accepted",
        latency_ms=1234.56,
        model="test-image-prompt-draft-model",
        base_url="http://example.invalid:11434/v1",
        transport="curl",
        config={"enabled": True, "memory_path": str(memory_path), "log_attempts": True},
        response_chars=2048,
    )

    payload = json.loads(memory_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["record_type"] == "qwen_call"
    assert payload["status"] == "accepted"
    assert payload["latency_ms"] == 1234.56
    assert payload["model"] == "test-image-prompt-draft-model"
    assert payload["base_url"] == "http://example.invalid:11434/v1"
    assert payload["transport"] == "curl"
    assert payload["response_chars"] == 2048
    assert payload["error_type"] == ""


def test_records_failed_qwen_call_health_event_without_prompt_leak(tmp_path):
    from tools.image2_adaptive_mediator import record_qwen_call_health

    memory_path = tmp_path / "adaptive.jsonl"

    record_qwen_call_health(
        status="offline",
        latency_ms=45.1,
        model="test-image-prompt-draft-model",
        base_url="http://example.invalid:11434/v1",
        transport="curl",
        config={"enabled": True, "memory_path": str(memory_path), "log_attempts": True},
        error_type="connection_failed",
        error_message="No route to host while sending RAW USER PROMPT",
    )

    payload = json.loads(memory_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["record_type"] == "qwen_call"
    assert payload["status"] == "offline"
    assert payload["error_type"] == "connection_failed"
    assert payload["error_message"] == "No route to host while sending RAW USER PROMPT"[:120]
    assert "prompt" not in payload
    assert "request" not in payload


def test_qwen_health_report_prefers_call_events_and_24h_window(tmp_path):
    from tools.image2_adaptive_mediator import summarize_image2_mediator_memory

    memory_path = tmp_path / "adaptive.jsonl"
    records = [
        {
            "timestamp": "2026-06-13T00:00:00+00:00",
            "record_type": "qwen_call",
            "status": "malformed",
            "latency_ms": 1000,
            "model": "test-image-prompt-draft-model",
        },
        {
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "qwen_call",
            "status": "accepted",
            "latency_ms": 1000,
            "model": "test-image-prompt-draft-model",
        },
        {
            "timestamp": "2026-06-15T00:05:00+00:00",
            "record_type": "qwen_call",
            "status": "offline",
            "latency_ms": 3000,
            "model": "test-image-prompt-draft-model",
            "error_type": "connection_failed",
        },
        {
            "timestamp": "2026-06-15T00:10:00+00:00",
            "record_type": "qwen_call",
            "status": "malformed",
            "latency_ms": 5000,
            "model": "test-image-prompt-draft-model",
            "error_type": "malformed_json",
        },
    ]
    memory_path.write_text(
        "\n".join(json.dumps(record) for record in records),
        encoding="utf-8",
    )

    summary = summarize_image2_mediator_memory(
        config={"memory_path": str(memory_path)},
        limit=5,
        now="2026-06-15T00:30:00+00:00",
    )

    health = summary["qwen_health"]
    assert health["status"] == "degraded"
    assert health["window_hours"] == 24
    assert health["call_count_24h"] == 3
    assert health["status_counts_24h"] == {
        "accepted": 1,
        "malformed": 1,
        "offline": 1,
    }
    assert health["last_success_at"] == "2026-06-15T00:00:00+00:00"
    assert health["last_failure_at"] == "2026-06-15T00:10:00+00:00"
    assert health["fallback_rate_24h"] == 0.6667
    assert health["malformed_json_rate_24h"] == 0.3333
    assert health["timeout_rate_24h"] == 0.0
    assert health["p50_latency_ms"] == 3000
    assert health["p95_latency_ms"] == 5000


def test_records_user_feedback_as_append_only_event(tmp_path):
    from tools.image2_adaptive_mediator import (
        mediate_image2_prompt,
        record_image2_mediator_attempt,
        record_image2_user_feedback,
    )

    memory_path = tmp_path / "adaptive.jsonl"
    mediated = mediate_image2_prompt(
        "cinematic fashion portrait",
        config={"enabled": True, "memory_path": str(memory_path)},
        draft_fn=lambda prompt: "cinematic fashion portrait with premium lighting",
    )
    record_image2_mediator_attempt(
        mediated,
        image2_status="success",
        config={"enabled": True, "memory_path": str(memory_path)},
    )

    feedback = record_image2_user_feedback(
        "太保守，不夠性感，保留這版但加強眼神",
        config={"enabled": True, "memory_path": str(memory_path)},
    )

    lines = memory_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[-1])
    assert feedback["failure_class"] == ["too_tame", "not_sexy_enough", "partial_success"]
    assert feedback["scores"]["user_satisfaction"] == 3
    assert feedback["next_strategy"] == "hybrid_refine"
    assert payload["record_type"] == "user_feedback"
    assert payload["feedback_source"] == "user"
    assert payload["feedback_text"] == "太保守，不夠性感，保留這版但加強眼神"
    assert payload["target_timestamp"] == json.loads(lines[0])["timestamp"]
    assert "increase sensuality through gaze" in payload["worked_phrases"]


def test_user_feedback_negative_style_words_are_not_misread_as_praise(tmp_path):
    from tools.image2_adaptive_mediator import record_image2_user_feedback

    memory_path = tmp_path / "adaptive.jsonl"
    _write_jsonl(memory_path, [{
        "timestamp": "2026-06-15T00:00:00+00:00",
        "record_type": "attempt",
        "user_concept": "glamour character editorial",
        "strategy": "hybrid_refine",
        "image2_status": "success",
        "failure_class": [],
    }])

    feedback = record_image2_user_feedback(
        "bad style, outside the reference library",
        config={"enabled": True, "memory_path": str(memory_path)},
    )

    assert "excellent" not in feedback["failure_class"]
    assert feedback["failure_class"] == ["style_mismatch", "visual_arsenal_miss"]
    assert feedback["scores"]["user_satisfaction"] == 1
    assert feedback["next_strategy"] == "post_failure_repair"
    assert "generic cosplay style" in feedback["avoid_phrases"]


def test_user_feedback_mixed_batch_review_preserves_failures(tmp_path):
    from tools.image2_adaptive_mediator import record_image2_user_feedback

    memory_path = tmp_path / "adaptive.jsonl"
    _write_jsonl(memory_path, [{
        "timestamp": "2026-06-15T00:00:00+00:00",
        "record_type": "attempt",
        "user_concept": "fantasy character catalog batch",
        "strategy": "hybrid_refine",
        "image2_status": "success",
        "failure_class": [],
    }])

    feedback = record_image2_user_feedback(
        "G4 過關；G1/G3 design drift；G2 not pretty enough and not glamorous enough",
        config={"enabled": True, "memory_path": str(memory_path)},
    )

    assert "excellent" not in feedback["failure_class"]
    assert feedback["failure_class"] == [
        "partial_success",
        "persona_drift",
        "not_beautiful_enough",
        "not_sexy_enough",
    ]
    assert feedback["scores"]["user_satisfaction"] == 3
    assert feedback["next_strategy"] == "post_failure_repair"
    assert "preserve accepted variant direction" in feedback["worked_phrases"]
    assert "persona/design drift" in feedback["avoid_phrases"]


def test_records_user_feedback_to_split_file_and_targets_split_attempt(tmp_path):
    from tools.image2_adaptive_mediator import (
        mediate_image2_prompt,
        record_image2_mediator_attempt,
        record_image2_user_feedback,
    )

    memory_dir = tmp_path / "image2_memory"
    config = {"enabled": True, "memory_dir": str(memory_dir), "log_attempts": True}
    mediated = mediate_image2_prompt(
        "cinematic fashion portrait",
        config=config,
    )
    record_image2_mediator_attempt(
        mediated,
        image2_status="success",
        config=config,
    )

    feedback = record_image2_user_feedback("太保守", config=config)

    feedback_path = memory_dir / "user_feedback.jsonl"
    payload = json.loads(feedback_path.read_text(encoding="utf-8").splitlines()[0])
    attempt_payload = json.loads((memory_dir / "attempts.jsonl").read_text(encoding="utf-8"))
    assert feedback["recorded"] is True
    assert payload["record_type"] == "user_feedback"
    assert payload["target_timestamp"] == attempt_payload["timestamp"]
    assert payload["failure_class"] == ["too_tame"]


def test_image2_mediator_memory_tool_reports_and_records_feedback(tmp_path, monkeypatch):
    from tools import image2_adaptive_mediator as mediator
    from tools.registry import registry

    memory_path = tmp_path / "adaptive.jsonl"
    monkeypatch.setattr(
        mediator,
        "read_image2_adaptive_mediator_config",
        lambda: {"enabled": True, "memory_path": str(memory_path), "log_attempts": True},
    )

    mediated = mediator.mediate_image2_prompt(
        "product photo",
        config={"enabled": True, "memory_path": str(memory_path)},
    )
    mediator.record_image2_mediator_attempt(
        mediated,
        image2_status="success",
        config={"enabled": True, "memory_path": str(memory_path)},
    )

    entry = registry.get_entry("image2_mediator_memory")
    assert entry is not None

    feedback_result = json.loads(entry.handler({
        "action": "feedback",
        "feedback": "跑題",
    }))
    report_result = json.loads(entry.handler({
        "action": "report",
        "limit": 5,
    }))

    assert feedback_result["success"] is True
    assert feedback_result["feedback"]["failure_class"] == ["wrong_subject"]
    assert report_result["success"] is True
    assert report_result["summary"]["attempt_count"] == 1
    assert report_result["summary"]["feedback_count"] == 1
    assert report_result["summary"]["learning_summary"]["sample_policy"] == "rules_only"


def test_compact_memory_hints_use_similar_bucket_only(tmp_path):
    from tools.image2_adaptive_mediator import (
        extract_image2_intent,
        mediate_image2_prompt,
    )

    memory_path = tmp_path / "adaptive.jsonl"
    _write_jsonl(memory_path, [
        {
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "attempt",
            "user_concept": "黑色洋桔梗棚拍",
            "intent": extract_image2_intent("手拿黑色洋桔梗，成熟時尚雜誌感").to_dict(),
            "strategy": "hybrid_refine",
            "image2_status": "success",
            "worked_phrases": ["black lisianthus/eustoma with ruffled layered petals"],
            "avoid_phrases": ["black rose"],
            "object_locks_added": ["black lisianthus flowers, also known as eustoma"],
            "failure_class": ["object_drift"],
        },
        {
            "timestamp": "2026-06-15T00:01:00+00:00",
            "record_type": "attempt",
            "user_concept": "旗袍棚拍",
            "intent": extract_image2_intent("穿旗袍，成熟時尚雜誌感").to_dict(),
            "strategy": "hybrid_refine",
            "image2_status": "success",
            "worked_phrases": ["red silk qipao"],
            "avoid_phrases": ["blue jeans"],
            "object_locks_added": ["qipao / cheongsam"],
            "failure_class": [],
        },
    ])
    captured_request = {}

    def draft_fn(prompt: str) -> str:
        captured_request.update(json.loads(prompt))
        return json.dumps({
            "schema_version": "qwen_image_prompt_draft.v1",
            "candidates": [{
                "candidate_id": "q1",
                "positive_prompt": "black lisianthus flowers, also known as eustoma, fashion editorial",
                "style_tags": [],
                "lighting": [],
                "camera": [],
                "invented_elements": [],
                "risky_or_counterproductive_terms": [],
                "constraint_preservation_report": [{
                    "lock_id": "flower_species_001",
                    "expected": "black lisianthus flowers, also known as eustoma",
                    "status": "preserved",
                    "evidence": "uses eustoma",
                }],
            }],
        })

    mediate_image2_prompt(
        "手拿黑色洋桔梗，成熟時尚雜誌感",
        config={"enabled": True, "memory_path": str(memory_path)},
        preprocessor_config={"enabled": True, "model": "test-image-prompt-draft-model"},
        draft_fn=draft_fn,
    )

    hints = captured_request["compact_memory_hints"]
    encoded_hints = json.dumps(hints, ensure_ascii=False)
    assert "black lisianthus/eustoma with ruffled layered petals" in hints["worked_phrases"]
    assert "black rose" in hints["avoid_phrases"]
    assert hints["source_record_count"] == 1
    assert "black lisianthus" in hints["target_bucket"]
    assert "red silk qipao" not in encoded_hints
    assert "blue jeans" not in encoded_hints


def test_learning_summary_uses_phase5_sample_policy_thresholds(tmp_path):
    from tools.image2_adaptive_mediator import summarize_image2_mediator_memory

    expectations = [
        (0, "rules_only"),
        (9, "rules_only"),
        (10, "weak_reference"),
        (30, "moderate_reference"),
        (100, "strong_reference"),
        (300, "bandit_candidate"),
    ]
    for attempt_count, expected_policy in expectations:
        memory_path = tmp_path / f"memory_{attempt_count}.jsonl"
        records = [
            {
                "timestamp": f"2026-06-15T00:{index % 60:02d}:00+00:00",
                "record_type": "attempt",
                "user_concept": f"portrait {index}",
                "strategy": "hybrid_refine",
                "image2_status": "success",
                "failure_class": [],
            }
            for index in range(attempt_count)
        ]
        if records:
            _write_jsonl(memory_path, records)

        summary = summarize_image2_mediator_memory(config={"memory_path": str(memory_path)})

        assert summary["learning_summary"]["sample_policy"] == expected_policy


def test_learning_summary_buckets_strategy_outcomes_and_user_feedback(tmp_path):
    from tools.image2_adaptive_mediator import (
        extract_image2_intent,
        summarize_image2_mediator_memory,
    )

    flower_intent = extract_image2_intent("手拿黑色洋桔梗，成熟時尚雜誌感").to_dict()
    qipao_intent = extract_image2_intent("穿旗袍，成熟時尚雜誌感").to_dict()
    memory_path = tmp_path / "adaptive.jsonl"
    _write_jsonl(memory_path, [
        {
            "timestamp": "2026-06-15T00:00:00+00:00",
            "record_type": "attempt",
            "user_concept": "flower attempt success",
            "intent": flower_intent,
            "strategy": "hybrid_refine",
            "image2_status": "success",
            "failure_class": [],
            "scores": {"user_satisfaction": 4},
        },
        {
            "timestamp": "2026-06-15T00:01:00+00:00",
            "record_type": "attempt",
            "user_concept": "flower attempt blocked",
            "intent": flower_intent,
            "strategy": "safe_reframe",
            "image2_status": "blocked",
            "failure_class": ["blocked"],
            "scores": {"user_satisfaction": None},
        },
        {
            "timestamp": "2026-06-15T00:02:00+00:00",
            "record_type": "user_feedback",
            "user_concept": "flower attempt success",
            "intent": flower_intent,
            "strategy": "hybrid_refine",
            "image2_status": "feedback",
            "feedback_source": "user",
            "failure_class": ["too_tame"],
            "feedback_text": "太保守",
            "scores": {"user_satisfaction": 2},
        },
        {
            "timestamp": "2026-06-15T00:03:00+00:00",
            "record_type": "attempt",
            "user_concept": "qipao attempt",
            "intent": qipao_intent,
            "strategy": "element_lock",
            "image2_status": "success",
            "failure_class": [],
        },
    ])

    summary = summarize_image2_mediator_memory(
        config={"memory_path": str(memory_path)},
        limit=4,
    )

    buckets = summary["learning_summary"]["strategy_buckets"]
    flower_bucket = next(bucket for bucket in buckets if "black lisianthus" in bucket["bucket"])
    assert flower_bucket["attempt_count"] == 2
    assert flower_bucket["status_counts"] == {"blocked": 1, "success": 1}
    assert flower_bucket["failure_class_counts"] == {"blocked": 1}
    assert flower_bucket["user_feedback_failure_counts"] == {"too_tame": 1}
    assert flower_bucket["feedback_weight"] == "user_feedback_strongest_signal"
    assert flower_bucket["sample_policy"] == "rules_only"
    assert flower_bucket["strategies"]["hybrid_refine"]["attempt_count"] == 1
    assert flower_bucket["strategies"]["hybrid_refine"]["success_rate"] == 1.0
    assert flower_bucket["strategies"]["safe_reframe"]["blocked_count"] == 1
