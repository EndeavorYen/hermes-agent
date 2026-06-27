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


def test_provider_scopes_reference_error_to_browser_bridge(monkeypatch):
    from plugins.image_gen.grok_web_imagine import GrokWebImagineProvider

    monkeypatch.setenv("HERMES_GROK_WEB_IMAGINE", "1")
    provider = GrokWebImagineProvider(cdp_client=MagicMock())

    result = provider.generate(
        "keep this character",
        reference_image_urls=["https://example.com/ref.png"],
    )

    assert result["success"] is False
    assert result["error_type"] == "unsupported_reference_images"
    assert "browser bridge" in result["error"]
    assert "xAI image provider" in result["error"]


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
    cdp.generate_image.return_value = BrowserArtifact(path=image_path, source="browser")
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


def test_submit_prompt_uses_visible_submit_button(monkeypatch):
    from plugins.image_gen.grok_web_imagine import CDPClient

    client = CDPClient()
    calls = []

    def fake_evaluate(expression: str):
        calls.append(expression)
        return {"submitted": True, "method": "submit_button", "label": "送出"}

    monkeypatch.setattr(client, "evaluate", fake_evaluate)

    client.submit_prompt()

    assert calls
    assert "button[type=submit]" in calls[0]


def test_fill_prompt_prefers_prompt_editor_before_generic_visible_input():
    from plugins.image_gen.grok_web_imagine import _fill_prompt_js

    expression = _fill_prompt_js("clean product photo")

    assert "promptLike" in expression
    assert "ask grok" in expression
    assert "els.find(promptLike)" in expression


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
