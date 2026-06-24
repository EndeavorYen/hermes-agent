"""Experimental Grok web Imagine image backend.

This provider is intentionally separate from ``plugins.image_gen.xai``:
the xAI API quota and the consumer Grok web quota are different operational
surfaces and must not be reported as the same provider health track.

The browser bridge only inspects visible DOM state through a user-launched
Chrome DevTools Protocol port. It does not read cookies, local storage, request
headers, or bearer tokens. It is disabled by default and requires an explicit
operator opt-in before generation can run.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import websocket

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_b64_image,
    save_url_image,
    success_response,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "grok-web-imagine"
MODEL_ID = "grok-web-imagine"
DEFAULT_CDP_PORT = 9223
DEFAULT_URL_CONTAINS = "grok.com,accounts.x.ai"


@dataclass(frozen=True)
class VisibleState:
    status: str
    safe_to_submit: bool
    message: str
    url: str = ""
    title: str = ""


@dataclass(frozen=True)
class BrowserArtifact:
    path: Path
    source: str


class GrokWebImagineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _text_values(items: Iterable[Dict[str, Any]]) -> List[str]:
    values: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("text", "aria", "placeholder"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    return values


def _has_any(haystack: str, needles: Iterable[str]) -> bool:
    lower = haystack.lower()
    return any(needle.lower() in lower for needle in needles)


def target_url_matches(url: str, patterns: str) -> bool:
    """Return True when *url* contains any comma-separated target pattern."""
    haystack = str(url or "")
    parts = [part.strip() for part in str(patterns or "").split(",") if part.strip()]
    return any(part in haystack for part in parts)


def _has_login_button(snapshot: Dict[str, Any]) -> bool:
    labels = _text_values(snapshot.get("buttons") or [])
    login_labels = {
        "login",
        "log in",
        "sign in",
        "signin",
        "登入",
        "登录",
        "使用邮箱登录",
        "使用 google 登录",
        "使用 apple 登录",
        "使用 𝕏 登录",
    }
    for label in labels:
        norm = label.strip().lower()
        if norm in login_labels:
            return True
        if norm.startswith("sign in") or norm.startswith("log in"):
            return True
    return False


def _has_prompt_input(snapshot: Dict[str, Any]) -> bool:
    input_text = "\n".join(_text_values(snapshot.get("inputs") or []))
    return _has_any(
        input_text,
        (
            "ask grok",
            "what do you want",
            "prompt",
            "message",
            "make",
            "create",
            "問 grok",
            "你想知道什麼",
        ),
    )


def classify_visible_state(snapshot: Dict[str, Any]) -> VisibleState:
    """Classify a visible Grok/Imagine page snapshot without private state."""
    url = str(snapshot.get("url") or "")
    title = str(snapshot.get("title") or "")
    text = str(snapshot.get("text") or "")
    combined = "\n".join([url, title, text, "\n".join(_text_values(snapshot.get("buttons") or []))])
    url_lower = url.lower()

    if _has_any(combined, ("cloudflare", "verify you are human", "驗證您是否為真人")):
        return VisibleState(
            status="cloudflare_required",
            safe_to_submit=False,
            message="Grok web is behind a manual verification challenge; do not bypass it.",
            url=url,
            title=title,
        )

    if "accounts.x.ai/sign-in" in url or "accounts.x.ai/login" in url or _has_login_button(snapshot):
        return VisibleState(
            status="login_required",
            safe_to_submit=False,
            message="Grok web requires manual login in the debug Chrome window.",
            url=url,
            title=title,
        )

    if "/build" in url_lower:
        return VisibleState(
            status="grok_build_open",
            safe_to_submit=False,
            message="Grok Build is open; switch to Grok Imagine before running image generation.",
            url=url,
            title=title,
        )

    if (
        "/imagine" in url_lower
        and _has_any(combined, ("imagine", "create images", "create videos", "generate image"))
        and _has_prompt_input(snapshot)
    ):
        return VisibleState(
            status="imagine_ready",
            safe_to_submit=True,
            message="Grok web Imagine appears ready for a user-authorized generation attempt.",
            url=url,
            title=title,
        )

    if "grok.com" in url and _has_prompt_input(snapshot):
        return VisibleState(
            status="grok_ready",
            safe_to_submit=True,
            message="Grok web prompt input is visible; Imagine mode may need to be selected.",
            url=url,
            title=title,
        )

    return VisibleState(
        status="unknown",
        safe_to_submit=False,
        message="Grok web state is not recognized enough to submit safely.",
        url=url,
        title=title,
    )


SNAPSHOT_JS = r"""
(() => ({
  title: document.title,
  url: location.href,
  text: (document.body && document.body.innerText || "").slice(0, 1600),
  buttons: [...document.querySelectorAll("button,a,[role=button]")]
    .map((e) => ({
      text: (e.innerText || e.getAttribute("aria-label") || e.textContent || "").trim().slice(0, 120),
      aria: e.getAttribute("aria-label"),
      href: e.href || null
    }))
    .filter(x => x.text || x.aria || x.href)
    .slice(0, 40),
  inputs: [...document.querySelectorAll("textarea,input,[contenteditable=true]")]
    .map((e) => ({
      tag: e.tagName,
      aria: e.getAttribute("aria-label"),
      placeholder: e.getAttribute("placeholder"),
      text: (e.innerText || e.value || "").slice(0, 120)
    }))
    .slice(0, 20)
}))()
"""


MEDIA_JS = r"""
(() => [...document.querySelectorAll("img,video")]
  .map((e) => {
    const r = e.getBoundingClientRect();
    const src = e.currentSrc || e.src || "";
    return {
      tag: e.tagName,
      src,
      width: Math.round(r.width),
      height: Math.round(r.height),
      naturalWidth: e.naturalWidth || e.videoWidth || 0,
      naturalHeight: e.naturalHeight || e.videoHeight || 0,
      alt: e.alt || "",
      visible: r.width >= 128 && r.height >= 128
    };
  })
  .filter(x => x.src && x.visible && (x.naturalWidth >= 256 || x.width >= 256))
)()
"""


def _fill_prompt_js(prompt: str) -> str:
    return (
        "(() => {"
        "const prompt = "
        + json.dumps(prompt)
        + ";"
        "const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 20 && r.height > 20; };"
        "const els = [...document.querySelectorAll('textarea,input,[contenteditable=true]')].filter(visible);"
        "const el = els.find(e => e.tagName === 'TEXTAREA') || els[0];"
        "if (!el) return {filled:false, reason:'no_prompt_input'};"
        "el.focus();"
        "if (el.isContentEditable) { el.textContent = prompt; }"
        "else {"
        "  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
        "  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;"
        "  setter.call(el, prompt);"
        "}"
        "el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:prompt}));"
        "el.dispatchEvent(new Event('change', {bubbles:true}));"
        "return {filled:true};"
        "})()"
    )


def _click_imagine_js() -> str:
    return (
        "(() => {"
        "const els = [...document.querySelectorAll('button,a,[role=button]')];"
        "const el = els.find(e => ((e.innerText || e.getAttribute('aria-label') || e.textContent || '').trim().toLowerCase()).includes('imagine'));"
        "if (!el) return {clicked:false};"
        "el.click();"
        "return {clicked:true};"
        "})()"
    )


def _src_to_data_url_js(src: str) -> str:
    return r"""
