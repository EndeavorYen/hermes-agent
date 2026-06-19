from __future__ import annotations

import importlib.util
import json
import sys
import time
import types
from pathlib import Path


PLUGIN_ROOT = Path("/Users/simon/.hermes/plugins/visual-arsenal")


def _load_runtime_plugin_module(name: str):
    spec = importlib.util.spec_from_file_location(
        f"visual_arsenal_runtime_{name}",
        PLUGIN_ROOT / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_slack_natural_followups_inject_visual_arsenal_context():
    module = _load_runtime_plugin_module("__init__")

    for message in ("再來四張", "同樣風格再做一組", "生成幾張 beach resort 寫真"):
        result = module.visual_arsenal_slack_default_context(
            platform="slack",
            user_message=message,
        )

        assert result is not None
        assert "visual_arsenal_review_inbox" in result["context"]
        assert "visual_arsenal_generate" in result["context"]


def test_slack_video_followups_inject_video_generation_context():
    module = _load_runtime_plugin_module("__init__")

    result = module.visual_arsenal_slack_default_context(
        platform="slack",
        user_message="第一張產出影片",
    )

    assert result is not None
    assert "video_generate" in result["context"]


def test_slack_combined_image_video_requests_prefer_visual_agent_context():
    module = _load_runtime_plugin_module("__init__")

    result = module.visual_arsenal_slack_default_context(
        platform="slack",
        user_message="請幫我產出一張圖片和一段影片：霧黑鋼筆產品攝影",
    )

    assert result is not None
    assert "visual_agent_generate" in result["context"]
    assert "combined visual package" in result["context"]
    assert "image and video" in result["context"]


def test_slack_default_context_stays_quiet_for_unrelated_followup():
    module = _load_runtime_plugin_module("__init__")

    assert module.visual_arsenal_slack_default_context(
        platform="slack",
        user_message="再來整理會議筆記",
    ) is None


def test_visual_arsenal_generate_prefers_image_mission_with_reference_images(monkeypatch):
    tools = _load_runtime_plugin_module("tools")
    calls: dict[str, dict] = {}

    async def fake_mission(payload):
        calls["mission"] = payload
        return json.dumps({
            "success": True,
            "image": "/tmp/mission.png",
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
        })

    def fake_plain(payload):
        calls["plain"] = payload
        return json.dumps({
            "success": True,
            "image": "/tmp/plain.png",
            "provider": "plain",
        })

    monkeypatch.setitem(
        sys.modules,
        "tools.image_mission_tool",
        types.SimpleNamespace(_handle_image_generate_mission=fake_mission),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.image_generation_tool",
        types.SimpleNamespace(_handle_image_generate=fake_plain),
    )

    result = tools._generate_image(
        "battle-worn rogue, walking through fog",
        "portrait",
        reference_images=["/tmp/ref.png"],
    )

    assert result["image"] == "/tmp/mission.png"
    assert calls["mission"]["prompt"] == "battle-worn rogue, walking through fog"
    assert calls["mission"]["aspect_ratio"] == "portrait"
    assert calls["mission"]["reference_images"] == ["/tmp/ref.png"]
    assert calls["mission"]["budget"] == "task"
    assert "plain" not in calls


def test_visual_arsenal_generate_can_use_direct_provider_with_reference_images(monkeypatch):
    tools = _load_runtime_plugin_module("tools")
    calls: dict[str, dict] = {}

    async def fake_mission(payload):
        calls["mission"] = payload
        return json.dumps({
            "success": True,
            "image": "/tmp/mission.png",
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
        })

    def fake_plain(payload):
        calls["plain"] = payload
        return json.dumps({
            "success": True,
            "image": "/tmp/plain.png",
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
        })

    monkeypatch.setitem(
        sys.modules,
        "tools.image_mission_tool",
        types.SimpleNamespace(_handle_image_generate_mission=fake_mission),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.image_generation_tool",
        types.SimpleNamespace(_handle_image_generate=fake_plain),
    )

    result = tools._generate_image(
        "battle-worn rogue, walking through fog",
        "portrait",
        reference_images=["/tmp/ref.png"],
        generation_mode="direct",
    )

    assert result["image"] == "/tmp/plain.png"
    assert calls["plain"]["prompt"] == "battle-worn rogue, walking through fog"
    assert calls["plain"]["aspect_ratio"] == "portrait"
    assert calls["plain"]["reference_images"] == ["/tmp/ref.png"]
    assert "mission" not in calls


def test_visual_arsenal_generate_times_out_without_archiving_partial_output(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"hero")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Locked Hero",
                "role": "card",
                "status": "locked",
                "imagePath": "/assets/hero.png",
                "promptCore": "source-faithful portrait",
                "negativePrompt": "",
                "outputs": [],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    def slow_generate(*_args, **_kwargs):
        time.sleep(0.2)
        return {"success": True, "image": "/tmp/late.png"}

    monkeypatch.setattr(tools, "_generate_image", slow_generate)
    started = time.monotonic()

    result = json.loads(tools.visual_arsenal_generate({
        "reference_ids": ["hero"],
        "title": "timeout batch",
        "generation_timeout_seconds": 0.01,
    }))

    assert time.monotonic() - started < 0.15
    assert result["success"] is False
    assert result["stage"] == "image_generation"
    assert result["error_type"] == "timeout"
    saved = json.loads((root / "library" / "index.json").read_text(encoding="utf-8"))
    assert saved["references"][0]["outputs"] == []
    assert saved["runs"] == []


def test_visual_arsenal_generate_archives_reference_conditioning_metadata(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"hero")
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"generated")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Locked Hero",
                "role": "card",
                "status": "locked",
                "imagePath": "/assets/hero.png",
                "promptCore": "source-faithful portrait",
                "negativePrompt": "identity drift",
                "outputs": [],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")
    calls: dict[str, object] = {}

    def fake_generate(prompt, aspect_ratio, *, reference_images=None, **_kwargs):
        calls["prompt"] = prompt
        calls["aspect_ratio"] = aspect_ratio
        calls["reference_images"] = reference_images
        return {
            "success": True,
            "image": str(generated),
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
            "reference_image_count": 1,
            "reference_conditioning": "responses_input_image",
        }

    monkeypatch.setattr(tools, "_generate_image", fake_generate)

    result = json.loads(tools.visual_arsenal_generate({
        "reference_ids": ["hero"],
        "title": "reference-conditioned smoke",
        "aspect_ratio": "portrait",
    }))

    assert result["success"] is True
    assert calls["aspect_ratio"] == "portrait"
    assert calls["reference_images"] == [str(assets / "hero.png")]
    output_metadata = result["output"]["generationMetadata"]
    assert output_metadata["reference_image_count"] == 1
    assert output_metadata["reference_conditioning"] == "responses_input_image"
    run_metadata = result["run"]["generationMetadata"]
    assert run_metadata == output_metadata


