from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


def _text(value: Any) -> str:
    return str(value or "").strip()


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    width, height = size
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height)).convert("RGBA")


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc")
        if bold
        else Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise ValueError("no CJK-safe release-art font found")


def _shade(canvas: Image.Image, *, left: bool = True, bottom: bool = True) -> None:
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if left:
        extent = int(canvas.width * 0.68)
        for x in range(extent):
            alpha = round(178 * (1 - x / max(1, extent - 1)) ** 1.8)
            draw.line((x, 0, x, canvas.height), fill=(4, 8, 12, alpha))
    if bottom:
        start = int(canvas.height * 0.48)
        for y in range(start, canvas.height):
            progress = (y - start) / max(1, canvas.height - start - 1)
            draw.line((0, y, canvas.width, y), fill=(2, 5, 8, round(150 * progress)))
    canvas.alpha_composite(overlay)


def _fit_title(
    draw: ImageDraw.ImageDraw,
    title: str,
    *,
    max_width: int,
    preferred_size: int,
    minimum_size: int,
) -> ImageFont.FreeTypeFont:
    for size in range(preferred_size, minimum_size - 1, -2):
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), title, font=font, stroke_width=2)
        if box[2] - box[0] <= max_width:
            return font
    return _font(minimum_size, bold=True)


def _draw_identity(
    canvas: Image.Image,
    *,
    title: str,
    subtitle: str,
    thumbnail: bool,
) -> None:
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    margin = round(width * 0.055)
    title_y = round(height * (0.59 if thumbnail else 0.63))
    eyebrow_font = _font(max(22, round(height * 0.032)), bold=True)
    subtitle_font = _font(max(24, round(height * 0.034)))
    title_font = _fit_title(
        draw,
        title,
        max_width=round(width * 0.78),
        preferred_size=round(height * (0.145 if thumbnail else 0.13)),
        minimum_size=round(height * 0.075),
    )
    accent = (255, 196, 59, 255)
    draw.rounded_rectangle(
        (
            margin,
            title_y - round(height * 0.075),
            margin + round(width * 0.075),
            title_y - round(height * 0.064),
        ),
        radius=3,
        fill=accent,
    )
    draw.text(
        (margin, title_y - round(height * 0.055)),
        "故事專題",
        font=eyebrow_font,
        fill=(244, 245, 242, 245),
        stroke_width=1,
        stroke_fill=(0, 0, 0, 180),
    )
    draw.text(
        (margin, title_y),
        title,
        font=title_font,
        fill=(255, 255, 255, 255),
        stroke_width=max(2, round(height * 0.004)),
        stroke_fill=(0, 0, 0, 230),
    )
    if subtitle:
        title_box = draw.textbbox((margin, title_y), title, font=title_font)
        subtitle_y = min(
            height - round(height * 0.11), title_box[3] + round(height * 0.026)
        )
        draw.text(
            (margin, subtitle_y),
            subtitle,
            font=subtitle_font,
            fill=(239, 241, 237, 245),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 215),
        )


