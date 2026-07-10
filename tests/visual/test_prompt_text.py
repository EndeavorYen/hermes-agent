from __future__ import annotations

from agent.visual.prompt_text import build_provider_facing_visual_prompt


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