def test_visual_arsenal_generate_injects_diversity_contract_into_provider_prompt(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"hero")
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"generated")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Locked Hero",
                "role": "card",
                "status": "locked",
                "imagePath": "/assets/hero.png",
                "promptCore": "source-faithful portrait",
                "negativePrompt": "identity drift",
                "outputs": [],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")
    calls: dict[str, object] = {}

    def fake_generate(prompt, aspect_ratio, *, reference_images=None, **_kwargs):
        calls["prompt"] = prompt
        calls["aspect_ratio"] = aspect_ratio
        calls["reference_images"] = reference_images
        return {
            "success": True,
            "image": str(generated),
            "provider": "openai-codex",
            "model": "gpt-image-2-high",
            "reference_image_count": 1,
            "reference_conditioning": "responses_input_image",
        }

    monkeypatch.setattr(tools, "_generate_image", fake_generate)

    result = json.loads(tools.visual_arsenal_generate({
        "reference_ids": ["hero"],
        "title": "diverse pose smoke",
        "diversity_contract": {
            "pose": "seated side-angle pose",
            "camera": "low 85mm side angle",
            "crop": "seated full-body crop",
            "body_orientation": "side profile with face turned back toward camera",
            "hands": "one hand on bench, one hand holding robe edge",
            "scene_interaction": "legs angled across frame",
        },
    }))

    assert result["success"] is True
    prompt = str(calls["prompt"])
    assert "Diversity contract" in prompt
    assert "seated side-angle pose" in prompt
    assert "Do not reuse the same front-facing standing robe pose" in prompt
    assert "same pose" in prompt


