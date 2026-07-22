"""
Tests for MEDIA tag extraction from tool results.

Verifies that MEDIA tags (e.g., from TTS tool) are only extracted from
messages in the CURRENT turn, not from the full conversation history.
This prevents voice messages from accumulating and being sent multiple
times per reply. (Regression test for #160)

Also covers #34608: a stale MEDIA: path emitted by an execute_code /
make_image tool several turns earlier must not leak onto a later
text-only reply, even when the path-based dedup set fails to capture it.
"""

import json
import os
import re

import pytest


def extract_media_tags_fixed(result_messages, history_len):
    """
    Extract MEDIA tags from tool results, but ONLY from new messages
    (those added after history_len). This is the fixed behavior.
    
    Args:
        result_messages: Full list of messages including history + new
        history_len: Length of history before this turn
        
    Returns:
        Tuple of (media_tags list, has_voice_directive bool)
    """
    media_tags = []
    has_voice_directive = False
    
    # Only process new messages from this turn
    new_messages = result_messages[history_len:] if len(result_messages) > history_len else []
    
    for msg in new_messages:
        if msg.get("role") == "tool" or msg.get("role") == "function":
            content = msg.get("content", "")
            if "MEDIA:" in content:
                for match in re.finditer(r'MEDIA:(\S+)', content):
                    path = match.group(1).strip().rstrip('",}')
                    if path:
                        media_tags.append(f"MEDIA:{path}")
                if "[[audio_as_voice]]" in content:
                    has_voice_directive = True
    
    return media_tags, has_voice_directive


def extract_media_tags_production(result_messages, history_len, history_media_paths):
    """Mirror of the production scan in gateway/run.py after the #34608 fix.

    Primary guard: scope the scan to the current turn via ``history_len``
    slicing (matching how ``agent_history`` is passed as
    ``conversation_history`` into ``run_conversation``). Secondary guard:
    path-based dedup against ``history_media_paths`` (the #160 compression-safe
    fallback, also used when compression shrinks the list below history_len).
    """
    media_tags = []
    has_voice_directive = False

    if len(result_messages) >= history_len and history_len:
        scan_msgs = result_messages[history_len:]
    else:
        scan_msgs = result_messages

    for msg in scan_msgs:
        if msg.get("role") == "tool" or msg.get("role") == "function":
            content = msg.get("content", "")
            if "MEDIA:" in content:
                for match in re.finditer(r'MEDIA:(\S+)', content):
                    path = match.group(1).strip().rstrip('",}')
                    if path and path not in history_media_paths:
                        media_tags.append(f"MEDIA:{path}")
                if "[[audio_as_voice]]" in content:
                    has_voice_directive = True

    return media_tags, has_voice_directive


def extract_media_tags_broken(result_messages):
    """
    The BROKEN behavior: extract MEDIA tags from ALL messages including history.
    This causes TTS voice messages to accumulate and be re-sent on every reply.
    """
    media_tags = []
    has_voice_directive = False
    
    for msg in result_messages:
        if msg.get("role") == "tool" or msg.get("role") == "function":
            content = msg.get("content", "")
            if "MEDIA:" in content:
                for match in re.finditer(r'MEDIA:(\S+)', content):
                    path = match.group(1).strip().rstrip('",}')
                    if path:
                        media_tags.append(f"MEDIA:{path}")
                if "[[audio_as_voice]]" in content:
                    has_voice_directive = True
    
    return media_tags, has_voice_directive


class TestMediaExtraction:
    """Tests for MEDIA tag extraction from tool results."""

    def test_gateway_auto_append_ignores_media_examples_in_skill_docs(self):
        """Skill/documentation examples must not be appended as real attachments."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "How should I format gateway media?"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_skill", "function": {"name": "skill_view"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_skill",
                "content": """
