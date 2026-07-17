from __future__ import annotations

from agent.visual.prompt_text import (
    build_provider_facing_visual_prompt,
    strip_visual_prompt_metadata,
    strip_visual_runtime_metadata,
)


def test_runtime_metadata_strip_preserves_thread_contract_but_drops_injected_context():
    prompt = '''[Replying to: "故事影片 parent"]

[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] simon: 請製作一部故事影片
[End of thread context]

以 G1 和 G4 為主要參考，幫我換個背景

Raphael State Observer (ephemeral, internal):
task_state: casual_or_direct

Visual Arsenal default for Slack image work:
- Example mentions G2 and G3 and story-video workflow.
'''

    runtime_text = strip_visual_runtime_metadata(prompt)
    provider_text = strip_visual_prompt_metadata(prompt)

    assert "[thread parent] simon: 請製作一部故事影片" in runtime_text
    assert "以 G1 和 G4 為主要參考" in runtime_text
    assert "Raphael State Observer" not in runtime_text
    assert provider_text == "以 G1 和 G4 為主要參考，幫我換個背景"


def test_provider_facing_prompt_strips_agent_context_blocks_but_keeps_current_intent():
    prompt = """Provider-ready visual prompt:
Objective: [Replying to: "請使用 grok-web-imagine provider / Grok Web Imagine + reference 固定這位角色，產出不同姿勢候選並選最佳，只交付最佳圖片。"]

[Thread context — prior messages in this thread (not yet in conversation history):]

[thread parent] simon: 請使用 grok-web-imagine provider / Grok Web Imagine + reference 固定這位角色，產出不同姿勢候選並選最佳，只交付最佳圖片。

[End of thread context]

可不可以再嘗試不同的構圖，可以類似原 ref 的構圖進行調整和優化

Session visual context:

- attachment 1: visual_reference reference; preserve its role only when relevant.

Reference policy for unassigned uploaded images:

- Treat all attached images as an unassigned collective reference set.

Quality target: polished high-quality final image, beautiful subject rendering.

Provider reference image ordering for generation:

- provider images 1-3 form an unassigned collective identity/style reference set.
When provider image ordering and user ref labels differ, user ref labels keep their original visible upload order.
"""

    provider_prompt = build_provider_facing_visual_prompt(prompt)

    assert provider_prompt.startswith("可不可以再嘗試不同的構圖")
    assert "Quality: polished high-quality final image, beautiful subject rendering." in provider_prompt
    assert "Provider-ready visual prompt" not in provider_prompt
    assert "Objective:" not in provider_prompt
    assert "[Replying to:" not in provider_prompt
    assert "[Thread context" not in provider_prompt
    assert "[thread parent]" not in provider_prompt
    assert "Session visual context" not in provider_prompt
    assert "Reference policy for unassigned uploaded images" not in provider_prompt
    assert "Provider reference image ordering" not in provider_prompt


def test_provider_facing_prompt_keeps_explicit_role_mapping_as_natural_instruction():
    prompt = """Provider-ready visual prompt:
Objective: 把 ref 1 的角色，套用 ref2 的姿勢，產出圖片即可

Reference mapping from the user's visible upload order:
- ref 1 = character_identity
- ref 2 = pose_composition

Role constraints:
- ref 1: preserve character identity, face, hair, silhouette, signature outfit, accessories, and palette.
- ref 2: use only pose, body orientation, limb placement, camera angle, framing, composition, and scene layout.
- Do not copy identity, face, hair, wardrobe, color palette, or styling from pose refs.

Negative constraints: no malformed anatomy, no duplicated limbs.
"""

    provider_prompt = build_provider_facing_visual_prompt(prompt)

    assert provider_prompt.startswith("把 ref 1 的角色")
    assert "Reference use: ref 1 = character_identity; ref 2 = pose_composition" in provider_prompt
    assert "Role constraints: ref 1: preserve character identity" in provider_prompt
    assert "Negative: no malformed anatomy, no duplicated limbs." in provider_prompt
    assert "Reference mapping from the user's visible upload order" not in provider_prompt
    assert "Provider-ready visual prompt" not in provider_prompt


def test_provider_facing_prompt_removes_internal_quality_dimension_labels():
    prompt = (
        "動漫圖，性感一些\n\n"
        "First-pass visual quality guidance: anime illustration polish, clean expressive facial features. "
        "Dimension-specific quality guidance: subject_beauty: improve stylized attractiveness; "
        "fashion_material_quality: improve wardrobe texture."
    )

    provider_prompt = build_provider_facing_visual_prompt(prompt)

    assert "Quality: anime illustration polish" in provider_prompt
    assert "Additional quality refinements: improve stylized attractiveness" in provider_prompt
    assert "Dimension-specific quality guidance" not in provider_prompt
    assert "subject_beauty:" not in provider_prompt
    assert "fashion_material_quality:" not in provider_prompt


def test_xai_photoreal_request_prevents_child_audience_from_cartoonizing_style():
    prompt = (
        "適合五歲兒童的寫實自然史紀錄片畫面：剛破殼的幼龍踏出第一步，"
        "成年恐龍在雨中保護牠。"
    )

    provider_prompt = build_provider_facing_visual_prompt(
        prompt,
        provider="xai",
        request_category="educational",
    )

    assert "Audience age affects emotional clarity only" in provider_prompt
    assert "physically plausible anatomy and natural proportions" in provider_prompt
    assert "not illustration, animation, mascot, or oversized cute eyes" in provider_prompt


def test_xai_stylized_request_does_not_receive_photorealism_guardrail():
    provider_prompt = build_provider_facing_visual_prompt(
        "適合五歲兒童的可愛卡通幼龍動畫插圖。",
        provider="xai",
        request_category="anime",
    )

    assert "Audience age affects emotional clarity only" not in provider_prompt


def test_xai_negated_stylized_terms_keep_photorealism_guardrail():
    provider_prompt = build_provider_facing_visual_prompt(
        "Photoreal nature documentary for children; no cartoon or illustration; 不要卡通或動畫。",
        provider="xai",
        request_category="educational",
    )

    assert "Audience age affects emotional clarity only" in provider_prompt


def test_xai_unrelated_negation_does_not_hide_explicit_stylized_intent():
    provider_prompt = build_provider_facing_visual_prompt(
        "Photoreal lighting, not gloomy but use cartoon illustration; 寫實光影，不是陰暗而是卡通動畫。",
        provider="xai",
        request_category="anime",
    )

    assert "Audience age affects emotional clarity only" not in provider_prompt