def test_runtime_visual_arsenal_search_uses_reviewed_output_ranker(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"hero")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [
                {
                    "id": "hero",
                    "title": "Old Hero",
                    "role": "character",
                    "status": "locked",
                    "imagePath": "/assets/hero.png",
                    "tags": ["rogue"],
                    "promptCore": "battle-worn rogue",
                    "negativePrompt": "",
                    "notes": "",
                    "outputs": [
                        {
                            "id": "keeper",
                            "title": "Kept Beach Trial",
                            "status": "kept",
                            "imagePath": "/assets/hero.png",
                            "prompt": "beach resort portrait with elegant adult model",
                            "reviewNotes": "Best beach resort portrait direction so far.",
                            "score": 96,
                            "runId": "run-keeper",
                        }
                    ],
                    "createdAt": "2026-05-31T00:00:00.000Z",
                    "updatedAt": "2026-05-31T00:00:00.000Z",
                },
                {
                    "id": "recent",
                    "title": "Recent Beach Portrait",
                    "role": "character",
                    "status": "locked",
                    "imagePath": "/assets/hero.png",
                    "tags": ["beach", "portrait"],
                    "promptCore": "beach resort portrait with elegant adult model",
                    "negativePrompt": "",
                    "notes": "Unreviewed but newer.",
                    "outputs": [],
                    "createdAt": "2026-06-02T00:00:00.000Z",
                    "updatedAt": "2026-06-02T00:00:00.000Z",
                },
            ],
            "runs": [
                {
                    "id": "run-keeper",
                    "referenceIds": ["hero"],
                    "targetReferenceId": "hero",
                    "outputIds": ["hero::keeper"],
                    "reviewDecision": {
                        "selectedOutputIds": ["hero::keeper"],
                        "summary": "Preserve the beach resort face and styling.",
                        "nextBrief": "Explore a cleaner luxury resort variation.",
                    },
                }
            ],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_search({"query": "beach resort portrait", "limit": 2}))

    assert [ref["id"] for ref in result["references"]] == ["hero", "recent"]
    assert result["references"][0]["learning_signals"]["kept_outputs"] == 1
    assert result["references"][0]["rank_score"] > result["references"][1]["rank_score"]
    assert "Explore a cleaner luxury resort variation." in result["references"][0]["learning_highlights"]


