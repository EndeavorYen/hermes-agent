from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


def _snapshot(
    *,
    url: str = "https://grok.com/",
    title: str = "Grok",
    text: str = "",
    buttons: list[dict[str, str | None]] | None = None,
    inputs: list[dict[str, str | None]] | None = None,
) -> dict:
    return {
        "url": url,
        "title": title,
        "text": text,
        "buttons": buttons or [],
        "inputs": inputs or [],
    }


def _durable_artifact(path: Path, source: str = "browser"):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact

    return BrowserArtifact(
        path=path,
        source=source,
        page_url="https://grok.com/imagine/post/test-post",
        page_title="Imagine - Grok",
        durability="durable_history_or_post",
        history_verified=True,
    )


def test_classify_login_page_requires_human_login():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://accounts.x.ai/sign-in?redirect=grok-com",
            title="登录您的 Grok 账户 | Grok",
            text="登录您的账户\n使用 𝕏 登录\n使用邮箱登录",
            buttons=[{"text": "使用 Google 登录", "aria": None}],
        )
    )

    assert state.status == "login_required"
    assert state.safe_to_submit is False
    assert "manual login" in state.message


def test_classify_cloudflare_page_does_not_bypass_challenge():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/",
            title="Just a moment...",
            text="Cloudflare\nVerify you are human",
        )
    )

    assert state.status == "cloudflare_required"
    assert state.safe_to_submit is False
    assert "manual verification" in state.message


def test_classify_logged_out_landing_page_as_login_required():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/",
            title="Grok",
            text="Imagine\n登入\n註冊\n問 Grok 任何事",
            buttons=[{"text": "Imagine", "aria": None}, {"text": "登入", "aria": None}],
            inputs=[{"tag": "TEXTAREA", "aria": "問 Grok 任何事", "placeholder": "你想知道什麼？"}],
        )
    )

    assert state.status == "login_required"
    assert state.safe_to_submit is False


def test_classify_imagine_ready_when_logged_in_prompt_input_visible():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/imagine",
            title="Grok",
            text="Imagine\nCreate images and videos",
            buttons=[{"text": "Imagine", "aria": None}],
            inputs=[
                {
                    "tag": "TEXTAREA",
                    "aria": "Ask Grok anything",
                    "placeholder": "What do you want to make?",
                }
            ],
        )
    )

    assert state.status == "imagine_ready"
    assert state.safe_to_submit is True


def test_classify_imagine_upgrade_prompt_requires_supergrok_session():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/imagine",
            title="Imagine - Grok",
            text="Imagine\n升級至 SuperGrok\nUpgrade to continue creating images",
            inputs=[],
        )
    )

    assert state.status == "subscription_required"
    assert state.safe_to_submit is False
    assert "SuperGrok" in state.message


def test_classify_imagine_ready_when_upgrade_cta_is_visible_but_prompt_controls_work():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/imagine",
            title="Imagine - Grok",
            text=(
                "精選範本\nProduct Showcase\nGlossy Product Shot\n"
                "圖片\n影片\n代理\n語速\n品質\n2:3\n升級至 SuperGrok"
            ),
            buttons=[{"text": "Imagine", "aria": None}, {"text": "Glossy Product Shot", "aria": None}],
            inputs=[
                {
                    "tag": "DIV",
                    "aria": "Ask Grok anything",
                    "placeholder": None,
                    "text": "",
                }
            ],
        )
    )

    assert state.status == "imagine_ready"
    assert state.safe_to_submit is True


def test_classify_imagine_results_gallery_is_not_safe_to_submit_another_prompt():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/imagine",
            title="Tiny red cube on a white table - Grok",
            text=(
                "搜尋\n新一代\n返回 Grok 聊天\n歷史紀錄\n探索\n"
                "Tiny red cube on a white table, clean product photo, no text.\n"
                "提升品質\n圖片\n影片\n代理\n語速\n品質\n2:3\n升級至 SuperGrok"
            ),
            inputs=[
                {
                    "tag": "DIV",
                    "aria": "輸入以想像",
                    "placeholder": None,
                    "text": "Tiny red cube on a white table, clean product photo, no text.",
                }
            ],
        )
    )

    assert state.status == "imagine_results_open"
    assert state.safe_to_submit is False
    assert "results gallery" in state.message


def test_classify_imagine_post_page_as_result_page_not_create_composer():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
            title="Imagine - Grok",
            text="Imagine - Grok\nCreate a simple clean vertical test image\n編輯",
            inputs=[
                {
                    "tag": "DIV",
                    "aria": "Ask Grok anything",
                    "placeholder": None,
                    "text": "",
                }
            ],
        )
    )

    assert state.status == "imagine_post_open"
    assert state.safe_to_submit is False


def test_provider_reports_subscription_required_without_submitting(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine",
        title="Imagine - Grok",
        text="Imagine\n升級至 SuperGrok\nUpgrade to continue creating images",
        inputs=[],
    )
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("clean product photo")

    assert result["success"] is False
    assert result["error_type"] == "subscription_required"
    assert "SuperGrok" in result["error"]
    assert not cdp.generate_image.called


def test_classify_grok_build_page_is_not_safe_for_image_generation():
    from plugins.image_gen.grok_web_imagine import classify_visible_state

    state = classify_visible_state(
        _snapshot(
            url="https://grok.com/build",
            title="Grok",
            text=(
                "Grok Build\n測試版\n從您的終端機執行的新型編碼代理。\n"
                "Imagine\n為您的網站和應用程式產生或編輯影像和影片。\n"
                "計劃模式\n子代理"
            ),
            buttons=[{"text": "Imagine", "aria": None}],
            inputs=[
                {
                    "tag": "TEXTAREA",
                    "aria": "Ask Grok anything",
                    "placeholder": "What do you want to build?",
                }
            ],
        )
    )

    assert state.status == "grok_build_open"
    assert state.safe_to_submit is False
    assert "Imagine" in state.message


def test_provider_reports_grok_build_mode_without_submitting(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/build",
        title="Grok",
        text="Grok Build\nImagine\n計劃模式\n子代理",
        inputs=[{"tag": "TEXTAREA", "aria": "Ask Grok anything", "placeholder": "What do you want to build?"}],
    )
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("clean product photo")

    assert result["success"] is False
    assert result["error_type"] == "grok_build_open"
    assert not cdp.generate_image.called


