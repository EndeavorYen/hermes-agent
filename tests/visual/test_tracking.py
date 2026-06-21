import json
from pathlib import Path


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_tracking_records_successful_image_attempt(tmp_path, monkeypatch):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import record_visual_generation_attempt

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "generated.png"
    image.write_bytes(_ONE_PIXEL_PNG)

    payload = record_visual_generation_attempt(
        {"success": True, "image": str(image), "provider": "xai", "model": "grok-imagine-image"},
        user_prompt="redacted runtime prompt",
        prompt_original="redacted runtime prompt",
        prompt_mediated="compiled prompt",
        modality="image",
        operation="text_to_image",
        artifact_key="image",
        kind="image",
        provider="xai",
        model="grok-imagine-image",
        parameters_requested={"aspect_ratio": "16:9"},
        parameters_effective={"aspect_ratio": "16:9"},
    )

    assert payload["visual_request_id"].startswith("vrq_")
    assert payload["visual_attempt_id"].startswith("vat_")
    assert payload["visual_artifact_id"].startswith("var_")

    ledger = VisualAttemptLedger(tmp_path / "visual" / "attempt_ledger.sqlite3")
    artifact = ledger.get_artifact(payload["visual_artifact_id"])
    assert artifact["freshness_status"] == "fresh"
    assert artifact["content_hash"].startswith("sha256:")


def test_tracking_records_failed_attempt_without_artifact(tmp_path, monkeypatch):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.tracking import record_visual_generation_attempt

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    payload = record_visual_generation_attempt(
        {
            "success": False,
            "image": None,
            "error": "content moderation",
            "error_type": "provider_rejected",
        },
        user_prompt="redacted runtime prompt",
        prompt_original="redacted runtime prompt",
        prompt_mediated="compiled prompt",
        modality="image",
        operation="text_to_image",
        artifact_key="image",
        kind="image",
        provider="xai",
        model="grok-imagine-image",
    )

    assert payload["visual_request_id"].startswith("vrq_")
    assert payload["visual_attempt_id"].startswith("vat_")
    assert "visual_artifact_id" not in payload

    ledger = VisualAttemptLedger(tmp_path / "visual" / "attempt_ledger.sqlite3")
    attempt = ledger.get_attempt(payload["visual_attempt_id"])
    assert attempt["status"] == "failed"
    assert attempt["error_type"] == "provider_rejected"


def test_tracking_is_best_effort_when_ledger_fails(tmp_path, monkeypatch):
    from agent.visual import tracking

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        tracking.VisualAttemptLedger,
        "initialize",
        lambda self: (_ for _ in ()).throw(RuntimeError("ledger unavailable")),
    )
    payload = {"success": False, "error": "boom", "error_type": "provider_exception"}

    result = tracking.record_visual_generation_attempt(
        payload,
        user_prompt="redacted runtime prompt",
        prompt_original="redacted runtime prompt",
        prompt_mediated="compiled prompt",
        modality="image",
        operation="text_to_image",
        artifact_key="image",
        kind="image",
        provider="xai",
        model="grok-imagine-image",
    )

    assert result is payload
    assert "visual_request_id" not in result


def test_image_tool_dispatch_records_visual_attempt(tmp_path, monkeypatch):
    import tools.image_generation_tool as image_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    image = tmp_path / "generated.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        image_tool,
        "_dispatch_to_plugin_provider",
        lambda *args, **kwargs: json.dumps(
            {
                "success": True,
                "image": str(image),
                "provider": "xai",
                "model": "grok-imagine-image",
            }
        ),
    )

    raw = image_tool._handle_image_generate({"prompt": "redacted prompt", "aspect_ratio": "16:9"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["image"] == str(image)
    assert payload["visual_artifact_id"].startswith("var_")


def test_image_tool_tracking_failure_does_not_break_generation(tmp_path, monkeypatch):
    import tools.image_generation_tool as image_tool

    image = tmp_path / "generated.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setattr(
        image_tool,
        "_dispatch_to_plugin_provider",
        lambda *args, **kwargs: json.dumps({"success": True, "image": str(image)}),
    )
    monkeypatch.setattr(image_tool, "_read_configured_image_model", lambda: None)
    monkeypatch.setattr(
        image_tool,
        "_resolve_fal_model",
        lambda: (_ for _ in ()).throw(RuntimeError("config unavailable")),
    )

    raw = image_tool._handle_image_generate({"prompt": "redacted prompt", "aspect_ratio": "16:9"})
    payload = json.loads(raw)

    assert payload == {"success": True, "image": str(image)}


def test_video_tool_dispatch_records_visual_attempt(tmp_path, monkeypatch):
    import tools.video_generation_tool as video_tool

    class FakeVideoProvider:
        name = "xai"
        display_name = "xAI"

        def default_model(self):
            return "grok-imagine-video"

        def generate(self, prompt, **kwargs):
            return {
                "success": True,
                "video": str(video),
                "provider": self.name,
                "model": kwargs["model"],
                "prompt": prompt,
                "modality": "text",
            }

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    video = tmp_path / "generated.mp4"
    video.write_bytes(b"fake mp4 bytes")
    monkeypatch.setattr(video_tool, "_read_configured_video_provider", lambda: "xai")
    monkeypatch.setattr(video_tool, "_resolve_active_provider", lambda: FakeVideoProvider())

    raw = video_tool._handle_video_generate({"prompt": "redacted prompt"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["video"] == str(video)
    assert payload["visual_artifact_id"].startswith("var_")
    assert Path(tmp_path / "visual" / "attempt_ledger.sqlite3").exists()