def test_visual_arsenal_batch_eval_plan_uses_locked_high_score_outputs(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"hero")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [
                {
                    "id": "hero",
                    "title": "Wolf beach reference",
                    "role": "card",
                    "status": "locked",
                    "imagePath": "/assets/hero.png",
                    "tags": ["fantasy", "beach"],
                    "promptCore": "photoreal fantasy beach editorial, angular face",
                    "negativePrompt": "round face, generic styling",
                    "notes": "",
                    "outputs": [
                        {
                            "id": "A",
                            "title": "A kept cabana",
                            "status": "kept",
                            "imagePath": "/assets/hero.png",
                            "prompt": "premium cabana editorial, strong face direction",
                            "score": 94,
                            "scoreNotes": "Reviewer: A is strong. Keep this face and styling direction.",
                        },
                        {
                            "id": "C",
                            "title": "C demoted weak face",
                            "status": "rejected",
                            "imagePath": "/assets/hero.png",
                            "prompt": "similar but weak face direction",
                            "score": 40,
                            "scoreNotes": "Reviewer: C face direction failed the beauty target. Avoid this face direction.",
                        },
                    ],
                    "createdAt": "2026-06-01T00:00:00Z",
                    "updatedAt": "2026-06-01T00:00:00Z",
                },
                {
                    "id": "candidate",
                    "title": "Untrusted candidate",
                    "role": "card",
                    "status": "candidate",
                    "imagePath": "/assets/hero.png",
                    "tags": ["generic"],
                    "promptCore": "generic cosplay",
                    "negativePrompt": "",
                    "notes": "",
                    "outputs": [],
                },
            ],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_batch_eval_plan({
        "query": "glamour character editorial",
        "reference_ids": ["hero", "candidate"],
        "variant_count": 3,
        "scene_variations": ["cabana close portrait", "low angle rocks", "black backdrop"],
        "include_paths": True,
    }))

    assert result["success"] is True
    assert result["batch"]["reference_ids"] == ["hero"]
    assert result["batch"]["blocked_reference_ids"] == [{"id": "candidate", "status": "candidate"}]
    assert result["batch"]["positive_examples"][0]["output_id"] == "A"
    assert "failed the beauty target" in result["batch"]["avoid_lessons"][0]["notes"]
    assert [variant["label"] for variant in result["variants"]] == ["G1", "G2", "G3"]
    assert all(variant["reference_images"] == [str(assets / "hero.png")] for variant in result["variants"])
    assert all("generic cosplay" not in variant["prompt"] for variant in result["variants"])
    assert result["batch"]["generation_policy"] == {
        "requires_reference_conditioning": True,
        "prompt_only_formal_candidates": False,
        "reason": "locked Visual Arsenal references with source images require reference_images conditioning",
    }
    assert "Reply with labels" in result["review_card"]


def test_visual_arsenal_batch_eval_plan_adds_diversity_contract_after_pose_collapse(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"hero")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Fantasy beach reference",
                "role": "card",
                "status": "locked",
                "imagePath": "/assets/hero.png",
                "tags": ["fantasy", "beach"],
                "promptCore": "photoreal fantasy beach editorial, angular face",
                "negativePrompt": "round face, generic cosplay",
                "outputs": [
                    {
                        "id": "kept",
                        "title": "Kept face",
                        "status": "kept",
                        "imagePath": "/assets/hero.png",
                        "prompt": "beautiful face and wolf-ear styling",
                        "score": 90,
                    },
                    {
                        "id": "bad-i1",
                        "title": "I1 rejected",
                        "status": "rejected",
                        "imagePath": "/assets/hero.png",
                        "score": 25,
                        "scoreNotes": "同張圖換背景，姿勢沒變，差評",
                        "failureClass": [
                            "low_variation",
                            "background_only_variation",
                            "pose_collapse",
                        ],
                    },
                ],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_batch_eval_plan({
        "reference_ids": ["hero"],
        "variant_count": 4,
        "scene_variations": ["beach", "studio", "resort", "pool"],
        "include_paths": True,
    }))

    assert result["success"] is True
    assert result["batch"]["generation_policy"]["requires_composition_diversity"] is True
    assert "low_variation" in result["batch"]["generation_policy"]["avoid_failure_classes"]
    contracts = [variant["diversity_contract"] for variant in result["variants"]]
    assert [contract["pose"] for contract in contracts] == [
        "three-quarter standing turn",
        "seated side-angle pose",
        "walking candid stride",
        "over-shoulder back turn",
    ]
    assert len({contract["camera"] for contract in contracts}) == 4
    assert len({contract["crop"] for contract in contracts}) == 4
    assert all("Do not reuse the same front-facing standing robe pose" in variant["prompt"] for variant in result["variants"])
    assert all("same pose" in variant["negative_prompt"] for variant in result["variants"])