Recommended pattern:
```text
MEDIA:/absolute/path/to/image.png
```
Second message:
```text
caption
```
""",
            },
            {"role": "assistant", "content": "Use a standalone media message."},
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)
        assert tags == []
        assert voice is False

    def test_gateway_auto_append_keeps_real_tts_media_tag(self):
        """TTS tool media tags are still auto-appended when the model omits them."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "Say this as audio"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_tts", "function": {"name": "text_to_speech"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_tts",
                "content": '{"success": true, "media_tag": "[[audio_as_voice]]\\nMEDIA:/tmp/voice.ogg"}',
            },
            {"role": "assistant", "content": "Done."},
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)
        assert tags == ["MEDIA:/tmp/voice.ogg"]
        assert voice is True

    def test_gateway_auto_append_story_video_completed_mp4(self, tmp_path):
        from gateway.run import _collect_auto_append_media_tags

        video = tmp_path / "final.mp4"
        video.write_bytes(b"mp4")
        messages = [
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_story_video",
                    "function": {"name": "story_video_audio_director"},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_story_video",
                "content": (
                    '{"success": true, "action": "production_status", '
                    f'"media": ["MEDIA:{video}"]}}'
                ),
            },
            {"role": "assistant", "content": "影片完成。"},
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)

        assert tags == [f"MEDIA:{video}"]
        assert voice is False

    @pytest.mark.parametrize(
        "payload",
        [
            '{"success": false, "action": "production_status", "media": ["MEDIA:{path}"]}',
            '{"success": true, "action": "status", "media": ["MEDIA:{path}"]}',
            '{"success": true, "action": "production_status", "media": ["MEDIA:{path}.wav"]}',
            '{"success": true, "action": "production_status", "media": ["MEDIA:{missing}"]}',
        ],
    )
    def test_gateway_auto_append_story_video_rejects_non_deliverables(
        self, tmp_path, payload
    ):
        from gateway.run import _collect_auto_append_media_tags

        video = tmp_path / "final.mp4"
        video.write_bytes(b"mp4")
        content = payload.replace("{path}", str(video)).replace(
            "{missing}", str(tmp_path / "missing.mp4")
        )
        messages = [
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_story_video",
                    "function": {"name": "story_video_audio_director"},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_story_video",
                "content": content,
            },
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)

        assert tags == []
        assert voice is False

    def test_gateway_auto_append_image_generate_json_path(self):
        """image_generate returns a local path in JSON (no MEDIA: tag); it is
        auto-appended so delivery doesn't depend on the model restating it."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "Make me a cat"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_img", "function": {"name": "image_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_img",
                "content": '{"success": true, "image": "/tmp/gen/cat.png", "agent_visible_image": "/tmp/gen/cat.png"}',
            },
            {"role": "assistant", "content": "Here's your cat."},
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)
        assert tags == ["MEDIA:/tmp/gen/cat.png"]
        assert voice is False

    def test_gateway_auto_append_image_generate_prefers_host_path(self):
        """When host and sandbox paths differ, the host-deliverable path wins."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "Make me a dog"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_img", "function": {"name": "image_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_img",
                "content": '{"success": true, "host_image": "/host/dog.jpg", "image": "/host/dog.jpg", "agent_visible_image": "/sandbox/dog.jpg"}',
            },
        ]

        tags, _ = _collect_auto_append_media_tags(messages, history_offset=0)
        assert tags == ["MEDIA:/host/dog.jpg"]

    def test_gateway_auto_append_image_generate_failure_and_url_ignored(self):
        """Failed generations and remote URLs are not auto-delivered."""
        from gateway.run import _collect_auto_append_media_tags

        def _img_msgs(content):
            return [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": "c", "function": {"name": "image_generate"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "c", "content": content},
            ]

        # Failed generation
        tags, _ = _collect_auto_append_media_tags(
            _img_msgs('{"success": false, "image": null, "error": "boom"}'),
            history_offset=0,
        )
        assert tags == []

        # Remote URL is not a local file path
        tags, _ = _collect_auto_append_media_tags(
            _img_msgs('{"success": true, "image": "https://fal.media/x/cat.png"}'),
            history_offset=0,
        )
        assert tags == []

    def test_gateway_auto_append_image_generate_dedupes_history(self):
        """A generated image path already in history is not re-sent."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c", "function": {"name": "image_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c",
                "content": '{"success": true, "image": "/tmp/gen/cat.png"}',
            },
        ]

        tags, _ = _collect_auto_append_media_tags(
            messages, history_offset=0, history_media_paths={"/tmp/gen/cat.png"}
        )
        assert tags == []

    def test_gateway_auto_append_visual_package_selected_media_only(self):
        """visual_package_generate JSON only appends selected current artifacts."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "Make image and video"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_visual", "function": {"name": "visual_package_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_1", '
                    '"images": ["/tmp/current.png"], "videos": ["/tmp/current.mp4"], '
                    '"delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["var_img", "var_vid"], '
                    '"visual_artifacts": {'
                    '"/tmp/current.png": {"request_id": "vrq_1", "artifact_id": "var_img", "kind": "image"}, '
                    '"/tmp/old.png": {"request_id": "vrq_old", "artifact_id": "var_old", "kind": "image"}, '
                    '"/tmp/current.mp4": {"request_id": "vrq_1", "artifact_id": "var_vid", "kind": "video"}'
                    "}}}"
                ),
            },
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)

        assert tags == ["MEDIA:/tmp/current.png", "MEDIA:/tmp/current.mp4"]
        assert voice is False

    def test_gateway_auto_append_partial_visual_package_qualified_media(self):
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "Make four candidates"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_visual", "function": {"name": "visual_package_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": json.dumps(
                    {
                        "success": True,
                        "package_status": "partial",
                        "error_type": "candidate_option_shortfall",
                        "visual_request_id": "vrq_partial",
                        "images": ["/tmp/qualified.png"],
                        "videos": [],
                        "delivery_metadata": {
                            "selected_visual_artifact_ids": ["var_qualified"],
                            "visual_artifacts": {
                                "/tmp/qualified.png": {
                                    "request_id": "vrq_partial",
                                    "artifact_id": "var_qualified",
                                    "kind": "image",
                                }
                            },
                        },
                    }
                ),
            },
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)

        assert tags == ["MEDIA:/tmp/qualified.png"]
        assert voice is False

    def test_gateway_auto_append_visual_agent_video_only_skips_source_image(self):
        """visual_agent_generate video-only output skips internal source images."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "請產生一段 6 秒影片"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_visual_agent", "function": {"name": "visual_agent_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual_agent",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_2", '
                    '"images": [], "videos": ["/tmp/current.mp4"], '
                    '"delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["var_vid"], '
                    '"visual_artifacts": {'
                    '"/tmp/internal-source.png": {"request_id": "vrq_2", "artifact_id": "var_img", "kind": "image"}, '
                    '"/tmp/current.mp4": {"request_id": "vrq_2", "artifact_id": "var_vid", "kind": "video"}'
                    "}}}"
                ),
            },
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)

        assert tags == ["MEDIA:/tmp/current.mp4"]
        assert voice is False

    def test_gateway_auto_append_visual_package_dedupes_file_uri_variant(self):
        """visual_package_generate should not append path and file:// variants twice."""
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {"role": "user", "content": "Make a video"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_visual", "function": {"name": "visual_package_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_3", '
                    '"images": [], "videos": ["/tmp/current.mp4"], '
                    '"delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["var_vid"], '
                    '"visual_artifacts": {'
                    '"/tmp/current.mp4": {"request_id": "vrq_3", "artifact_id": "var_vid", "kind": "video"}, '
                    '"file:///tmp/current.mp4": {"request_id": "vrq_3", "artifact_id": "var_vid", "kind": "video"}'
                    "}}}"
                ),
            },
        ]

        tags, voice = _collect_auto_append_media_tags(messages, history_offset=0)

        assert tags == ["MEDIA:/tmp/current.mp4"]
        assert voice is False

    def test_visual_media_tag_cannot_bypass_selected_manifest(self):
        from gateway.run import _collect_auto_append_media_tags

        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_visual",
                        "function": {"name": "visual_package_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_current", '
                    '"images": ["/tmp/selected.png"], "videos": [], '
                    '"diagnostic": "MEDIA:/tmp/rejected.png", '
                    '"delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["selected"], '
                    '"visual_artifacts": {'
                    '"/tmp/selected.png": {'
                    '"request_id": "vrq_current", "artifact_id": "selected", '
                    '"kind": "image"}, '
                    '"/tmp/rejected.png": {'
                    '"request_id": "vrq_current", "artifact_id": "rejected", '
                    '"kind": "image"}}}}'
                ),
            },
        ]

        tags, _ = _collect_auto_append_media_tags(messages, history_offset=0)

        assert tags == ["MEDIA:/tmp/selected.png"]

    def test_visual_manifest_rejects_selected_artifact_from_other_request(self):
        from gateway.run import _collect_current_turn_delivery_media_paths

        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_visual",
                        "function": {"name": "visual_package_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_current", '
                    '"images": ["/tmp/old.png"], "videos": [], '
                    '"delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["old"], '
                    '"visual_artifacts": {"/tmp/old.png": {'
                    '"request_id": "vrq_old", "artifact_id": "old", '
                    '"kind": "image"}}}}'
                ),
            },
        ]

        assert _collect_current_turn_delivery_media_paths(messages) == set()

    def test_visual_delivery_dedupe_scopes_identity_to_session_thread(self):
        from agent.visual.delivery_dedupe import get_artifact_delivery_deduper
        from gateway.run import _collect_current_turn_delivery_media_paths

        get_artifact_delivery_deduper()._seen.clear()
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_visual",
                        "function": {"name": "visual_package_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_1", '
                    '"images": ["/tmp/alias-a.png"], "videos": [], '
                    '"delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["selected"], '
                    '"visual_artifacts": {"/tmp/alias-a.png": {'
                    '"request_id": "vrq_1", "artifact_id": "selected", '
                    '"content_hash": "sha256:same", "kind": "image"}}}}'
                ),
            },
        ]

        first = _collect_current_turn_delivery_media_paths(
            messages,
            delivery_destination="slack:session-1:thread-1",
        )
        duplicate = _collect_current_turn_delivery_media_paths(
            messages,
            delivery_destination="slack:session-1:thread-1",
        )
        other_thread = _collect_current_turn_delivery_media_paths(
            messages,
            delivery_destination="slack:session-1:thread-2",
        )

        assert "/tmp/alias-a.png" in first
        assert duplicate == set()
        assert "/tmp/alias-a.png" in other_thread

    def test_reused_path_with_new_artifact_identity_is_current(self):
        from gateway.run import (
            _collect_current_turn_delivery_media_paths,
            _visual_delivery_history_key,
        )

        path = "/tmp/reused-output.png"
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_visual",
                        "function": {"name": "visual_package_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_new", '
                    '"images": ["'
                    + path
                    + '"], "videos": [], "delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["new"], '
                    '"visual_artifacts": {"'
                    + path
                    + '": {"request_id": "vrq_new", "artifact_id": "new", '
                    '"content_hash": "sha256:new", "kind": "image"}}}}'
                ),
            },
        ]

        current = _collect_current_turn_delivery_media_paths(
            messages,
            history_media_paths={path},
            history_media_identities={
                _visual_delivery_history_key("vrq_old", "sha256:old")
            },
        )

        assert path in current

    def test_auto_append_allows_reused_path_with_new_artifact_identity(self):
        from gateway.run import (
            _collect_auto_append_media_tags,
            _visual_delivery_history_key,
        )

        path = "/tmp/reused-auto-append.png"
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_visual",
                        "function": {"name": "visual_package_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_new", '
                    '"images": ["'
                    + path
                    + '"], "videos": [], "delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["new"], '
                    '"visual_artifacts": {"'
                    + path
                    + '": {"request_id": "vrq_new", "artifact_id": "new", '
                    '"content_hash": "sha256:new", "kind": "image"}}}}'
                ),
            },
        ]

        tags, _ = _collect_auto_append_media_tags(
            messages,
            history_media_paths={path},
            history_media_identities={
                _visual_delivery_history_key("vrq_old", "sha256:old")
            },
        )

        assert tags == [f"MEDIA:{path}"]

    def test_same_identity_is_allowed_for_a_new_visual_request(self):
        from gateway.run import (
            _collect_current_turn_delivery_media_paths,
            _visual_delivery_history_key,
        )

        path = "/tmp/same-content-new-request.png"
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_visual",
                        "function": {"name": "visual_package_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "visual_request_id": "vrq_new", '
                    '"images": ["'
                    + path
                    + '"], "videos": [], "delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["new"], '
                    '"visual_artifacts": {"'
                    + path
                    + '": {"request_id": "vrq_new", "artifact_id": "new", '
                    '"content_hash": "sha256:same", "kind": "image"}}}}'
                ),
            },
        ]

        current = _collect_current_turn_delivery_media_paths(
            messages,
            history_media_paths={path},
            history_media_identities={
                _visual_delivery_history_key("vrq_old", "sha256:same")
            },
        )

        assert path in current

    def test_collect_history_media_paths_includes_image_generate_json(self):
        """Regression for #46627: the history media-path collector must pick up
        image_generate JSON-payload paths (no MEDIA: tag), not just MEDIA:
        text tags. Otherwise, after a compression boundary the auto-append
        fallback rescans full history, finds the generated path absent from
        the dedup set, and re-emits the same MEDIA tag every turn.
        """
        from gateway.run import _collect_history_media_paths

        history = [
            {"role": "user", "content": "make a cat"},
            {
                "role": "assistant",
                "tool_calls": [{"id": "c", "function": {"name": "image_generate"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "c",
                "content": '{"success": true, "image": "/tmp/gen/cat.png"}',
            },
            # A separate MEDIA: text tag from another tool, to confirm both shapes.
            {
                "role": "tool",
                "tool_call_id": "d",
                "content": "Saved MEDIA:/tmp/voice/note.ogg done",
            },
        ]
        paths = _collect_history_media_paths(history)
        assert "/tmp/gen/cat.png" in paths  # JSON-payload path (the bug)
        assert "/tmp/voice/note.ogg" in paths  # MEDIA: text path (already worked)

    def test_collect_history_media_paths_includes_visual_package_selected_artifacts(self):
        """History dedup must include selected visual_package artifacts."""
        from gateway.run import _collect_history_media_paths

        history = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_visual", "function": {"name": "visual_package_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "images": ["/tmp/selected.png"], '
                    '"videos": [], "delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["var_selected"], '
                    '"visual_artifacts": {'
                    '"/tmp/selected.png": {"artifact_id": "var_selected", "kind": "image"}, '
                    '"/tmp/rejected.png": {"artifact_id": "var_rejected", "kind": "image"}'
                    "}}}"
                ),
            },
        ]

        paths = _collect_history_media_paths(history)

        assert "/tmp/selected.png" in paths
        assert "/tmp/rejected.png" not in paths

    def test_image_generate_not_reemitted_after_compression(self):
        """End-to-end of the #46627 fix: collect history paths, then the
        compression-fallback rescan (history_offset stale) must dedup the
        generated image against them — no re-emission."""
        from gateway.run import (
            _collect_auto_append_media_tags,
            _collect_history_media_paths,
        )

        history = [
            {
                "role": "assistant",
                "tool_calls": [{"id": "c", "function": {"name": "image_generate"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "c",
                "content": '{"success": true, "image": "/tmp/gen/dog.png"}',
            },
        ]
        history_paths = _collect_history_media_paths(history)

        # Simulate the post-compression fallback: history_offset is stale
        # (larger than the shrunken message list), so the collector rescans
        # the full list. With the dedup set populated, the already-delivered
        # image must NOT be re-emitted.
        tags, _ = _collect_auto_append_media_tags(
            history, history_offset=9999, history_media_paths=history_paths
        )
        assert tags == [], f"generated image re-emitted after compression: {tags}"

    def test_response_media_filter_drops_prior_visual_artifact_paths(self):
        """Final-answer MEDIA paths must not re-deliver old visual artifacts.

        Regression for Slack visual threads where the model called only
        visual_arsenal_review_inbox, then placed four previous generated
        images in its final response. Those paths are real files and pass the
        platform safety filter, but they are not current-turn artifacts.
        """
        from gateway.run import _filter_response_media_refs_to_current_turn

        stale = "/tmp/hermes-test/visual-arsenal/library/assets/old-a.png"
        filtered = _filter_response_media_refs_to_current_turn(
            [(stale, False)],
            current_turn_media_paths=set(),
            history_media_paths={stale},
            turn_started_at=None,
        )

        assert filtered == []

    def test_response_media_filter_drops_fresh_unselected_managed_visual(
        self,
        tmp_path,
        monkeypatch,
    ):
        from gateway.run import _filter_response_media_refs_to_current_turn

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        rejected = tmp_path / "media" / "generated" / "rejected.png"
        rejected.parent.mkdir(parents=True)
        rejected.write_bytes(b"\x89PNG\r\n\x1a\n")

        filtered = _filter_response_media_refs_to_current_turn(
            [(str(rejected), False)],
            current_turn_media_paths=set(),
            history_media_paths=set(),
            turn_started_at=0,
        )

        assert filtered == []

    def test_response_media_filter_keeps_current_visual_package_artifact(self):
        """Final-answer MEDIA paths stay deliverable when the current turn made them."""
        from gateway.run import (
            _collect_current_turn_delivery_media_paths,
            _filter_response_media_refs_to_current_turn,
        )

        current = "/tmp/hermes-test/visual-arsenal/library/assets/current.png"
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_visual", "function": {"name": "visual_package_generate"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_visual",
                "content": (
                    '{"success": true, "images": ["'
                    + current
                    + '"], "videos": [], "delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["var_img"], '
                    '"visual_artifacts": {"'
                    + current
                    + '": {"artifact_id": "var_img", "kind": "image"}}}}'
                ),
            },
        ]

        current_paths = _collect_current_turn_delivery_media_paths(messages, history_offset=0)
        filtered = _filter_response_media_refs_to_current_turn(
            [(current, False)],
            current_turn_media_paths=current_paths,
            history_media_paths={current},
            turn_started_at=None,
        )

        assert filtered == [(current, False)]

    def test_compacted_text_only_turn_does_not_reclassify_old_visual_as_current(self):
        """A history_offset=0 compaction must not make old media current again."""
        from gateway.run import (
            _collect_current_turn_delivery_media_paths,
            _sanitize_final_response_media_refs,
        )

        stale = "/tmp/hermes-history/old-selected.png"
        compacted_messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "old_visual",
                        "function": {"name": "visual_package_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "old_visual",
                "content": (
                    '{"success": true, "images": ["'
                    + stale
                    + '"], "videos": [], "delivery_metadata": {'
                    '"selected_visual_artifact_ids": ["old_artifact"], '
                    '"visual_artifacts": {"'
                    + stale
                    + '": {"artifact_id": "old_artifact", "kind": "image"}}}}'
                ),
            },
            {"role": "user", "content": "只要文字說明，不要重送圖片"},
            {
                "role": "assistant",
                "content": f"舊圖路徑僅供說明：\nMEDIA:{stale}",
            },
        ]

        current_paths = _collect_current_turn_delivery_media_paths(
            compacted_messages,
            history_offset=0,
            history_media_paths={stale},
        )
        cleaned = _sanitize_final_response_media_refs(
            compacted_messages[-1]["content"],
            current_turn_media_paths=current_paths,
            history_media_paths={stale},
            turn_started_at=None,
        )

        assert current_paths == set()
        assert "MEDIA:" not in cleaned
        assert stale not in cleaned

    def test_sanitize_final_response_removes_stale_visual_media_tag(self):
        """Gateway should strip stale MEDIA tags before adapters extract them."""
        from gateway.run import _sanitize_final_response_media_refs

        stale = "/tmp/hermes-test/visual-arsenal/library/assets/old-a.png"
        cleaned = _sanitize_final_response_media_refs(
            f"這是構圖候選：\nMEDIA:{stale}",
            current_turn_media_paths=set(),
            history_media_paths={stale},
            turn_started_at=None,
        )

        assert "MEDIA:" not in cleaned
        assert stale not in cleaned
        assert "這是構圖候選" in cleaned

    def test_sanitize_final_response_removes_old_managed_visual_media_without_history(
        self, tmp_path, monkeypatch
    ):
        """Old managed visual assets are stale even if they were found by search."""
        from gateway.run import _sanitize_final_response_media_refs

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        asset = tmp_path / "visual-arsenal" / "library" / "assets" / "old-a.png"
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b"\x89PNG\r\n\x1a\n")
        old_time = 1000.0
        os.utime(asset, (old_time, old_time))

        cleaned = _sanitize_final_response_media_refs(
            f"這是搜尋到的舊圖：\nMEDIA:{asset}",
            current_turn_media_paths=set(),
            history_media_paths=set(),
            turn_started_at=old_time + 3600,
        )

        assert "MEDIA:" not in cleaned
        assert str(asset) not in cleaned
        assert "搜尋到的舊圖" in cleaned

    def test_sanitize_final_response_preserves_current_visual_media_tag(self):
        """Current-turn visual media remains available for native upload."""
        from gateway.run import _sanitize_final_response_media_refs

        current = "/tmp/hermes-test/visual-arsenal/library/assets/current.png"
        response = f"這是新的構圖候選：\nMEDIA:{current}"
        cleaned = _sanitize_final_response_media_refs(
            response,
            current_turn_media_paths={current},
            history_media_paths={current},
            turn_started_at=None,
        )

        assert cleaned == response


    def test_media_tags_not_extracted_from_history(self):
        """MEDIA tags from previous turns should NOT be extracted again."""
        # Simulate conversation history with a TTS call from a previous turn
        history = [
            {"role": "user", "content": "Say hello as audio"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "function": {"name": "text_to_speech"}}]},
            {"role": "tool", "tool_call_id": "1", "content": '{"success": true, "media_tag": "[[audio_as_voice]]\\nMEDIA:/path/to/audio1.ogg"}'},
            {"role": "assistant", "content": "I've said hello for you!"},
        ]
        
        # New turn: user asks a simple question
        new_messages = [
            {"role": "user", "content": "What time is it?"},
            {"role": "assistant", "content": "It's 3:30 AM."},
        ]
        
        all_messages = history + new_messages
        history_len = len(history)
        
        # Fixed behavior: should extract NO media tags (none in new messages)
        tags, voice_directive = extract_media_tags_fixed(all_messages, history_len)
        assert tags == [], "Fixed extraction should not find tags in history"
        assert voice_directive is False
        
        # Broken behavior: would incorrectly extract the old media tag
        broken_tags, broken_voice = extract_media_tags_broken(all_messages)
        assert len(broken_tags) == 1, "Broken extraction finds tags in history"
        assert "audio1.ogg" in broken_tags[0]
    
    def test_media_tags_extracted_from_current_turn(self):
        """MEDIA tags from the current turn SHOULD be extracted."""
        # History without TTS
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        
        # New turn with TTS call
        new_messages = [
            {"role": "user", "content": "Say goodbye as audio"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "2", "function": {"name": "text_to_speech"}}]},
            {"role": "tool", "tool_call_id": "2", "content": '{"success": true, "media_tag": "[[audio_as_voice]]\\nMEDIA:/path/to/audio2.ogg"}'},
            {"role": "assistant", "content": "I've said goodbye!"},
        ]
        
        all_messages = history + new_messages
        history_len = len(history)
        
        # Fixed behavior: should extract the new media tag
        tags, voice_directive = extract_media_tags_fixed(all_messages, history_len)
        assert len(tags) == 1, "Should extract media tag from current turn"
        assert "audio2.ogg" in tags[0]
        assert voice_directive is True
    
    def test_multiple_tts_calls_in_history_not_accumulated(self):
        """Multiple TTS calls in history should NOT accumulate in new responses."""
        # History with multiple TTS calls
        history = [
            {"role": "user", "content": "Say hello"},
            {"role": "tool", "tool_call_id": "1", "content": 'MEDIA:/audio/hello.ogg'},
            {"role": "assistant", "content": "Done!"},
            {"role": "user", "content": "Say goodbye"},
            {"role": "tool", "tool_call_id": "2", "content": 'MEDIA:/audio/goodbye.ogg'},
            {"role": "assistant", "content": "Done!"},
            {"role": "user", "content": "Say thanks"},
            {"role": "tool", "tool_call_id": "3", "content": 'MEDIA:/audio/thanks.ogg'},
            {"role": "assistant", "content": "Done!"},
        ]
        
        # New turn: no TTS
        new_messages = [
            {"role": "user", "content": "What time is it?"},
            {"role": "assistant", "content": "3 PM"},
        ]
        
        all_messages = history + new_messages
        history_len = len(history)
        
        # Fixed: no tags
        tags, _ = extract_media_tags_fixed(all_messages, history_len)
        assert tags == [], "Should not accumulate tags from history"
        
        # Broken: would have 3 tags (all the old ones)
        broken_tags, _ = extract_media_tags_broken(all_messages)
        assert len(broken_tags) == 3, "Broken version accumulates all history tags"
    
    def test_deduplication_within_current_turn(self):
        """Multiple MEDIA tags in current turn should be deduplicated."""
        history = []
        
        # Current turn with multiple tool calls producing same media
        new_messages = [
            {"role": "user", "content": "Multiple TTS"},
            {"role": "tool", "tool_call_id": "1", "content": 'MEDIA:/audio/same.ogg'},
            {"role": "tool", "tool_call_id": "2", "content": 'MEDIA:/audio/same.ogg'},  # duplicate
            {"role": "tool", "tool_call_id": "3", "content": 'MEDIA:/audio/different.ogg'},
            {"role": "assistant", "content": "Done!"},
        ]
        
        all_messages = history + new_messages
        
        tags, _ = extract_media_tags_fixed(all_messages, 0)
        # Even though same.ogg appears twice, deduplication happens after extraction
        # The extraction itself should get both, then caller deduplicates
        assert len(tags) == 3  # Raw extraction gets all
        
        # Deduplication as done in the actual code:
        seen = set()
        unique = [t for t in tags if t not in seen and not seen.add(t)]
        assert len(unique) == 2  # After dedup: same.ogg and different.ogg