def test_default_target_patterns_include_grok_and_accounts_pages():
    from plugins.image_gen.grok_web_imagine import DEFAULT_URL_CONTAINS, target_url_matches

    assert target_url_matches("https://grok.com/imagine", DEFAULT_URL_CONTAINS)
    assert target_url_matches("https://accounts.x.ai/sign-in", DEFAULT_URL_CONTAINS)
    assert not target_url_matches("https://example.com", DEFAULT_URL_CONTAINS)


def test_media_item_usability_rejects_low_resolution_placeholder():
    from plugins.image_gen.grok_web_imagine import media_item_is_usable_image

    assert media_item_is_usable_image(
        {
            "tag": "IMG",
            "src": "data:image/png;base64,abc",
            "visible": True,
            "naturalWidth": 171,
            "naturalHeight": 256,
        }
    ) is False


def test_media_item_usability_accepts_generated_image_thumbnail():
    from plugins.image_gen.grok_web_imagine import media_item_is_usable_image

    assert media_item_is_usable_image(
        {
            "tag": "IMG",
            "src": "https://imagine-public.x.ai/example_thumbnail.jpg",
            "visible": True,
            "naturalWidth": 464,
            "naturalHeight": 688,
        }
    ) is True


def test_provider_disabled_by_default_even_if_registered(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.delenv("HERMES_GROK_WEB_IMAGINE", raising=False)
    provider = GrokWebImagineProvider(cdp_client=MagicMock())

    assert provider.name == "grok-web-imagine"
    assert provider.is_available() is False
    result = provider.generate("clean product photo")

    assert result["success"] is False
    assert result["error_type"] == "disabled_by_default"
    assert result["provider"] == "grok-web-imagine"


def test_provider_capabilities_advertise_browser_reference_upload():
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    caps = GrokWebImagineProvider(cdp_client=MagicMock()).capabilities()

    assert caps["modalities"] == ["text", "image", "image_edit"]
    assert caps["operations"] == ["generate", "edit_current", "continue_current", "regenerate_current"]
    assert caps["max_reference_images"] >= 1


def test_provider_preflight_reports_browser_state_without_submitting(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine",
        title="Imagine - Grok",
        text="Imagine\nCreate images and videos",
        inputs=[{"tag": "TEXTAREA", "aria": "Ask Grok anything", "placeholder": "What do you want to make?"}],
    )
    provider = GrokWebImagineProvider(cdp_client=cdp)

    report = provider.preflight()

    assert report == {
        "status": "imagine_ready",
        "safe_to_submit": True,
        "ready": True,
        "message": "Grok web Imagine appears ready for a user-authorized generation attempt.",
        "url": "https://grok.com/imagine",
        "title": "Imagine - Grok",
        "quota_used": False,
        "generation_called": False,
    }
    cdp.snapshot.assert_called_once()
    assert not cdp.generate_image.called


def test_provider_preflight_prompt_probe_fills_composer_without_submitting(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine",
        title="Imagine - Grok",
        text="Imagine\nCreate images and videos",
        inputs=[{"tag": "TEXTAREA", "aria": "Ask Grok anything", "placeholder": "What do you want to make?"}],
    )
    cdp.fill_prompt.return_value = {
        "filled": True,
        "submitReady": True,
        "submitDisabled": False,
        "filledText": "Hermes Raphael preflight browser readiness probe.",
        "tag": "TEXTAREA",
    }
    provider = GrokWebImagineProvider(cdp_client=cdp)

    report = provider.preflight(
        probe_prompt="Hermes Raphael preflight browser readiness probe."
    )

    assert report["status"] == "imagine_ready"
    assert report["ready"] is True
    assert report["safe_to_submit"] is True
    assert report["quota_used"] is False
    assert report["generation_called"] is False
    assert report["prompt_probe"] == {
        "attempted": True,
        "prompt_text_present": True,
        "submit_enabled": True,
        "reason": "",
        "tag": "TEXTAREA",
        "filled_text_preview": "Hermes Raphael preflight browser readiness probe.",
    }
    cdp.fill_prompt.assert_called_once_with(
        "Hermes Raphael preflight browser readiness probe."
    )
    assert not cdp.generate_image.called
    assert not cdp.submit_prompt.called


def test_provider_preflight_classifies_login_setup_without_submitting(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://accounts.x.ai/sign-in?redirect=grok-com",
        title="登录您的 Grok 账户 | Grok",
        text="登录您的账户\n使用 Google 登录",
    )
    provider = GrokWebImagineProvider(cdp_client=cdp)

    report = provider.preflight()

    assert report["status"] == "login_required"
    assert report["ready"] is False
    assert report["safe_to_submit"] is False
    assert "manual login" in report["message"]
    assert report["quota_used"] is False
    assert report["generation_called"] is False
    cdp.snapshot.assert_called_once()
    assert not cdp.generate_image.called


def test_provider_rejects_remote_reference_images_until_download_pipeline_exists(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    provider = GrokWebImagineProvider(cdp_client=MagicMock())

    result = provider.generate(
        "keep this character",
        reference_image_urls=["https://example.com/ref.png"],
    )

    assert result["success"] is False
    assert result["error_type"] == "unsupported_reference_source"
    assert "browser bridge" in result["error"]
    assert "local file" in result["error"]


def test_provider_passes_local_reference_images_to_browser_runner(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    source_path = tmp_path / "source.png"
    ref_path = tmp_path / "pose.png"
    output_path = tmp_path / "grok-web-ref.png"
    source_path.write_bytes(b"source image")
    ref_path.write_bytes(b"pose image")
    output_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine",
        title="Grok",
        text="Imagine\nCreate images and videos",
        inputs=[{"tag": "TEXTAREA", "aria": "Ask Grok anything", "placeholder": "What do you want to make?"}],
    )
    cdp.generate_image.return_value = _durable_artifact(output_path, source="browser")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate(
        "use source character and pose reference",
        aspect_ratio="portrait",
        image_url=str(source_path),
        reference_image_urls=[str(ref_path)],
    )

    assert result["success"] is True
    assert result["image"] == str(output_path)
    assert result["modality"] == "image"
    assert result["reference_image_count"] == 2
    cdp.generate_image.assert_called_once_with(
        prompt="use source character and pose reference",
        aspect_ratio="portrait",
        timeout_seconds=240,
        image_paths=[str(source_path.resolve()), str(ref_path.resolve())],
    )


def test_provider_reports_login_required_without_submitting(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://accounts.x.ai/sign-in?redirect=grok-com",
        title="登录您的 Grok 账户 | Grok",
        text="登录您的账户\n使用 Google 登录",
    )
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("clean product photo")

    assert result["success"] is False
    assert result["error_type"] == "login_required"
    assert "debug Chrome" in result["error"]
    cdp.snapshot.assert_called_once()
    assert not cdp.method_calls[1:]


def test_provider_returns_saved_artifact_from_browser_runner(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    image_path = tmp_path / "grok-web.png"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine",
        title="Grok",
        text="Imagine\nCreate images and videos",
        inputs=[{"tag": "TEXTAREA", "aria": "Ask Grok anything", "placeholder": "What do you want to make?"}],
    )
    cdp.generate_image.return_value = _durable_artifact(image_path, source="browser")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("clean product photo", aspect_ratio="square")

    assert result["success"] is True
    assert result["image"] == str(image_path)
    assert result["provider"] == "grok-web-imagine"
    assert result["model"] == "grok-web-imagine"
    assert result["aspect_ratio"] == "square"
    assert result["quota_source"] == "consumer_web"
    cdp.generate_image.assert_called_once_with(
        prompt="clean product photo",
        aspect_ratio="square",
        timeout_seconds=240,
    )


def test_provider_rejects_unverified_ephemeral_artifact_as_non_deliverable(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    image_path = tmp_path / "grok-web-explore.jpg"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine",
        title="Grok",
        text="Imagine\nCreate images and videos",
        inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
    )
    cdp.generate_image.return_value = BrowserArtifact(
        path=image_path,
        source="browser_data_url",
        page_url="https://grok.com/imagine",
        page_title="Transient browser result - Grok",
        durability="ephemeral_browser_page",
        history_verified=False,
    )
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("clean product photo", aspect_ratio="square")

    assert result["success"] is False
    assert result["image"] is None
    assert result["error_type"] == "durable_history_not_verified"
    assert result["artifact_path"] == str(image_path)
    assert result["artifact_source"] == "browser_data_url"
    assert result["artifact_durability"] == "ephemeral_browser_page"
    assert result["history_verified"] is False
    assert result["page_url"] == "https://grok.com/imagine"
    assert result["page_title"] == "Transient browser result - Grok"


def test_provider_accepts_imagine_results_gallery_artifact(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    image_path = tmp_path / "grok-web-gallery.jpg"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine",
        title="Imagine - Grok",
        text="Imagine\nCreate images and videos",
        inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
    )
    cdp.generate_image.return_value = BrowserArtifact(
        path=image_path,
        source="browser_data_url",
        page_url="https://grok.com/imagine",
        page_title="CREATE A CUTE GIRL STYLE - Grok",
        durability="imagine_results_gallery",
        history_verified=True,
    )
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("CREATE A CUTE GIRL STYLE", aspect_ratio="square")

    assert result["success"] is True
    assert result["image"] == str(image_path)
    assert result["artifact_durability"] == "imagine_results_gallery"
    assert result["history_verified"] is True
    assert result["page_url"] == "https://grok.com/imagine"


def test_provider_navigates_from_imagine_post_page_before_generation(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    image_path = tmp_path / "grok-web.png"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.side_effect = [
        _snapshot(
            url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
            title="Imagine - Grok",
            text="Imagine - Grok\n編輯",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
        _snapshot(
            url="https://grok.com/imagine",
            title="Grok",
            text="Imagine\nCreate images and videos",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    ]
    cdp.generate_image.return_value = _durable_artifact(image_path, source="browser")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("clean product photo", aspect_ratio="square")

    assert result["success"] is True
    cdp.navigate.assert_called_once_with("https://grok.com/imagine")
    cdp.generate_image.assert_called_once()


def test_provider_switches_from_explore_results_to_new_generation_composer(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda _seconds: None)
    image_path = tmp_path / "grok-web.png"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.side_effect = [
        _snapshot(
            url="https://grok.com/imagine",
            title="Tiny red cube on a white table - Grok",
            text="搜尋\n新一代\n返回 Grok 聊天\n歷史紀錄\n探索\nTiny red cube\n圖片\n影片",
            inputs=[{"tag": "DIV", "aria": "輸入以想像", "placeholder": None, "text": "Tiny red cube"}],
        ),
        _snapshot(
            url="https://grok.com/imagine",
            title="Imagine - Grok",
            text="Imagine\nCreate images and videos",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None, "text": ""}],
        ),
    ]
    cdp.generate_image.return_value = _durable_artifact(image_path, source="browser_screenshot")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate("clean product photo", aspect_ratio="square")

    assert result["success"] is True
    cdp.open_new_generation_composer.assert_called_once()
    cdp.navigate.assert_not_called()
    cdp.generate_image.assert_called_once()


def test_provider_edits_current_post_without_navigating_to_new_composer(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    image_path = tmp_path / "grok-web-edit.png"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
        title="Imagine - Grok",
        text="Imagine - Grok\n編輯\n重新產生",
        inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
    )
    cdp.edit_current_image.return_value = _durable_artifact(image_path, source="browser_screenshot")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate(
        "make the lighting warmer and keep the same pen",
        aspect_ratio="square",
        operation="edit_current",
    )

    assert result["success"] is True
    assert result["image"] == str(image_path)
    assert result["operation"] == "edit_current"
    assert result["modality"] == "image_edit"
    assert result["reference_image_count"] == 0
    cdp.navigate.assert_not_called()
    cdp.generate_image.assert_not_called()
    cdp.edit_current_image.assert_called_once_with(
        prompt="make the lighting warmer and keep the same pen",
        aspect_ratio="square",
        timeout_seconds=240,
    )


def test_provider_continue_current_edits_open_post_without_new_session(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    image_path = tmp_path / "grok-web-continue.png"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
        title="Imagine - Grok",
        text="Imagine - Grok\n編輯\n重新產生",
        inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
    )
    cdp.edit_current_image.return_value = _durable_artifact(image_path, source="browser_screenshot")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate(
        "try a different composition while keeping this character",
        aspect_ratio="portrait",
        operation="continue_current",
    )

    assert result["success"] is True
    assert result["operation"] == "continue_current"
    assert result["modality"] == "image_edit"
    cdp.navigate.assert_not_called()
    cdp.open_new_generation_composer.assert_not_called()
    cdp.generate_image.assert_not_called()
    cdp.edit_current_image.assert_called_once_with(
        prompt="try a different composition while keeping this character",
        aspect_ratio="portrait",
        timeout_seconds=240,
    )


def test_provider_continue_current_opens_visible_result_from_gallery_without_new_session(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda _seconds: None)
    image_path = tmp_path / "grok-web-continue-gallery.png"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.side_effect = [
        _snapshot(
            url="https://grok.com/imagine",
            title="Tiny red cube on a white table - Grok",
            text="搜尋\n新一代\n返回 Grok 聊天\n歷史紀錄\n探索\nTiny red cube\n圖片\n影片",
            inputs=[{"tag": "DIV", "aria": "輸入以想像", "placeholder": None, "text": "Tiny red cube"}],
        ),
        _snapshot(
            url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
            title="Imagine - Grok",
            text="Imagine - Grok\n編輯\n重新產生",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    ]
    cdp.edit_current_image.return_value = _durable_artifact(image_path, source="browser_screenshot")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate(
        "try a different composition while keeping this character",
        aspect_ratio="portrait",
        operation="continue_current",
    )

    assert result["success"] is True
    assert result["operation"] == "continue_current"
    cdp.open_current_result_from_gallery.assert_called_once()
    cdp.open_new_generation_composer.assert_not_called()
    cdp.generate_image.assert_not_called()
    cdp.edit_current_image.assert_called_once()


def test_provider_regenerates_current_post_without_new_session(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    ref_path = tmp_path / "ignored-ref.png"
    image_path = tmp_path / "grok-web-regenerate.png"
    ref_path.write_bytes(b"reference")
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
        title="Imagine - Grok",
        text="Imagine - Grok\n編輯\n重新產生",
        inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
    )
    cdp.regenerate_current_image.return_value = _durable_artifact(image_path, source="browser_screenshot")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate(
        "重新產生",
        aspect_ratio="portrait",
        operation="regenerate_current",
        reference_image_urls=[str(ref_path)],
    )

    assert result["success"] is True
    assert result["operation"] == "regenerate_current"
    assert result["modality"] == "image"
    assert result["reference_image_count"] == 0
    cdp.navigate.assert_not_called()
    cdp.open_new_generation_composer.assert_not_called()
    cdp.generate_image.assert_not_called()
    cdp.edit_current_image.assert_not_called()
    cdp.regenerate_current_image.assert_called_once_with(timeout_seconds=240)


def test_provider_regenerate_current_opens_visible_result_from_gallery_without_new_session(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda _seconds: None)
    image_path = tmp_path / "grok-web-regenerate-gallery.png"
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.side_effect = [
        _snapshot(
            url="https://grok.com/imagine",
            title="Tiny red cube on a white table - Grok",
            text="搜尋\n新一代\n返回 Grok 聊天\n歷史紀錄\n探索\nTiny red cube\n圖片\n影片",
            inputs=[{"tag": "DIV", "aria": "輸入以想像", "placeholder": None, "text": "Tiny red cube"}],
        ),
        _snapshot(
            url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
            title="Imagine - Grok",
            text="Imagine - Grok\n編輯\n重新產生",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    ]
    cdp.regenerate_current_image.return_value = _durable_artifact(image_path, source="browser_screenshot")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate(
        "重新產生",
        aspect_ratio="portrait",
        operation="regenerate_current",
    )

    assert result["success"] is True
    assert result["operation"] == "regenerate_current"
    cdp.open_current_result_from_gallery.assert_called_once()
    cdp.open_new_generation_composer.assert_not_called()
    cdp.generate_image.assert_not_called()
    cdp.regenerate_current_image.assert_called_once()


def test_provider_edit_current_can_upload_additional_references(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    ref_path = tmp_path / "style-ref.png"
    image_path = tmp_path / "grok-web-edit-ref.png"
    ref_path.write_bytes(b"reference image")
    image_path.write_bytes(b"fake image")
    cdp = MagicMock()
    cdp.snapshot.return_value = _snapshot(
        url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
        title="Imagine - Grok",
        text="Imagine - Grok\n編輯\n重新產生",
        inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
    )
    cdp.edit_current_image.return_value = _durable_artifact(image_path, source="browser_screenshot")
    provider = GrokWebImagineProvider(cdp_client=cdp)

    result = provider.generate(
        "apply the uploaded material reference",
        aspect_ratio="square",
        reference_image_urls=[str(ref_path)],
        operation="edit_current",
    )

    assert result["success"] is True
    assert result["reference_image_count"] == 1
    cdp.edit_current_image.assert_called_once_with(
        prompt="apply the uploaded material reference",
        aspect_ratio="square",
        timeout_seconds=240,
        image_paths=[str(ref_path.resolve())],
    )


def test_submit_prompt_uses_visible_submit_button(monkeypatch):
    from plugins.image_gen.grok_web_imagine import CDPClient

    client = CDPClient()
    calls = []

    def fake_evaluate(expression: str):
        calls.append(expression)
        return {"submitted": True, "method": "submit_button", "label": "送出", "centerX": 1085, "centerY": 811}

    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    mouse_events = []
    monkeypatch.setattr(client, "_send", lambda method, params=None: mouse_events.append((method, params or {})) or {"result": {}})

    client.submit_prompt()

    assert calls
    assert "button[type=submit]" in calls[0]
    assert "編輯" in calls[0]
    assert mouse_events == [
        ("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 1085, "y": 811}),
        ("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 1085, "y": 811, "button": "left", "clickCount": 1}),
        ("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 1085, "y": 811, "button": "left", "clickCount": 1}),
    ]


def test_attach_images_sets_browser_file_input_files(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import CDPClient

    image_path = tmp_path / "reference.png"
    image_path.write_bytes(b"fake image")
    client = CDPClient()
    calls = []
    fake_ws = MagicMock()

    def fake_send_on_ws(ws, method: str, params: dict | None = None):
        assert ws is fake_ws
        calls.append((method, params or {}))
        if method == "Runtime.evaluate":
            return {"result": {"result": {"value": {"clicked": True}}}}
        if method == "DOM.getDocument":
            return {"result": {"root": {"nodeId": 1}}}
        if method == "DOM.querySelectorAll":
            return {"result": {"nodeIds": [42]}}
        if method == "DOM.setFileInputFiles":
            return {"result": {}}
        raise AssertionError(f"unexpected CDP method: {method}")

    monkeypatch.setattr(client, "_connect", lambda: fake_ws)
    monkeypatch.setattr(client, "_send_on_ws", fake_send_on_ws)

    uploaded = client.attach_images([str(image_path)])

    assert uploaded == [str(image_path.resolve())]
    assert (
        "DOM.setFileInputFiles",
        {"nodeId": 42, "files": [str(image_path.resolve())]},
    ) in calls


def test_attach_images_keeps_dom_upload_calls_on_one_cdp_session(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from plugins.image_gen.grok_web_imagine import CDPClient

    image_path = tmp_path / "reference.png"
    image_path.write_bytes(b"fake image")
    client = CDPClient()
    connections = []

    class FakeWebSocket:
        def __init__(self):
            self.session_id = len(connections) + 1
            self.methods = []
            self.response = {}

        def send(self, raw: str):
            request = json.loads(raw)
            method = request["method"]
            params = request.get("params") or {}
            self.methods.append(method)
            request_id = request["id"]
            root_id = self.session_id * 100 + 1
            input_id = self.session_id * 100 + 42
            if method == "Runtime.evaluate":
                self.response = {"id": request_id, "result": {"result": {"value": {"ok": True}}}}
            elif method == "DOM.getDocument":
                self.response = {"id": request_id, "result": {"root": {"nodeId": root_id}}}
            elif method == "DOM.querySelectorAll":
                if params.get("nodeId") != root_id:
                    self.response = {"id": request_id, "error": {"message": "Could not find node with given id"}}
                else:
                    self.response = {"id": request_id, "result": {"nodeIds": [input_id]}}
            elif method == "DOM.setFileInputFiles":
                if params.get("nodeId") != input_id:
                    self.response = {"id": request_id, "error": {"message": "Could not find node with given id"}}
                else:
                    self.response = {"id": request_id, "result": {}}
            else:
                self.response = {"id": request_id, "error": {"message": f"unexpected method {method}"}}

        def recv(self) -> str:
            return json.dumps(self.response)

        def close(self):
            pass

    def fake_create_connection(*args, **kwargs):
        ws = FakeWebSocket()
        connections.append(ws)
        return ws

    monkeypatch.setattr(client, "_page_ws_url", lambda: "ws://test")
    monkeypatch.setattr(
        "plugins.image_gen.grok_web_imagine.websocket",
        SimpleNamespace(create_connection=fake_create_connection),
    )

    uploaded = client.attach_images([str(image_path)])

    assert uploaded == [str(image_path.resolve())]
    dom_sessions = [
        ws.session_id
        for ws in connections
        if any(method.startswith("DOM.") for method in ws.methods)
    ]
    assert len(set(dom_sessions)) == 1


def test_cdp_connection_timeout_covers_screenshot_fallback_settle(monkeypatch):
    from types import SimpleNamespace

    from plugins.image_gen.grok_web_imagine import CDPClient, SCREENSHOT_FALLBACK_SETTLE_MS

    client = CDPClient()
    captured = []

    class FakeWebSocket:
        def close(self):
            pass

    def fake_create_connection(*args, **kwargs):
        captured.append(kwargs)
        return FakeWebSocket()

    monkeypatch.setattr(client, "_page_ws_url", lambda: "ws://test")
    monkeypatch.setattr(
        "plugins.image_gen.grok_web_imagine.websocket",
        SimpleNamespace(create_connection=fake_create_connection),
    )

    client._connect().close()

    assert captured
    assert captured[0]["timeout"] > (SCREENSHOT_FALLBACK_SETTLE_MS / 1000)


def test_edit_current_image_clicks_post_edit_action_and_waits_for_new_artifact(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, CDPClient

    client = CDPClient()
    current_image = {
        "tag": "IMG",
        "src": "https://assets.grok.com/generated/current/image.jpg?cache=1",
        "visible": True,
        "naturalWidth": 1024,
        "naturalHeight": 1024,
    }
    edited_image = {
        "tag": "IMG",
        "src": "https://assets.grok.com/generated/edited/image.jpg?cache=1",
        "visible": True,
        "naturalWidth": 1024,
        "naturalHeight": 1024,
    }
    media_snapshots = iter([
        [current_image],
        [current_image, edited_image],
    ])
    times = iter([0, 0.1, 0.2, 0.3])
    evaluate_calls = []
    saved_sources = []
    output_path = tmp_path / "edited.png"

    monkeypatch.setattr(client, "media", lambda: next(media_snapshots))
    monkeypatch.setattr(
        client,
        "snapshot",
        lambda: _snapshot(
            url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
            title="Imagine - Grok",
            text="Imagine - Grok\n編輯\n重新產生",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    )

    def fake_evaluate(expression: str):
        evaluate_calls.append(expression)
        if "clickGrokCurrentPostEditAction" in expression:
            return {"clicked": True, "label": "編輯"}
        return {"ok": True}

    def fake_save(src: str) -> BrowserArtifact:
        saved_sources.append(src)
        return BrowserArtifact(path=output_path, source="browser_screenshot")

    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    monkeypatch.setattr(client, "fill_prompt", lambda prompt: {"filled": True})
    monkeypatch.setattr(client, "submit_prompt", lambda: None)
    monkeypatch.setattr(client, "_save_image_src", fake_save)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda seconds: None)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.time", lambda: next(times))

    artifact = client.edit_current_image(prompt="make lighting warmer", timeout_seconds=1)

    assert artifact.path == output_path
    assert saved_sources == ["https://assets.grok.com/generated/edited/image.jpg?cache=1"]
    assert any("clickGrokCurrentPostEditAction" in expression for expression in evaluate_calls)


def test_current_post_edit_action_js_targets_non_aria_clickable_edit_labels():
    from plugins.image_gen.grok_web_imagine import CLICK_CURRENT_POST_EDIT_ACTION_JS

    assert "button,a,[role=button],div,span" in CLICK_CURRENT_POST_EDIT_ACTION_JS
    assert 'closest(".query-bar")' in CLICK_CURRENT_POST_EDIT_ACTION_JS
    assert "area" in CLICK_CURRENT_POST_EDIT_ACTION_JS
    assert "a.area - b.area" in CLICK_CURRENT_POST_EDIT_ACTION_JS


def test_regenerate_current_image_clicks_post_regenerate_action(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, CDPClient

    client = CDPClient()
    current_image = {
        "tag": "IMG",
        "src": "https://assets.grok.com/generated/current/image.jpg?cache=1",
        "visible": True,
        "naturalWidth": 1024,
        "naturalHeight": 1024,
    }
    regenerated_image = {
        "tag": "IMG",
        "src": "https://assets.grok.com/generated/regenerated/image.jpg?cache=1",
        "visible": True,
        "naturalWidth": 1024,
        "naturalHeight": 1024,
    }
    media_snapshots = iter([
        [current_image],
        [current_image, regenerated_image],
    ])
    times = iter([0, 0.1, 0.2, 0.3])
    evaluate_calls = []
    saved_sources = []
    output_path = tmp_path / "regenerated.png"

    monkeypatch.setattr(client, "media", lambda: next(media_snapshots))
    monkeypatch.setattr(
        client,
        "snapshot",
        lambda: _snapshot(
            url="https://grok.com/imagine/post/7cdbd493-8d4d-4d84-b862-b92e4720f14c",
            title="Imagine - Grok",
            text="Imagine - Grok\n編輯\n重新產生",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    )

    def fake_evaluate(expression: str):
        evaluate_calls.append(expression)
        if "clickGrokCurrentPostRegenerateAction" in expression:
            return {"clicked": True, "label": "重新產生"}
        return {"ok": True}

    def fake_save(src: str) -> BrowserArtifact:
        saved_sources.append(src)
        return BrowserArtifact(path=output_path, source="browser_screenshot")

    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    monkeypatch.setattr(client, "_save_image_src", fake_save)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda seconds: None)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.time", lambda: next(times))

    artifact = client.regenerate_current_image(timeout_seconds=1)

    assert artifact.path == output_path
    assert saved_sources == ["https://assets.grok.com/generated/regenerated/image.jpg?cache=1"]
    assert any("clickGrokCurrentPostRegenerateAction" in expression for expression in evaluate_calls)


def test_current_post_regenerate_action_js_targets_regenerate_labels():
    from plugins.image_gen.grok_web_imagine import CLICK_CURRENT_POST_REGENERATE_ACTION_JS

    assert "regenerate" in CLICK_CURRENT_POST_REGENERATE_ACTION_JS
    assert "重新產生" in CLICK_CURRENT_POST_REGENERATE_ACTION_JS
    assert 'closest(".query-bar")' in CLICK_CURRENT_POST_REGENERATE_ACTION_JS


def test_generate_image_excludes_uploaded_reference_preview_from_artifact_candidates(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, CDPClient

    client = CDPClient()
    reference_preview = {
        "tag": "IMG",
        "src": "blob:https://grok.com/reference-preview",
        "visible": True,
        "naturalWidth": 1024,
        "naturalHeight": 1024,
    }
    generated_image = {
        "tag": "IMG",
        "src": "https://imagine-public.x.ai/generated-result.jpg",
        "visible": True,
        "naturalWidth": 832,
        "naturalHeight": 1248,
    }
    media_snapshots = iter([
        [],
        [reference_preview],
        [reference_preview, generated_image],
    ])
    saved_sources = []
    output_path = tmp_path / "generated-result.jpg"

    monkeypatch.setattr(client, "media", lambda: next(media_snapshots))
    monkeypatch.setattr(
        client,
        "snapshot",
        lambda: _snapshot(
            url="https://grok.com/imagine",
            title="Grok",
            text="Imagine\nCreate images and videos",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    )
    monkeypatch.setattr(client, "attach_images", lambda image_paths: image_paths)
    monkeypatch.setattr(client, "evaluate", lambda expression: {"filled": True})
    monkeypatch.setattr(client, "submit_prompt", lambda: None)

    def fake_save(src: str) -> BrowserArtifact:
        saved_sources.append(src)
        return BrowserArtifact(path=output_path, source="browser_url")

    monkeypatch.setattr(client, "_save_image_src", fake_save)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda seconds: None)

    artifact = client.generate_image(
        prompt="use the reference but create a new image",
        aspect_ratio="portrait",
        timeout_seconds=1,
        image_paths=["/tmp/reference.png"],
    )

    assert artifact.path == output_path
    assert saved_sources == ["https://imagine-public.x.ai/generated-result.jpg"]


def test_generate_image_reports_distinct_unusable_candidates_without_polling_inflation(monkeypatch):
    import pytest

    from plugins.image_gen.grok_web_imagine import CDPClient, GrokWebImagineError

    client = CDPClient()
    small_a = {
        "tag": "IMG",
        "src": "data:image/png;base64,small-a",
        "visible": True,
        "width": 299,
        "height": 211,
        "naturalWidth": 171,
        "naturalHeight": 256,
    }
    small_b = {
        "tag": "IMG",
        "src": "data:image/png;base64,small-b",
        "visible": True,
        "width": 299,
        "height": 211,
        "naturalWidth": 171,
        "naturalHeight": 256,
    }
    media_snapshots = iter([
        [],
        [small_a, small_b],
        [small_a, small_b],
    ])
    times = iter([0, 0.1, 0.2, 2.0])

    monkeypatch.setattr(client, "media", lambda: next(media_snapshots))
    monkeypatch.setattr(
        client,
        "snapshot",
        lambda: _snapshot(
            url="https://grok.com/imagine",
            title="Grok",
            text="Imagine\nCreate images and videos",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    )
    monkeypatch.setattr(client, "evaluate", lambda expression: {"filled": True})
    monkeypatch.setattr(client, "submit_prompt", lambda: None)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda seconds: None)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.time", lambda: next(times))

    with pytest.raises(GrokWebImagineError) as exc:
        client.generate_image(prompt="clean product photo", timeout_seconds=1)

    assert exc.value.code == "no_usable_generated_artifact"
    assert "2 distinct" in exc.value.message
    assert "minimum 256px-per-side artifact gate" in exc.value.message


def test_generate_image_recovers_when_candidate_disappears_during_screenshot_fallback(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, CDPClient, GrokWebImagineError

    client = CDPClient()
    first_image = {
        "tag": "IMG",
        "src": "https://assets.grok.com/generated/transition/image.jpg?cache=1",
        "visible": True,
        "naturalWidth": 832,
        "naturalHeight": 1248,
    }
    current_post_image = {
        "tag": "IMG",
        "src": "https://assets.grok.com/generated/current-post/image.jpg?cache=1",
        "visible": True,
        "naturalWidth": 832,
        "naturalHeight": 1248,
    }
    media_snapshots = iter([
        [],
        [first_image],
        [current_post_image],
    ])
    times = iter([0, 0.1, 0.2, 0.3])
    saved_sources = []
    output_path = tmp_path / "current-post.png"

    monkeypatch.setattr(client, "media", lambda: next(media_snapshots))
    monkeypatch.setattr(
        client,
        "snapshot",
        lambda: _snapshot(
            url="https://grok.com/imagine",
            title="Grok",
            text="Imagine\nCreate images and videos",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    )
    monkeypatch.setattr(client, "fill_prompt", lambda prompt: {"filled": True})
    monkeypatch.setattr(client, "submit_prompt", lambda: None)
    monkeypatch.setattr(client, "composer_has_draft", lambda: False)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda seconds: None)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.time", lambda: next(times))

    def fake_save(src: str) -> BrowserArtifact:
        saved_sources.append(src)
        if "transition" in src:
            raise GrokWebImagineError("artifact_extract_failed", "{'ok': False, 'error': 'image_element_not_found'}")
        return BrowserArtifact(path=output_path, source="browser_screenshot")

    monkeypatch.setattr(client, "_save_image_src", fake_save)

    artifact = client.generate_image(prompt="clean product photo", timeout_seconds=1)

    assert artifact.path == output_path
    assert saved_sources == [
        "https://assets.grok.com/generated/transition/image.jpg?cache=1",
        "https://assets.grok.com/generated/current-post/image.jpg?cache=1",
    ]


def test_save_http_image_src_falls_back_to_cdp_visible_image_screenshot(monkeypatch, tmp_path):
    import base64

    from plugins.image_gen.grok_web_imagine import CDPClient

    client = CDPClient()
    image_src = "https://assets.grok.com/users/example/generated/result/image.jpg?cache=1"
    output_path = tmp_path / "grok-visible.png"
    calls = []

    def fail_download(*args, **kwargs):
        raise RuntimeError("403 Client Error: Forbidden")

    def fake_evaluate(expression: str, **kwargs):
        calls.append(("evaluate", expression))
        if "prepareGrokImageForScreenshot" in expression:
            return {"ok": True, "naturalWidth": 720, "naturalHeight": 1280, "filter": "none"}
        if "findGrokImageForScreenshot" in expression:
            return {
                "ok": True,
                "clip": {"x": 100, "y": 50, "width": 320, "height": 568, "scale": 1},
                "naturalWidth": 720,
                "naturalHeight": 1280,
            }
        return {"ok": False, "error": "fetch_403"}

    def fake_send(method: str, params: dict | None = None):
        calls.append((method, params or {}))
        if method == "Page.captureScreenshot":
            return {"result": {"data": base64.b64encode(b"png screenshot").decode("ascii")}}
        raise AssertionError(f"unexpected CDP method: {method}")

    def fake_save_b64(data: str, **kwargs):
        assert base64.b64decode(data) == b"png screenshot"
        assert kwargs["prefix"] == "grok_web_imagine"
        assert kwargs["extension"] == "png"
        output_path.write_bytes(b"png screenshot")
        return output_path

    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.save_url_image", fail_download)
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.save_b64_image", fake_save_b64)
    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    monkeypatch.setattr(client, "_send", fake_send)

    artifact = client._save_image_src(image_src)

    assert artifact.path == output_path
    assert artifact.source == "browser_screenshot"
    assert (
        "Page.captureScreenshot",
        {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": False,
            "clip": {"x": 100, "y": 50, "width": 320, "height": 568, "scale": 2.0},
        },
    ) in calls
    evaluated = "\n".join(expression for kind, expression in calls if kind == "evaluate")
    assert "prepareGrokImageForScreenshot" in evaluated
    assert "data-hermes-grok-screenshot-hidden" in evaluated
    assert "restoreGrokScreenshotOverlays" in evaluated


def test_visible_image_clip_js_selects_before_scrolling_matching_images():
    from plugins.image_gen.grok_web_imagine import _visible_image_clip_js

    expression = _visible_image_clip_js("https://assets.grok.com/generated/image.jpg")
    selection_block = expression.split("const item = findGrokImageForScreenshot()", 1)[0]

    assert "scrollIntoView" not in selection_block
    assert "item.img.scrollIntoView" in expression


def test_fill_prompt_prefers_prompt_editor_before_generic_visible_input():
    from plugins.image_gen.grok_web_imagine import _fill_prompt_js

    expression = _fill_prompt_js("clean product photo")

    assert "promptLike" in expression
    assert "ask grok" in expression
    assert "els.find(promptLike)" in expression
    assert "execCommand('insertText'" in expression
    assert "filledText" in expression


def test_prompt_state_uses_whitespace_normalized_match():
    from plugins.image_gen.grok_web_imagine import _prompt_input_state_js

    expression = _prompt_input_state_js("line one\nline two")

    assert "normalizeText" in expression
    assert "normalizeText(filledText).includes(normalizeText(prompt))" in expression


def test_fill_prompt_uses_cdp_input_insert_text_for_prompt_editor(monkeypatch):
    from plugins.image_gen.grok_web_imagine import CDPClient

    client = CDPClient()
    calls = []

    def fake_evaluate(expression: str):
        if "focusGrokPromptInput" in expression:
            return {"focused": True, "contentEditable": True, "centerX": 520, "centerY": 760}
        if "grokPromptInputState" in expression:
            return {"filled": True, "submitReady": True, "filledText": "clean product photo"}
        raise AssertionError(f"unexpected evaluate: {expression[:120]}")

    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    monkeypatch.setattr(client, "_send", lambda method, params=None: calls.append((method, params or {})) or {"result": {}})

    result = client.fill_prompt("clean product photo")

    assert result["filled"] is True
    assert calls[:3] == [
        ("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 520, "y": 760}),
        ("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 520, "y": 760, "button": "left", "clickCount": 1}),
        ("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 520, "y": 760, "button": "left", "clickCount": 1}),
    ]
    assert calls[-1] == ("Input.insertText", {"text": "clean product photo"})


def test_fill_prompt_waits_for_submit_ready_after_reference_upload(monkeypatch):
    from plugins.image_gen.grok_web_imagine import CDPClient

    client = CDPClient()
    prompt_states = iter(
        [
            {
                "filled": True,
                "submitReady": False,
                "submitDisabled": True,
                "filledText": "clean product photo",
            },
            {
                "filled": True,
                "submitReady": True,
                "submitDisabled": False,
                "filledText": "clean product photo",
            },
        ]
    )
    sleeps = []

    def fake_evaluate(expression: str):
        if "focusGrokPromptInput" in expression:
            return {"focused": True, "contentEditable": True, "centerX": 520, "centerY": 760}
        if "grokPromptInputState" in expression:
            return next(prompt_states)
        if "const prompt =" in expression:
            raise AssertionError("DOM fallback should not run while waiting for submit readiness")
        raise AssertionError(f"unexpected evaluate: {expression[:120]}")

    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    monkeypatch.setattr(client, "_send", lambda method, params=None: {"result": {}})
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda seconds: sleeps.append(seconds))

    result = client.fill_prompt("clean product photo")

    assert result["filled"] is True
    assert sleeps


def test_generate_image_resets_dirty_composer_before_reference_upload(monkeypatch, tmp_path):
    from plugins.image_gen.grok_web_imagine import BrowserArtifact, CDPClient

    client = CDPClient()
    output_path = tmp_path / "generated-result.jpg"
    resets = []
    attached = []

    monkeypatch.setattr(client, "media", lambda: [])
    monkeypatch.setattr(
        client,
        "snapshot",
        lambda: _snapshot(
            url="https://grok.com/imagine",
            title="Grok",
            text="Imagine\nCreate images and videos",
            inputs=[{"tag": "DIV", "aria": "Ask Grok anything", "placeholder": None}],
        ),
    )
    monkeypatch.setattr(client, "composer_has_draft", lambda: True)
    monkeypatch.setattr(client, "open_new_generation_composer", lambda: resets.append("new"))
    monkeypatch.setattr(client, "attach_images", lambda image_paths: attached.extend(image_paths) or image_paths)
    monkeypatch.setattr(client, "fill_prompt", lambda prompt: {"filled": True})
    monkeypatch.setattr(client, "submit_prompt", lambda: None)
    monkeypatch.setattr(client, "_wait_for_new_image", lambda before, timeout: BrowserArtifact(path=output_path, source="browser_url"))
    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.time.sleep", lambda seconds: None)

    artifact = client.generate_image(
        prompt="use the reference",
        timeout_seconds=1,
        image_paths=["/tmp/reference.png"],
    )

    assert artifact.path == output_path
    assert resets == ["new"]
    assert attached == ["/tmp/reference.png"]


def test_submit_prompt_raises_when_submit_button_missing(monkeypatch):
    import pytest
    from plugins.image_gen.grok_web_imagine import CDPClient, GrokWebImagineError

    client = CDPClient()
    monkeypatch.setattr(client, "evaluate", lambda expression: {"submitted": False, "reason": "no_submit_button"})

    with pytest.raises(GrokWebImagineError) as exc:
        client.submit_prompt()

    assert exc.value.code == "submit_button_not_found"


def test_probe_cli_outputs_login_required(monkeypatch, capsys):
    from plugins.image_gen.grok_web_imagine import main

    class FakeClient:
        def __init__(self, port: int = 9223, url_contains: str = "x.ai"):
            assert port == 9223
            assert url_contains == "x.ai"

        def snapshot(self) -> dict:
            return _snapshot(
                url="https://accounts.x.ai/sign-in",
                title="登录您的 Grok 账户 | Grok",
                text="登录您的账户",
            )

    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.CDPClient", FakeClient)
    rc = main(["probe", "--port", "9223", "--url-contains", "x.ai"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "login_required"
    assert payload["safe_to_submit"] is False


def test_probe_cli_default_url_contains_matches_runtime_provider(monkeypatch, capsys):
    from plugins.image_gen.grok_web_imagine import DEFAULT_URL_CONTAINS, main

    class FakeClient:
        def __init__(self, port: int = 9223, url_contains: str = "x.ai"):
            assert port == 9223
            assert url_contains == DEFAULT_URL_CONTAINS

        def snapshot(self) -> dict:
            return _snapshot(
                url="https://grok.com/imagine/post/current",
                title="Imagine - Grok",
                text="Imagine - Grok\n編輯",
            )

    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.CDPClient", FakeClient)
    rc = main(["probe", "--port", "9223"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "imagine_post_open"
    assert payload["url"] == "https://grok.com/imagine/post/current"


def test_probe_cli_outputs_cdp_unreachable_instead_of_traceback(monkeypatch, capsys):
    import urllib.error

    from plugins.image_gen.grok_web_imagine import main

    class FakeClient:
        def __init__(self, port: int = 9223, url_contains: str = "x.ai"):
            pass

        def snapshot(self) -> dict:
            raise urllib.error.URLError(PermissionError("Operation not permitted"))

    monkeypatch.setattr("plugins.image_gen.grok_web_imagine.CDPClient", FakeClient)
    rc = main(["probe", "--port", "9223", "--url-contains", "grok.com"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "cdp_unreachable"
    assert payload["safe_to_submit"] is False
    assert "Chrome DevTools" in payload["message"]