def test_visual_arsenal_batch_eval_plan_prioritizes_preferred_outputs(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"hero")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Fantasy beach reference",
                "role": "card",
                "status": "locked",
                "imagePath": "/assets/hero.png",
                "tags": ["fantasy"],
                "promptCore": "source fantasy costume",
                "negativePrompt": "",
                "notes": "",
                "outputs": [
                    {
                        "id": "old-a",
                        "title": "Old high score",
                        "status": "kept",
                        "imagePath": "/assets/hero.png",
                        "prompt": "old high score cabana direction",
                        "score": 96,
                        "scoreNotes": "Historically good, but not the latest selected base.",
                    },
                    {
                        "id": "g4",
                        "title": "G4 accepted",
                        "status": "kept",
                        "imagePath": "/assets/hero.png",
                        "prompt": "G4-safe catalog beauty repair",
                        "score": 86,
                        "scoreNotes": "Reviewer: only G4 passed in the latest batch.",
                    },
                ],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_batch_eval_plan({
        "reference_ids": ["hero"],
        "preferred_output_ids": ["g4"],
        "variant_count": 2,
        "scene_variations": ["repair persona drift", "increase beauty"],
    }))

    assert result["batch"]["positive_examples"][0]["output_id"] == "g4"
    assert result["variants"][0]["basis_output_id"] == "g4"
    assert "G4-safe catalog beauty repair" in result["variants"][0]["prompt"]


def test_visual_arsenal_apply_batch_review_updates_outputs_and_run(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    for name in ("g1.png", "g2.png", "g3.png", "g4.png"):
        (assets / name).write_bytes(name.encode())
    outputs = [
        {"id": "g1", "title": "G1", "status": "candidate", "imagePath": "/assets/g1.png"},
        {"id": "g2", "title": "G2", "status": "candidate", "imagePath": "/assets/g2.png"},
        {"id": "g3", "title": "G3", "status": "candidate", "imagePath": "/assets/g3.png"},
        {"id": "g4", "title": "G4", "status": "candidate", "imagePath": "/assets/g4.png"},
    ]
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Wolf beach reference",
                "role": "card",
                "status": "locked",
                "imagePath": "/assets/g1.png",
                "tags": [],
                "promptCore": "wolf-ear beach cosplay",
                "negativePrompt": "",
                "notes": "",
                "outputs": outputs,
            }],
            "runs": [{
                "id": "batch-1",
                "referenceIds": ["hero"],
                "targetReferenceId": "hero",
                "outputIds": ["hero::g1", "hero::g2", "hero::g3", "hero::g4"],
                "status": "completed",
            }],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_apply_batch_review({
        "reference_id": "hero",
        "run_id": "batch-1",
        "label_output_ids": {
            "G1": "g1",
            "G2": "g2",
            "G3": "g3",
            "G4": "g4",
        },
        "review_text": "只有 G4 過關；G1 人設差異太大；G3 人設差異太大；G2 不夠漂亮、不夠性感",
    }))

    assert result["success"] is True
    assert result["updates"]["G4"]["status"] == "kept"
    assert result["updates"]["G4"]["score"] == 86
    assert result["updates"]["G1"]["failure_class"] == ["persona_drift"]
    assert result["updates"]["G1"]["status"] == "rejected"
    assert result["updates"]["G3"]["status"] == "rejected"
    assert result["updates"]["G2"]["failure_class"] == ["not_beautiful_enough", "not_sexy_enough"]
    assert result["updates"]["G2"]["status"] == "retry"

    saved = json.loads((root / "library" / "index.json").read_text(encoding="utf-8"))
    saved_outputs = {item["id"]: item for item in saved["references"][0]["outputs"]}
    assert saved_outputs["g4"]["status"] == "kept"
    assert saved_outputs["g1"]["score"] == 35
    assert saved_outputs["g2"]["score"] == 45
    decision = saved["runs"][0]["reviewDecision"]
    assert decision["selectedOutputIds"] == ["hero::g4"]
    assert decision["retryOutputIds"] == ["hero::g2"]
    assert decision["rejectedOutputIds"] == ["hero::g1", "hero::g3"]