class TestStaleToolMediaLeak:
    """Regression tests for #34608.

    A MEDIA: path emitted by an execute_code / make_image tool several turns
    earlier remains in the full conversation message list. A later text-only
    reply (zero MEDIA directives) must NOT attach that stale image.

    The production code previously relied solely on path-based dedup against
    paths reconstructed from the replayable transcript. When that
    reconstruction does not byte-match the in-memory tool content (timestamp
    stripping, observed-context withholding, compression rewrites), the stale
    path is absent from the dedup set and leaks. Turn-scoped slicing closes
    this class of bug deterministically.
    """

    def test_stale_execute_code_media_not_attached_to_text_only_reply(self):
        """The exact #34608 scenario: make_image cover from an earlier turn."""
        # Prior turn generated an image via execute_code stdout.
        history = [
            {"role": "user", "content": "Make a cover image"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "1", "function": {"name": "execute_code"}}]},
            {"role": "tool", "tool_call_id": "1",
             "content": "Generating cover...\nMEDIA:/tmp/seosmi_cover.png\nDone."},
            {"role": "assistant", "content": "Here is your cover."},
        ]
        # Current turn: plain text status update, zero MEDIA directives.
        new_messages = [
            {"role": "user", "content": "What skill version am I on?"},
            {"role": "assistant", "content": "You're on v0.15.1."},
        ]
        all_messages = history + new_messages
        history_len = len(history)

        # Simulate the dedup set FAILING to capture the stale path (the real
        # #34608 condition: replayable-history reconstruction diverged from
        # the in-memory tool content, so the path is not in the set).
        history_media_paths = set()

        tags, voice = extract_media_tags_production(
            all_messages, history_len, history_media_paths
        )
        assert tags == [], (
            "Stale tool MEDIA from a prior turn must not leak onto a "
            f"later text-only reply, got {tags}"
        )
        assert voice is False

        # The pre-fix production behaviour (scan everything, dedup only) would
        # have leaked the stale path when the dedup set missed it.
        broken_tags, _ = extract_media_tags_broken(all_messages)
        assert any("seosmi_cover.png" in t for t in broken_tags), (
            "Sanity: the unscoped scan does surface the stale path"
        )

    def test_current_turn_media_still_attached_when_dedup_set_empty(self):
        """Turn-scoping must not suppress genuinely new media."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        new_messages = [
            {"role": "user", "content": "Make me a cover image"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "9", "function": {"name": "execute_code"}}]},
            {"role": "tool", "tool_call_id": "9",
             "content": "MEDIA:/tmp/fresh_cover.png"},
            {"role": "assistant", "content": "Here it is."},
        ]
        all_messages = history + new_messages
        tags, _ = extract_media_tags_production(
            all_messages, len(history), set()
        )
        assert len(tags) == 1 and "fresh_cover.png" in tags[0]

    def test_compression_shrink_falls_back_to_path_dedup(self):
        """When the list is shorter than history_len (mid-run compression),
        fall back to scanning everything with path-based dedup so the #160
        compression-safe guarantee is preserved."""
        # Post-compression list is shorter than the original history length.
        compressed_messages = [
            {"role": "user", "content": "summary so far..."},
            {"role": "tool", "tool_call_id": "7",
             "content": "MEDIA:/tmp/old_from_history.png"},
            {"role": "assistant", "content": "ok"},
        ]
        original_history_len = 12  # larger than the compressed list
        # The old path IS captured in the dedup set here (history scan ran
        # before compression), so it must still be excluded.
        history_media_paths = {"/tmp/old_from_history.png"}
        tags, _ = extract_media_tags_production(
            compressed_messages, original_history_len, history_media_paths
        )
        assert tags == [], (
            "On the compression fallback path, path-dedup must still exclude "
            f"known-old media, got {tags}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