def compile_release_art_brief(topic: str, ledger: dict[str, Any]) -> dict[str, str]:
    shots: list[dict[str, Any]] = []
    for scene in ledger.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        shots.extend(
            shot for shot in scene.get("shots") or [] if isinstance(shot, dict)
        )
    first_shot = shots[0] if shots else {}

    def hero_score(shot: dict[str, Any]) -> int:
        role = _text(shot.get("engagement_role")).lower()
        energy = _text(shot.get("composition_energy")).lower()
        scale = _text(shot.get("shot_scale")).lower()
        score = {
            "payoff": 5,
            "reveal": 4,
            "hook": 3,
            "reaction": 2,
            "build": 1,
        }.get(role, 0)
        score += {"kinetic": 4, "awe": 4, "tense": 2, "curious": 1}.get(energy, 0)
        score += 2 if scale in {"medium", "close_up", "wide"} else 0
        score += 1 if _text(shot.get("action")) else 0
        score += 1 if _text(shot.get("story_moment")) else 0
        searchable = " ".join(_text(value).lower() for value in shot.values())
        subject_text = _text(shot.get("subject")).lower()
        if "恐龍" in subject_text or "dinosaur" in subject_text:
            score += 10
        elif "恐龍" in searchable or "dinosaur" in searchable:
            score += 1
        truth_mode = _text(shot.get("visual_truth_mode")).lower()
        score += (
            3
            if truth_mode in {"reconstruction", "mixed_evidence_reconstruction"}
            else 0
        )
        score -= 8 if truth_mode == "comparison" else 0
        if any(
            marker in searchable
            for marker in (
                "博物館",
                "實驗室",
                "演示裝置",
                "標本桌",
                "museum",
                "laboratory",
                "demonstration device",
            )
        ):
            score -= 6
        evidence_markers = (
            "化石",
            "研究員",
            "骨骼",
            "標本",
            "fossil",
            "researcher",
            "specimen",
        )
        if any(
            marker in searchable and marker not in topic.lower()
            for marker in evidence_markers
        ):
            score -= 5
        return score

    hero_shot = max(shots, key=hero_score) if shots else first_shot
    takeaway = _text(first_shot.get("viewer_takeaway"))
    subject = _text(hero_shot.get("subject")) or topic
    action = _text(hero_shot.get("action"))
    story_moment = _text(hero_shot.get("story_moment"))
    style = _text(ledger.get("visual_style")) or "cinematic factual reconstruction"
    prompt = " ".join((
        f"Create a premium 16:9 cinematic hero image for a story video titled {topic}.",
        f"Hero subject: {subject}.",
        f"Hero action: {action}." if action else "",
        f"Decisive instant: {story_moment}." if story_moment else "",
        f"Core audience promise: {takeaway or 'a surprising, visually immediate discovery'}.",
        "Build one coherent scene with a dominant hero subject, a bold foreground clue, readable midground action, and atmospheric background scale.",
        "Use a decisive story instant, dramatic low or intimate camera placement, motivated high-contrast light, volumetric atmosphere, selective depth of field, and strong leading lines.",
        "Controlled exaggeration of perspective, lighting, particles, weather, and scale is welcome, while factual anatomy, evidence, time period, and causal meaning remain credible.",
        f"Visual direction: {style}, premium theatrical color separation, emotionally inviting for a curious general audience.",
        "Avoid empty landscapes, museum-catalog staging, generic documentary stock photography, passive centered subjects, collages, grids, and infographic layouts.",
        "No generated text, title, caption, label, logo, border, or watermark; typography will be composed locally.",
    ))
    return {
        "prompt": prompt,
        "title": topic,
        "subtitle": takeaway[:38] if takeaway else "從一個線索，看見完整故事",
    }


def compose_release_art(
    *,
    source: Path,
    output_dir: Path,
    title: str,
    subtitle: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        hero = opened.convert("RGB")
    hero_source = output_dir / "hero_source.png"
    hero.save(hero_source, "PNG", optimize=True)

    opening = _cover(hero, (1920, 1080))
    opening = ImageEnhance.Contrast(opening).enhance(1.08)
    _shade(opening)
    _draw_identity(opening, title=title, subtitle=subtitle, thumbnail=False)
    opening_path = output_dir / "opening_card.png"
    opening.convert("RGB").save(opening_path, "PNG", optimize=True)

    thumbnail = _cover(hero, (1280, 720))
    thumbnail = ImageEnhance.Color(thumbnail).enhance(1.08)
    thumbnail = ImageEnhance.Contrast(thumbnail).enhance(1.12)
    _shade(thumbnail)
    _draw_identity(thumbnail, title=title, subtitle=subtitle, thumbnail=True)
    thumbnail_path = output_dir / "thumbnail.jpg"
    thumbnail.convert("RGB").save(thumbnail_path, "JPEG", quality=94, optimize=True)

    ending = _cover(hero, (1920, 1080)).filter(ImageFilter.GaussianBlur(7))
    ending = ImageEnhance.Brightness(ending).enhance(0.42)
    draw = ImageDraw.Draw(ending)
    heading_font = _fit_title(
        draw,
        "探索仍在繼續",
        max_width=1400,
        preferred_size=108,
        minimum_size=72,
    )
    subtitle_font = _font(42)
    heading_box = draw.textbbox((0, 0), "探索仍在繼續", font=heading_font)
    x = (1920 - (heading_box[2] - heading_box[0])) // 2
    draw.text(
        (x, 430),
        "探索仍在繼續",
        font=heading_font,
        fill="white",
        stroke_width=3,
        stroke_fill=(0, 0, 0, 220),
    )
    topic_box = draw.textbbox((0, 0), title, font=subtitle_font)
    draw.text(
        ((1920 - (topic_box[2] - topic_box[0])) // 2, 575),
        title,
        font=subtitle_font,
        fill=(238, 239, 235),
    )
    ending_path = output_dir / "ending_card.png"
    ending.convert("RGB").save(ending_path, "PNG", optimize=True)

    return {
        "hero_source": hero_source,
        "opening_card": opening_path,
        "ending_card": ending_path,
        "thumbnail": thumbnail_path,
    }


__all__ = ["compile_release_art_brief", "compose_release_art"]
