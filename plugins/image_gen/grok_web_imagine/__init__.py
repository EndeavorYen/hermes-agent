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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import websocket
except ModuleNotFoundError:  # pragma: no cover - exercised through CDP send path
    websocket = None

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
MIN_USABLE_IMAGE_SIDE = 256
MAX_REFERENCE_IMAGES = 4
REFERENCE_UPLOAD_SETTLE_SECONDS = 1.5
SCREENSHOT_FALLBACK_SETTLE_MS = 12000
MAX_SCREENSHOT_FALLBACK_SCALE = 2.0
CDP_WEBSOCKET_TIMEOUT_SECONDS = max(30.0, (SCREENSHOT_FALLBACK_SETTLE_MS / 1000) + 10.0)


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


def media_item_is_usable_image(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("tag") != "IMG" or not item.get("visible"):
        return False
    src = item.get("src")
    if not isinstance(src, str) or not src.strip():
        return False
    try:
        natural_width = int(item.get("naturalWidth") or 0)
        natural_height = int(item.get("naturalHeight") or 0)
    except (TypeError, ValueError):
        return False
    return natural_width >= MIN_USABLE_IMAGE_SIDE and natural_height >= MIN_USABLE_IMAGE_SIDE


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

    if "/imagine/post/" in url_lower:
        return VisibleState(
            status="imagine_post_open",
            safe_to_submit=False,
            message="Grok Imagine is showing an existing result page; switch to the create composer first.",
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

    if _has_any(combined, ("upgrade to supergrok", "升級至 supergrok", "升級到 supergrok")):
        return VisibleState(
            status="subscription_required",
            safe_to_submit=False,
            message="Grok Imagine is showing a SuperGrok upgrade prompt; use a SuperGrok-enabled web session.",
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


def _cdp_unreachable_state(exc: Exception) -> VisibleState:
    return VisibleState(
        status="cdp_unreachable",
        safe_to_submit=False,
        message=f"Could not reach Chrome DevTools for Grok web Imagine: {exc}",
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
        "const label = (e) => `${e.getAttribute('aria-label') || ''} ${e.getAttribute('placeholder') || ''}`.trim().toLowerCase();"
        "const promptLike = (e) => /ask grok|what do you want|prompt|message|make|create|問 grok|你想知道什麼/.test(label(e));"
        "const els = [...document.querySelectorAll('textarea,input,[contenteditable=true]')].filter(visible);"
        "const el = els.find(promptLike) || els.find(e => e.tagName === 'TEXTAREA') || els.find(e => e.isContentEditable) || els[0];"
        "if (!el) return {filled:false, reason:'no_prompt_input'};"
        "el.focus();"
        "if (el.isContentEditable) {"
        "  const range = document.createRange();"
        "  range.selectNodeContents(el);"
        "  const selection = window.getSelection();"
        "  selection.removeAllRanges();"
        "  selection.addRange(range);"
        "  document.execCommand('insertText', false, prompt);"
        "}"
        "else {"
        "  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
        "  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;"
        "  setter.call(el, prompt);"
        "}"
        "el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:prompt}));"
        "el.dispatchEvent(new Event('change', {bubbles:true}));"
        "const filledText = (el.innerText || el.value || el.textContent || '').trim();"
        "return {filled:filledText.includes(prompt), filledText:filledText.slice(0, 120)};"
        "})()"
    )


FOCUS_PROMPT_INPUT_JS = r"""
(() => {
  const focusGrokPromptInput = () => {
    const visible = (e) => {
      const r = e.getBoundingClientRect();
      return r.width > 20 && r.height > 20;
    };
    const label = (e) => `${e.getAttribute("aria-label") || ""} ${e.getAttribute("placeholder") || ""}`.trim().toLowerCase();
    const promptLike = (e) => /ask grok|what do you want|prompt|message|make|create|問 grok|你想知道什麼/.test(label(e));
    const els = [...document.querySelectorAll("textarea,input,[contenteditable=true]")].filter(visible);
    const el = els.find(promptLike) || els.find(e => e.tagName === "TEXTAREA") || els.find(e => e.isContentEditable) || els[0];
    if (!el) return {focused:false, reason:"no_prompt_input"};
    el.focus();
    if (el.isContentEditable) {
      const range = document.createRange();
      range.selectNodeContents(el);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    } else if (typeof el.select === "function") {
      el.select();
    }
    return {
      focused: document.activeElement === el || el.contains(document.activeElement),
      contentEditable: Boolean(el.isContentEditable),
      tag: el.tagName,
      text: (el.innerText || el.value || el.textContent || "").trim().slice(0, 120)
    };
  };
  return focusGrokPromptInput();
})()
"""


def _prompt_input_state_js(prompt: str) -> str:
    return (
        "(() => {"
        "const prompt = "
        + json.dumps(prompt)
        + ";"
        "const grokPromptInputState = () => {"
        "const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 20 && r.height > 20; };"
        "const label = (e) => `${e.getAttribute('aria-label') || ''} ${e.getAttribute('placeholder') || ''}`.trim().toLowerCase();"
        "const promptLike = (e) => /ask grok|what do you want|prompt|message|make|create|問 grok|你想知道什麼/.test(label(e));"
        "const els = [...document.querySelectorAll('textarea,input,[contenteditable=true]')].filter(visible);"
        "const el = els.find(promptLike) || els.find(e => e.tagName === 'TEXTAREA') || els.find(e => e.isContentEditable) || els[0];"
        "if (!el) return {filled:false, reason:'no_prompt_input'};"
        "const filledText = (el.innerText || el.value || el.textContent || '').trim();"
        "return {filled:filledText.includes(prompt), filledText:filledText.slice(0, 120), tag:el.tagName};"
        "};"
        "return grokPromptInputState();"
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


CLICK_CURRENT_POST_EDIT_ACTION_JS = r"""
(() => {
  const clickGrokCurrentPostEditAction = () => {
    const visible = (e) => {
      const r = e.getBoundingClientRect();
      return r.width > 12 && r.height > 12;
    };
    const label = (e) => (
      e.innerText || e.getAttribute("aria-label") || e.getAttribute("title") || e.textContent || ""
    ).trim();
    const controls = [...document.querySelectorAll("button,a,[role=button],div,span")]
      .filter((e) => visible(e) && !e.disabled && e.getAttribute("aria-disabled") !== "true")
      .filter((e) => !e.closest(".query-bar"))
      .map((e) => {
        const r = e.getBoundingClientRect();
        return {el:e, text:label(e), area:Math.max(0, r.width) * Math.max(0, r.height)};
      })
      .filter((item) => item.text);
    controls.sort((a, b) => a.area - b.area);
    const edit = controls.find((item) => /^(edit|modify|remix|編輯|编辑|修改)$/i.test(item.text))
      || controls.find((item) => /(edit|modify|remix|編輯|编辑|修改)/i.test(item.text));
    if (!edit) return {clicked:false, reason:"edit_action_not_found"};
    edit.el.click();
    return {clicked:true, label:edit.text.slice(0, 120)};
  };
  return clickGrokCurrentPostEditAction();
})()
"""


SUBMIT_PROMPT_JS = r"""
(() => {
  const visible = (e) => {
    const r = e.getBoundingClientRect();
    return r.width > 20 && r.height > 20;
  };
  const label = (e) => (e.innerText || e.getAttribute("aria-label") || e.textContent || "").trim();
  const buttons = [...document.querySelectorAll("button[type=submit],button,[role=button]")]
    .filter((e) => visible(e) && !e.disabled && e.getAttribute("aria-disabled") !== "true");
  const submit = buttons.find((e) => e.matches("button[type=submit]"))
    || buttons.find((e) => /^(send|submit|generate|create|edit|modify|送出|產生|生成|編輯|编辑|修改)$/i.test(label(e)));
  if (!submit) return {submitted:false, reason:"no_submit_button"};
  submit.click();
  return {submitted:true, method:"submit_button", label:label(submit), type:submit.getAttribute("type")};
})()
"""


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


def _visible_image_clip_js(src: str) -> str:
    return r"""
(() => {
  const src = __SRC__;
  const findGrokImageForScreenshot = () => {
    const images = [...document.querySelectorAll("img")]
      .filter((img) => (img.currentSrc || img.src) === src)
      .map((img) => {
        const r = img.getBoundingClientRect();
        return {
          img,
          rect: {x: r.x, y: r.y, width: r.width, height: r.height},
          area: Math.max(0, r.width) * Math.max(0, r.height),
          naturalWidth: img.naturalWidth || 0,
          naturalHeight: img.naturalHeight || 0
        };
      })
      .filter((item) => (
        item.rect.width >= 32 &&
        item.rect.height >= 32 &&
        item.naturalWidth >= 32 &&
        item.naturalHeight >= 32
      ));
    images.sort((a, b) => b.area - a.area);
    return images[0] || null;
  };
  const item = findGrokImageForScreenshot();
  if (!item) return {ok:false, error:"image_element_not_found"};
  item.img.scrollIntoView({block: "center", inline: "center"});
  const refreshed = item.img.getBoundingClientRect();
  const r = {x: refreshed.x, y: refreshed.y, width: refreshed.width, height: refreshed.height};
  let hiddenCount = 0;
  [...document.body.querySelectorAll("*")].forEach((el) => {
    if (el === item.img || el.contains(item.img) || item.img.contains(el)) return;
    const er = el.getBoundingClientRect();
    const overlaps = !(er.right <= r.left || er.left >= r.right || er.bottom <= r.top || er.top >= r.bottom);
    if (!overlaps) return;
    const style = window.getComputedStyle(el);
    const className = String(el.className || "");
    const looksOverlay = (
      style.position === "absolute" ||
      style.position === "fixed" ||
      style.position === "sticky" ||
      /\b(absolute|fixed|sticky)\b/.test(className)
    );
    if (!looksOverlay) return;
    el.setAttribute("data-hermes-grok-screenshot-hidden", el.style.visibility || "");
    el.style.visibility = "hidden";
    hiddenCount += 1;
  });
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  const x = Math.max(0, r.x);
  const y = Math.max(0, r.y);
  const width = Math.max(1, Math.min(r.width, viewportWidth - x));
  const height = Math.max(1, Math.min(r.height, viewportHeight - y));
  return {
    ok:true,
    clip:{x, y, width, height, scale:1},
    naturalWidth:item.naturalWidth,
    naturalHeight:item.naturalHeight,
    hiddenOverlayCount:hiddenCount
  };
})()
""".replace("__SRC__", json.dumps(src))


def _prepare_visible_image_for_screenshot_js(src: str) -> str:
    return r"""
(async () => {
  const src = __SRC__;
  const settleMs = __SETTLE_MS__;
  const prepareGrokImageForScreenshot = async () => {
    const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
    const findImage = () => {
      const images = [...document.querySelectorAll("img")]
        .filter((img) => (img.currentSrc || img.src) === src)
        .map((img) => {
          const r = img.getBoundingClientRect();
          return {
            img,
            area: Math.max(0, r.width) * Math.max(0, r.height),
            visible: r.width >= 32 && r.height >= 32
          };
        })
        .filter((item) => item.visible);
      images.sort((a, b) => b.area - a.area);
      return images[0] ? images[0].img : null;
    };
    const img = findImage();
    if (!img) return {ok:false, error:"image_element_not_found"};
    img.scrollIntoView({block: "center", inline: "center"});
    try {
      if (typeof img.decode === "function") await img.decode();
    } catch (_) {}
    let filter = "";
    let opacity = 1;
    for (let attempt = 0; attempt < 24; attempt += 1) {
      const style = window.getComputedStyle(img);
      filter = style.filter || "";
      opacity = Number.parseFloat(style.opacity || "1");
      const clear = (
        img.complete &&
        img.naturalWidth >= 256 &&
        img.naturalHeight >= 256 &&
        !/blur\(/i.test(filter) &&
        opacity >= 0.95
      );
      if (clear) break;
      await wait(150);
    }
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await wait(settleMs);
    return {
      ok:true,
      complete:Boolean(img.complete),
      naturalWidth:img.naturalWidth || 0,
      naturalHeight:img.naturalHeight || 0,
      filter,
      opacity
    };
  };
  return await prepareGrokImageForScreenshot();
})()
""".replace("__SRC__", json.dumps(src)).replace("__SETTLE_MS__", str(SCREENSHOT_FALLBACK_SETTLE_MS))


RESTORE_VISIBLE_IMAGE_OVERLAYS_JS = r"""
(() => {
  const restoreGrokScreenshotOverlays = () => {
    let restored = 0;
    document.querySelectorAll("[data-hermes-grok-screenshot-hidden]").forEach((el) => {
      const previous = el.getAttribute("data-hermes-grok-screenshot-hidden") || "";
      el.style.visibility = previous;
      el.removeAttribute("data-hermes-grok-screenshot-hidden");
      restored += 1;
    });
    return restored;
  };
  return {restored: restoreGrokScreenshotOverlays()};
})()
"""


OPEN_REFERENCE_PICKER_JS = r"""
(() => {
  const visible = (e) => {
    const r = e.getBoundingClientRect();
    return r.width > 8 && r.height > 8;
  };
  const label = (e) => (
    e.innerText || e.getAttribute("aria-label") || e.getAttribute("title") || e.textContent || ""
  ).trim();
  if (document.querySelector("input[type=file]")) {
    return {clicked:false, fileInputPresent:true};
  }
  const candidates = [...document.querySelectorAll("button,[role=button],a,label")]
    .filter((e) => visible(e));
  const target = candidates.find((e) => (
    /(attach|upload|image|photo|reference|add image|上傳|上传|圖片|图片|照片|新增)/i.test(label(e))
  ));
  if (!target) return {clicked:false, fileInputPresent:false};
  target.click();
  return {clicked:true, label:label(target).slice(0, 120)};
})()
"""


DISPATCH_FILE_INPUT_CHANGE_JS = r"""
(() => {
  const inputs = [...document.querySelectorAll("input[type=file]")];
  const input = inputs[inputs.length - 1];
  if (!input) return {changed:false, reason:"no_file_input"};
  input.dispatchEvent(new Event("input", {bubbles:true}));
  input.dispatchEvent(new Event("change", {bubbles:true}));
  return {changed:true, fileCount: input.files ? input.files.length : null};
})()
"""


class CDPClient:
    """Small Chrome DevTools Protocol client for visible-page automation."""

    def __init__(self, port: int = DEFAULT_CDP_PORT, url_contains: str = DEFAULT_URL_CONTAINS):
        self.port = port
        self.url_contains = url_contains
        self._id = 0

    def _page_ws_url(self) -> str:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=5) as response:
                targets = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise GrokWebImagineError("cdp_unreachable", _cdp_unreachable_state(exc).message) from exc
        for target in targets:
            if target.get("type") == "page" and target_url_matches(str(target.get("url", "")), self.url_contains):
                return str(target["webSocketDebuggerUrl"])
        raise GrokWebImagineError(
            "browser_page_not_found",
            f"No Chrome page target contains {self.url_contains!r} on CDP port {self.port}.",
        )

    def _connect(self) -> Any:
        if websocket is None:
            raise GrokWebImagineError(
                "websocket_client_unavailable",
                "The websocket-client package is required for Grok web CDP automation.",
            )
        return websocket.create_connection(
            self._page_ws_url(),
            timeout=CDP_WEBSOCKET_TIMEOUT_SECONDS,
            origin=f"http://127.0.0.1:{self.port}",
        )

    def _send_on_ws(self, ws: Any, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._id += 1
        ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(ws.recv())
            if response.get("id") == self._id:
                return response

    def _send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ws = self._connect()
        try:
            return self._send_on_ws(ws, method, params)
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

    def submit_prompt(self) -> None:
        value = self.evaluate(SUBMIT_PROMPT_JS)
        if not isinstance(value, dict) or not value.get("submitted"):
            reason = value.get("reason") if isinstance(value, dict) else "unknown"
            raise GrokWebImagineError(
                "submit_button_not_found",
                f"Could not find a visible Grok Imagine submit button ({reason}).",
            )

    def fill_prompt(self, prompt: str) -> Dict[str, Any]:
        focused = self.evaluate(FOCUS_PROMPT_INPUT_JS)
        if not isinstance(focused, dict) or not focused.get("focused"):
            fallback = self.evaluate(_fill_prompt_js(prompt))
            return fallback if isinstance(fallback, dict) else {"filled": False, "reason": "prompt_input_not_found"}

        try:
            response = self._send("Input.insertText", {"text": prompt})
            if "error" in response:
                raise GrokWebImagineError("cdp_error", str(response["error"]))
        except GrokWebImagineError:
            logger.debug("Could not insert Grok web prompt via CDP input; falling back to DOM input", exc_info=True)
            fallback = self.evaluate(_fill_prompt_js(prompt))
            return fallback if isinstance(fallback, dict) else {"filled": False, "reason": "prompt_insert_failed"}

        state = self.evaluate(_prompt_input_state_js(prompt))
        if isinstance(state, dict) and state.get("filled"):
            return state
        fallback = self.evaluate(_fill_prompt_js(prompt))
        return fallback if isinstance(fallback, dict) else {"filled": False, "reason": "prompt_state_unconfirmed"}

    def snapshot(self) -> Dict[str, Any]:
        value = self.evaluate(SNAPSHOT_JS)
        return value if isinstance(value, dict) else {}

    def media(self) -> List[Dict[str, Any]]:
        value = self.evaluate(MEDIA_JS)
        return value if isinstance(value, list) else []

    def click_current_post_edit_action(self) -> Dict[str, Any]:
        value = self.evaluate(CLICK_CURRENT_POST_EDIT_ACTION_JS)
        return value if isinstance(value, dict) else {"clicked": False, "reason": "unknown"}

    def attach_images(self, image_paths: List[str]) -> List[str]:
        paths = [str(Path(path).expanduser().resolve()) for path in image_paths if str(path or "").strip()]
        if not paths:
            return []
        for path in paths:
            if not Path(path).is_file():
                raise GrokWebImagineError("reference_image_not_found", f"Reference image does not exist: {path}")

        try:
            self.evaluate(OPEN_REFERENCE_PICKER_JS)
        except GrokWebImagineError:
            logger.debug("Could not open Grok web reference picker before file upload", exc_info=True)

        ws = self._connect()
        try:
            document = self._send_on_ws(ws, "DOM.getDocument", {"depth": -1, "pierce": True})
            if "error" in document:
                raise GrokWebImagineError("cdp_error", str(document["error"]))
            root_node_id = (document.get("result") or {}).get("root", {}).get("nodeId")
            if not root_node_id:
                raise GrokWebImagineError("browser_dom_unavailable", "Could not inspect Grok web DOM for file upload.")

            node_ids: List[int] = []
            for attempt in range(2):
                query = self._send_on_ws(
                    ws,
                    "DOM.querySelectorAll",
                    {"nodeId": root_node_id, "selector": "input[type=file]"},
                )
                if "error" in query:
                    raise GrokWebImagineError("cdp_error", str(query["error"]))
                node_ids = (query.get("result") or {}).get("nodeIds") or []
                if node_ids:
                    break
                if attempt == 0:
                    time.sleep(0.75)
            if not node_ids:
                raise GrokWebImagineError(
                    "file_input_not_found",
                    "Could not find a Grok web file input for reference image upload.",
                )

            response = self._send_on_ws(ws, "DOM.setFileInputFiles", {"nodeId": node_ids[-1], "files": paths})
            if "error" in response:
                raise GrokWebImagineError("cdp_error", str(response["error"]))
        finally:
            ws.close()

        try:
            self.evaluate(DISPATCH_FILE_INPUT_CHANGE_JS)
        except GrokWebImagineError:
            logger.debug("Could not dispatch Grok web file input change event", exc_info=True)
        return paths

    def _wait_for_new_image(self, before: set[str], timeout_seconds: int) -> BrowserArtifact:
        deadline = time.time() + timeout_seconds
        last_media: List[Dict[str, Any]] = []
        unusable_candidate_srcs: set[str] = set()
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
                if not media_item_is_usable_image(item):
                    unusable_candidate_srcs.add(src)
                    continue
                try:
                    return self._save_image_src(src)
                except GrokWebImagineError as exc:
                    if exc.code == "artifact_extract_failed" and "image_element_not_found" in exc.message:
                        before.add(src)
                        logger.debug("Grok web image source disappeared during screenshot fallback; polling again")
                        continue
                    raise

        if unusable_candidate_srcs:
            raise GrokWebImagineError(
                "no_usable_generated_artifact",
                (
                    f"Grok web observed {len(unusable_candidate_srcs)} distinct new image candidate(s), "
                    f"but none met the minimum {MIN_USABLE_IMAGE_SIDE}px-per-side artifact gate."
                ),
            )
        raise GrokWebImagineError(
            "timeout",
            f"No new Grok web image appeared within {timeout_seconds}s; observed {len(last_media)} media nodes.",
        )

    def generate_image(
        self,
        *,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        timeout_seconds: int = 240,
        image_paths: Optional[List[str]] = None,
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

        if image_paths:
            self.attach_images(image_paths)
            time.sleep(REFERENCE_UPLOAD_SETTLE_SECONDS)
            before.update(str(item.get("src") or "") for item in self.media())

        filled = self.fill_prompt(prompt)
        if not isinstance(filled, dict) or not filled.get("filled"):
            raise GrokWebImagineError("prompt_input_not_found", "Could not find a visible Grok prompt input.")

        self.submit_prompt()

        return self._wait_for_new_image(before, timeout_seconds)

    def edit_current_image(
        self,
        *,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        timeout_seconds: int = 240,
        image_paths: Optional[List[str]] = None,
    ) -> BrowserArtifact:
        before = {str(item.get("src") or "") for item in self.media()}
        state = classify_visible_state(self.snapshot())
        if state.status != "imagine_post_open":
            raise GrokWebImagineError(
                "current_post_not_open",
                "Open a Grok Imagine result post before using edit_current.",
            )

        clicked = self.click_current_post_edit_action()
        if not clicked.get("clicked"):
            reason = str(clicked.get("reason") or "unknown")
            raise GrokWebImagineError(
                "edit_action_not_found",
                f"Could not find a visible Grok Imagine edit action on the current post ({reason}).",
            )
        time.sleep(1)

        if image_paths:
            self.attach_images(image_paths)
            time.sleep(REFERENCE_UPLOAD_SETTLE_SECONDS)
            before.update(str(item.get("src") or "") for item in self.media())

        filled = self.fill_prompt(prompt)
        if not isinstance(filled, dict) or not filled.get("filled"):
            raise GrokWebImagineError("prompt_input_not_found", "Could not find a visible Grok prompt input.")

        self.submit_prompt()
        return self._wait_for_new_image(before, timeout_seconds)

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
                try:
                    payload = self.evaluate(_src_to_data_url_js(src))
                except GrokWebImagineError:
                    payload = None
                if not isinstance(payload, dict) or not payload.get("ok"):
                    return self._save_visible_image_screenshot(src)
                path = _save_data_url(str(payload["dataUrl"]))
                return BrowserArtifact(path=path, source="browser_fetch")
            return BrowserArtifact(path=path, source="browser_url")
        raise GrokWebImagineError("unsupported_artifact_src", "Unsupported Grok web artifact source.")

    def _save_visible_image_screenshot(self, src: str) -> BrowserArtifact:
        try:
            self.evaluate(_prepare_visible_image_for_screenshot_js(src))
        except GrokWebImagineError:
            logger.debug("Could not prepare Grok image before screenshot fallback", exc_info=True)
        clip_payload = self.evaluate(_visible_image_clip_js(src))
        try:
            if not isinstance(clip_payload, dict) or not clip_payload.get("ok"):
                raise GrokWebImagineError("artifact_extract_failed", str(clip_payload))
            clip = clip_payload.get("clip")
            if not isinstance(clip, dict):
                raise GrokWebImagineError("artifact_extract_failed", f"Missing screenshot clip for {src}.")
            width = max(1.0, float(clip.get("width") or 1))
            height = max(1.0, float(clip.get("height") or 1))
            scale = max(1.0, float(clip.get("scale") or 1))
            try:
                natural_width = float(clip_payload.get("naturalWidth") or 0)
                natural_height = float(clip_payload.get("naturalHeight") or 0)
            except (TypeError, ValueError):
                natural_width = 0
                natural_height = 0
            if natural_width > 0 and natural_height > 0:
                natural_scale = min(natural_width / width, natural_height / height)
                scale = max(scale, min(MAX_SCREENSHOT_FALLBACK_SCALE, natural_scale))
            response = self._send(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "fromSurface": True,
                    "captureBeyondViewport": False,
                    "clip": {
                        "x": float(clip.get("x") or 0),
                        "y": float(clip.get("y") or 0),
                        "width": width,
                        "height": height,
                        "scale": scale,
                    },
                },
            )
            if "error" in response:
                raise GrokWebImagineError("artifact_extract_failed", str(response["error"]))
            b64 = ((response.get("result") or {}).get("data") or "").strip()
            if not b64:
                raise GrokWebImagineError("artifact_extract_failed", "CDP screenshot did not return image bytes.")
            path = save_b64_image(b64, prefix=PROVIDER_NAME.replace("-", "_"), extension="png")
            return BrowserArtifact(path=path, source="browser_screenshot")
        finally:
            try:
                self.evaluate(RESTORE_VISIBLE_IMAGE_OVERLAYS_JS)
            except GrokWebImagineError:
                logger.debug("Could not restore Grok screenshot overlays", exc_info=True)


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


def _reference_source_to_local_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise GrokWebImagineError("invalid_reference_image", "Reference image path is empty.")
    if raw.startswith(("http://", "https://")):
        raise GrokWebImagineError(
            "unsupported_reference_source",
            "The Grok web Imagine browser bridge currently supports local file reference images only.",
        )
    if raw.startswith("data:image/"):
        try:
            return str(_save_data_url(raw).resolve())
        except Exception as exc:  # noqa: BLE001
            raise GrokWebImagineError("invalid_reference_image", f"Could not materialize data URL reference image: {exc}") from exc
    if raw.startswith("file://"):
        parsed = urllib.parse.urlparse(raw)
        raw = urllib.parse.unquote(parsed.path)

    path = Path(raw).expanduser()
    if not path.is_file():
        raise GrokWebImagineError("reference_image_not_found", f"Reference image does not exist: {raw}")
    return str(path.resolve())


def _normalise_reference_image_paths(
    image_url: Optional[str],
    reference_image_urls: Optional[List[str]],
) -> List[str]:
    values: List[str] = []
    if isinstance(image_url, str) and image_url.strip():
        values.append(image_url)
    if isinstance(reference_image_urls, str):
        values.append(reference_image_urls)
    elif isinstance(reference_image_urls, (list, tuple)):
        values.extend(str(item) for item in reference_image_urls if isinstance(item, str) and item.strip())

    paths: List[str] = []
    seen: set[str] = set()
    for value in values:
        path = _reference_source_to_local_path(value)
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    if len(paths) > MAX_REFERENCE_IMAGES:
        raise GrokWebImagineError(
            "too_many_reference_images",
            f"Grok web Imagine browser bridge supports at most {MAX_REFERENCE_IMAGES} reference image(s).",
        )
    return paths


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


def _configured_imagine_url() -> str:
    cfg = _load_grok_web_config()
    value = cfg.get("imagine_url")
    return value if isinstance(value, str) and value.strip() else "https://grok.com/imagine"


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
        return {
            "modalities": ["text", "image", "image_edit"],
            "operations": ["generate", "edit_current"],
            "max_reference_images": MAX_REFERENCE_IMAGES,
        }

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
        operation = str(kwargs.get("operation") or "generate").strip().lower()
        if operation in {"edit", "modify_current", "current_post_edit"}:
            operation = "edit_current"
        if operation not in {"generate", "edit_current"}:
            return error_response(
                error="Grok web Imagine supports operation='generate' or operation='edit_current'.",
                error_type="unsupported_operation",
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )
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
        try:
            reference_image_paths = _normalise_reference_image_paths(image_url, reference_image_urls)
        except GrokWebImagineError as exc:
            return error_response(
                error=f"{exc.message} Provide local file paths for browser bridge uploads.",
                error_type=exc.code,
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        client = self._client()
        try:
            state = classify_visible_state(client.snapshot())
            if state.status == "imagine_post_open" and operation != "edit_current":
                client.navigate(_configured_imagine_url())
                time.sleep(2)
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

        if operation == "edit_current" and state.status != "imagine_post_open":
            return error_response(
                error="Open a Grok Imagine result post before using operation='edit_current'.",
                error_type="current_post_not_open",
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        if operation != "edit_current" and not state.safe_to_submit:
            return error_response(
                error=f"{state.message} Open the debug Chrome window and complete the setup before retrying.",
                error_type=state.status,
                provider=PROVIDER_NAME,
                model=MODEL_ID,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            generate_kwargs: Dict[str, Any] = {
                "prompt": prompt,
                "aspect_ratio": aspect,
                "timeout_seconds": int(kwargs.get("timeout_seconds") or 240),
            }
            if reference_image_paths:
                generate_kwargs["image_paths"] = reference_image_paths
            if operation == "edit_current":
                artifact = client.edit_current_image(**generate_kwargs)
            else:
                artifact = client.generate_image(**generate_kwargs)
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
            modality="image_edit" if operation == "edit_current" else ("image" if reference_image_paths else "text"),
            extra={
                "provider_family": "grok_web",
                "quota_source": "consumer_web",
                "artifact_source": artifact.source,
                "reference_image_count": len(reference_image_paths),
                "operation": operation,
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
        try:
            state = classify_visible_state(client.snapshot())
        except GrokWebImagineError as exc:
            state = VisibleState(status=exc.code, safe_to_submit=False, message=exc.message)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            state = _cdp_unreachable_state(exc)
        print(json.dumps(_state_payload(state), ensure_ascii=False, indent=2))
        return 0 if state.safe_to_submit else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