(async () => {
  const src = __SRC__;
  if (src.startsWith("data:")) return {ok:true, dataUrl:src};
  const response = await fetch(src);
  if (!response.ok) return {ok:false, error:`fetch_${response.status}`};
  const blob = await response.blob();
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("file_reader_failed"));
    reader.readAsDataURL(blob);
  });
  return {ok:true, dataUrl};
})()
""".replace("__SRC__", json.dumps(src))


class CDPClient:
    """Small Chrome DevTools Protocol client for visible-page automation."""

    def __init__(self, port: int = DEFAULT_CDP_PORT, url_contains: str = DEFAULT_URL_CONTAINS):
        self.port = port
        self.url_contains = url_contains
        self._id = 0

    def _page_ws_url(self) -> str:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=5) as response:
            targets = json.loads(response.read().decode("utf-8"))
        for target in targets:
            if target.get("type") == "page" and target_url_matches(str(target.get("url", "")), self.url_contains):
                return str(target["webSocketDebuggerUrl"])
        raise GrokWebImagineError(
            "browser_page_not_found",
            f"No Chrome page target contains {self.url_contains!r} on CDP port {self.port}.",
        )

    def _send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._id += 1
        ws = websocket.create_connection(
            self._page_ws_url(),
            timeout=10,
            origin=f"http://127.0.0.1:{self.port}",
        )
        try:
            ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
            while True:
                response = json.loads(ws.recv())
                if response.get("id") == self._id:
                    return response
        finally:
            ws.close()

    def evaluate(self, expression: str, *, await_promise: bool = True) -> Any:
        response = self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        if "error" in response:
            raise GrokWebImagineError("cdp_error", str(response["error"]))
        result = response.get("result", {})
        value = result.get("result", {})
        if value.get("subtype") == "error":
            raise GrokWebImagineError("browser_eval_error", str(value.get("description") or value))
        return value.get("value")

    def navigate(self, url: str) -> None:
        response = self._send("Page.navigate", {"url": url})
        if "error" in response:
            raise GrokWebImagineError("cdp_error", str(response["error"]))

    def press_enter(self) -> None:
        for event_type in ("keyDown", "keyUp"):
            response = self._send(
                "Input.dispatchKeyEvent",
                {
                    "type": event_type,
                    "key": "Enter",
                    "code": "Enter",
                    "windowsVirtualKeyCode": 13,
                    "nativeVirtualKeyCode": 13,
                },
            )
            if "error" in response:
                raise GrokWebImagineError("cdp_error", str(response["error"]))

    def snapshot(self) -> Dict[str, Any]:
        value = self.evaluate(SNAPSHOT_JS)
        return value if isinstance(value, dict) else {}

    def media(self) -> List[Dict[str, Any]]:
        value = self.evaluate(MEDIA_JS)
        return value if isinstance(value, list) else []

    def generate_image(
        self,
        *,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        timeout_seconds: int = 240,
    ) -> BrowserArtifact:
        before = {str(item.get("src") or "") for item in self.media()}
        snapshot = self.snapshot()
        state = classify_visible_state(snapshot)
        if state.status == "grok_ready":
            self.evaluate(_click_imagine_js())
            time.sleep(2)
            state = classify_visible_state(self.snapshot())
        if state.status not in {"imagine_ready", "grok_ready"}:
            raise GrokWebImagineError(state.status, state.message)

        filled = self.evaluate(_fill_prompt_js(prompt))
        if not isinstance(filled, dict) or not filled.get("filled"):
            raise GrokWebImagineError("prompt_input_not_found", "Could not find a visible Grok prompt input.")

        self.press_enter()

        deadline = time.time() + timeout_seconds
        last_media: List[Dict[str, Any]] = []
        while time.time() < deadline:
            time.sleep(4)
            current = self.media()
            last_media = current
            for item in reversed(current):
                src = str(item.get("src") or "")
                if not src or src in before:
                    continue
                if item.get("tag") != "IMG":
                    continue
                return self._save_image_src(src)

        raise GrokWebImagineError(
            "timeout",
            f"No new Grok web image appeared within {timeout_seconds}s; observed {len(last_media)} media nodes.",
        )

    def _save_image_src(self, src: str) -> BrowserArtifact:
        if src.startswith("data:image/"):
            path = _save_data_url(src)
            return BrowserArtifact(path=path, source="browser_data_url")
        if src.startswith("blob:"):
            payload = self.evaluate(_src_to_data_url_js(src))
            if not isinstance(payload, dict) or not payload.get("ok"):
                raise GrokWebImagineError("artifact_extract_failed", str(payload))
            path = _save_data_url(str(payload["dataUrl"]))
            return BrowserArtifact(path=path, source="browser_blob")
        if src.startswith(("http://", "https://")):
            try:
                path = save_url_image(src, prefix=PROVIDER_NAME.replace("-", "_"), timeout=90)
            except Exception:
                payload = self.evaluate(_src_to_data_url_js(src))
                if not isinstance(payload, dict) or not payload.get("ok"):
                    raise
                path = _save_data_url(str(payload["dataUrl"]))
                return BrowserArtifact(path=path, source="browser_fetch")
            return BrowserArtifact(path=path, source="browser_url")
        raise GrokWebImagineError("unsupported_artifact_src", "Unsupported Grok web artifact source.")


def _save_data_url(data_url: str) -> Path:
    header, _, b64 = data_url.partition(",")
    if not b64:
        raise GrokWebImagineError("artifact_extract_failed", "Data URL did not contain base64 payload.")
    extension = "png"
    if "image/" in header:
        extension = header.split("image/", 1)[1].split(";", 1)[0] or "png"
    if extension == "jpeg":
        extension = "jpg"
    # Validate before passing to the shared saver so errors surface cleanly.
    base64.b64decode(b64)
    return save_b64_image(b64, prefix=PROVIDER_NAME.replace("-", "_"), extension=extension)


def _load_grok_web_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        image_gen = cfg.get("image_gen") if isinstance(cfg, dict) else None
        web_cfg = image_gen.get("grok_web_imagine") if isinstance(image_gen, dict) else None
        return web_cfg if isinstance(web_cfg, dict) else {}
    except Exception as exc:
        logger.debug("Could not load image_gen.grok_web_imagine config: %s", exc)
        return {}


def _is_enabled() -> bool:
    env = os.environ.get("HERMES_GROK_WEB_IMAGINE")
    if isinstance(env, str) and env.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    cfg = _load_grok_web_config()
    return bool(cfg.get("enabled") is True)


def _configured_port() -> int:
    env = os.environ.get("HERMES_GROK_WEB_IMAGINE_CDP_PORT")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    cfg = _load_grok_web_config()
    value = cfg.get("cdp_port")
    return int(value) if isinstance(value, int) else DEFAULT_CDP_PORT


def _configured_url_contains() -> str:
    cfg = _load_grok_web_config()
    value = cfg.get("url_contains")
    return value if isinstance(value, str) and value.strip() else DEFAULT_URL_CONTAINS


class GrokWebImagineProvider(ImageGenProvider):
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Grok Web Imagine"

    def __init__(self, cdp_client: Optional[CDPClient] = None):
        self._cdp_client = cdp_client

    def is_available(self) -> bool:
        return _is_enabled()

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": MODEL_ID,
                "display": "Grok Web Imagine",
                "speed": "web UI",
                "strengths": "Uses the logged-in Grok consumer web Imagine quota.",
            }
        ]

    def default_model(self) -> Optional[str]:
        return MODEL_ID

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Grok Web Imagine",
            "badge": "experimental",
            "tag": "Opt-in browser bridge for logged-in Grok web Imagine quota; no cookie/token access.",
            "env_vars": [],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text"], "max_reference_images": 0}

    def _client(self) -> CDPClient:
        return self._cdp_client or CDPClient(port=_configured_port(), url_contains=_configured_url_contains())

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        aspect = resolve_aspect_ratio(aspect_ratio)
        if not _is_enabled():
            return error_response(
                error=(
                    "Grok web Imagine provider is disabled by default. Set "
                    "HERMES_GROK_WEB_IMAGINE=1 or image_gen.grok_web_imagine.enabled=true."
                ),
                error_type="disabled_by_default",
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        if image_url or reference_image_urls:
            return error_response(
                error="Grok web Imagine provider currently supports text-to-image only.",
                error_type="unsupported_reference_images",
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        client = self._client()
        try:
            state = classify_visible_state(client.snapshot())
        except GrokWebImagineError as exc:
            return error_response(
                error=exc.message,
                error_type=exc.code,
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except Exception as exc:  # noqa: BLE001
            return error_response(
                error=f"Could not inspect Grok web browser state: {exc}",
                error_type="browser_probe_failed",
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        if not state.safe_to_submit:
            return error_response(
                error=f"{state.message} Open the debug Chrome window and complete the setup before retrying.",
                error_type=state.status,
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            artifact = client.generate_image(
                prompt=prompt,
                aspect_ratio=aspect,
                timeout_seconds=int(kwargs.get("timeout_seconds") or 240),
            )
        except GrokWebImagineError as exc:
            return error_response(
                error=exc.message,
                error_type=exc.code,
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except Exception as exc:  # noqa: BLE001
            return error_response(
                error=f"Grok web Imagine browser generation failed: {exc}",
                error_type="browser_generation_failed",
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        return success_response(
            image=str(artifact.path),
            model=MODEL_ID,
            prompt=prompt,
            aspect_ratio=aspect,
            provider=PROVIDER_NAME,
            modality="text",
            extra={
                "provider_family": "grok_web",
                "quota_source": "consumer_web",
                "artifact_source": artifact.source,
            },
        )


def register(ctx: Any) -> None:
    ctx.register_image_gen_provider(GrokWebImagineProvider())


def _state_payload(state: VisibleState) -> Dict[str, Any]:
    return {
        "status": state.status,
        "safe_to_submit": state.safe_to_submit,
        "message": state.message,
        "url": state.url,
        "title": state.title,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe or run the experimental Grok web Imagine browser bridge.")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="Inspect visible Grok web state without submitting.")
    probe.add_argument("--port", type=int, default=DEFAULT_CDP_PORT)
    probe.add_argument("--url-contains", default="x.ai")

    args = parser.parse_args(argv)
    if args.command == "probe":
        client = CDPClient(port=args.port, url_contains=args.url_contains)
        state = classify_visible_state(client.snapshot())
        print(json.dumps(_state_payload(state), ensure_ascii=False, indent=2))
        return 0 if state.safe_to_submit else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