def test_visual_arsenal_apply_batch_review_understands_label_ranges(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    for name in ("h1.png", "h2.png", "h3.png"):
        (assets / name).write_bytes(name.encode())
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Wolf reference",
                "status": "locked",
                "imagePath": "/assets/h1.png",
                "outputs": [
                    {"id": "h1", "title": "H1", "status": "candidate", "imagePath": "/assets/h1.png"},
                    {"id": "h2", "title": "H2", "status": "candidate", "imagePath": "/assets/h2.png"},
                    {"id": "h3", "title": "H3", "status": "candidate", "imagePath": "/assets/h3.png"},
                ],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_apply_batch_review({
        "reference_id": "hero",
        "label_output_ids": {"H1": "h1", "H2": "h2", "H3": "h3"},
        "review_text": "H1-H3 全部退貨；面容完全不符合我的要求；face identity mismatch / persona drift",
    }))

    assert result["success"] is True
    assert all(update["status"] == "rejected" for update in result["updates"].values())
    assert all(update["score"] == 20 for update in result["updates"].values())
    assert all("identity_mismatch" in update["failure_class"] for update in result["updates"].values())
    assert all(
        "missing_reference_conditioning" in update["failure_class"]
        for update in result["updates"].values()
    )


def test_visual_arsenal_apply_batch_review_classifies_background_only_variation(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    for name in ("i1.png", "i2.png", "i5.png", "i6.png"):
        (assets / name).write_bytes(name.encode())
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Wolf reference",
                "status": "locked",
                "imagePath": "/assets/i1.png",
                "outputs": [
                    {"id": "i1", "title": "I1", "status": "candidate", "imagePath": "/assets/i1.png"},
                    {"id": "i2", "title": "I2", "status": "candidate", "imagePath": "/assets/i2.png"},
                    {"id": "i5", "title": "I5", "status": "candidate", "imagePath": "/assets/i5.png"},
                    {"id": "i6", "title": "I6", "status": "candidate", "imagePath": "/assets/i6.png"},
                ],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_apply_batch_review({
        "reference_id": "hero",
        "label_output_ids": {"I1": "i1", "I2": "i2", "I5": "i5", "I6": "i6"},
        "review_text": "I1/I2/I5/I6 都像同張圖換背景，姿勢沒變，差評",
    }))

    assert result["success"] is True
    assert all(update["status"] == "rejected" for update in result["updates"].values())
    assert all(update["score"] == 25 for update in result["updates"].values())
    assert all("low_variation" in update["failure_class"] for update in result["updates"].values())
    assert all("pose_collapse" in update["failure_class"] for update in result["updates"].values())
    assert all("background_only_variation" in update["failure_class"] for update in result["updates"].values())

    saved = json.loads((root / "library" / "index.json").read_text(encoding="utf-8"))
    saved_outputs = {item["id"]: item for item in saved["references"][0]["outputs"]}
    assert saved_outputs["i1"]["failureClass"] == [
        "low_variation",
        "background_only_variation",
        "pose_collapse",
    ]


def test_visual_arsenal_apply_batch_review_classifies_mixed_labeled_feedback(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    for name in ("v1.png", "v2.png"):
        (assets / name).write_bytes(name.encode())
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Third reference",
                "status": "locked",
                "imagePath": "/assets/v1.png",
                "outputs": [
                    {"id": "v1", "title": "V1", "status": "candidate", "imagePath": "/assets/v1.png"},
                    {"id": "v2", "title": "V2", "status": "candidate", "imagePath": "/assets/v2.png"},
                ],
            }],
            "runs": [],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_apply_batch_review({
        "reference_id": "hero",
        "label_output_ids": {"V1": "v1", "V2": "v2"},
        "review_text": "V1 臉還算像，但整體性感程度普通；V2 有腿部線條和裸足，還算加分，可惜臉稍微不自然",
    }))

    assert result["success"] is True
    assert result["updates"]["V1"]["status"] == "retry"
    assert result["updates"]["V1"]["score"] == 58
    assert result["updates"]["V1"]["failure_class"] == ["face_match_positive", "not_sexy_enough"]
    assert result["updates"]["V2"]["status"] == "retry"
    assert result["updates"]["V2"]["score"] == 62
    assert result["updates"]["V2"]["failure_class"] == ["legs_barefoot_positive", "face_uncanny"]

    saved = json.loads((root / "library" / "index.json").read_text(encoding="utf-8"))
    saved_outputs = {item["id"]: item for item in saved["references"][0]["outputs"]}
    assert saved_outputs["v1"]["failureClass"] == ["face_match_positive", "not_sexy_enough"]
    assert saved_outputs["v2"]["failureClass"] == ["legs_barefoot_positive", "face_uncanny"]


def test_visual_arsenal_apply_batch_review_keeps_positive_variant_with_soft_glamour_gap(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "v4.png").write_bytes(b"v4")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Third reference",
                "status": "locked",
                "imagePath": "/assets/v4.png",
                "outputs": [
                    {"id": "v4", "title": "V4", "status": "candidate", "imagePath": "/assets/v4.png"},
                ],
            }],
            "runs": [{
                "id": "v4",
                "referenceIds": ["hero"],
                "targetReferenceId": "hero",
                "outputIds": ["hero::v4"],
                "status": "completed",
            }],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_apply_batch_review({
        "reference_id": "hero",
        "run_id": "v4",
        "label_output_ids": {"V4": "v4"},
        "review_text": "V4 很不錯，姿勢和構圖有變化，也算有點性感(普通)，但有腿部線條和裸足，我給予好評",
    }))

    assert result["success"] is True
    assert result["updates"]["V4"]["status"] == "kept"
    assert result["updates"]["V4"]["score"] == 82
    assert result["updates"]["V4"]["failure_class"] == ["legs_barefoot_positive", "not_sexy_enough"]

    saved = json.loads((root / "library" / "index.json").read_text(encoding="utf-8"))
    saved_output = saved["references"][0]["outputs"][0]
    assert saved_output["status"] == "kept"
    assert saved["runs"][0]["reviewDecision"]["selectedOutputIds"] == ["hero::v4"]


def test_visual_arsenal_apply_batch_review_keeps_variant_but_tracks_reference_silhouette_gap(tmp_path, monkeypatch):
    root = tmp_path
    assets = root / "library" / "assets"
    assets.mkdir(parents=True)
    (assets / "v5.png").write_bytes(b"v5")
    (root / "library" / "index.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "references": [{
                "id": "hero",
                "title": "Third reference",
                "status": "locked",
                "imagePath": "/assets/v5.png",
                "outputs": [
                    {"id": "v5", "title": "V5", "status": "candidate", "imagePath": "/assets/v5.png"},
                ],
            }],
            "runs": [{
                "id": "v5",
                "referenceIds": ["hero"],
                "targetReferenceId": "hero",
                "outputIds": ["hero::v5"],
                "status": "completed",
            }],
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_VISUAL_ARSENAL_ROOT", str(root))
    tools = _load_runtime_plugin_module("tools")

    result = json.loads(tools.visual_arsenal_apply_batch_review({
        "reference_id": "hero",
        "run_id": "v5",
        "label_output_ids": {"V5": "v5"},
        "review_text": "V5 性感升級不夠，頂多和 V4 持平，但有不同姿勢和角度，給過。但遠不如 reference 的 butt silhouette impact",
    }))

    assert result["success"] is True
    assert result["updates"]["V5"]["status"] == "kept"
    assert result["updates"]["V5"]["score"] == 78
    assert result["updates"]["V5"]["failure_class"] == ["not_sexy_enough", "ref_butt_sexiness_gap"]

    saved = json.loads((root / "library" / "index.json").read_text(encoding="utf-8"))
    saved_output = saved["references"][0]["outputs"][0]
    assert saved_output["status"] == "kept"
    assert saved["runs"][0]["reviewDecision"]["selectedOutputIds"] == ["hero::v5"]
