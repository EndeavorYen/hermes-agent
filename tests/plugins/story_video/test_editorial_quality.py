from __future__ import annotations

from plugins.story_video.editorial_quality import (
    compute_read_aloud_metrics,
    validate_editorial_profile_v2,
)


SCRIPT = """### S00
午夜的沙地忽然抖了一下，一隻巴掌大的腳印出現在月光裡。

### S01
牠不是巨獸，卻藏著一個大問題：這樣的小傢伙，怎麼成了後來的恐龍家族？

### S02
鏡頭鑽進岩層，牙齒和骨頭像拼圖一樣，悄悄排出兩億多年前的時間順序。

### S03
等等，最像恐龍的骨頭竟然不一定屬於恐龍，科學家得比對髖骨和腳踝才敢下結論。

### S04
答案逐漸亮起來：牠們能用雙腳快速移動，也能把前肢空出來探索新的食物。

### S05
最後一塊化石沒有關上故事，反而打開新問題，下一次發現也許會改寫今天的答案。
"""


def _valid_report() -> dict:
    return {
        "schema": "story_video_editorial_metrics_v1",
        "concrete_scene_evidence": [
            {
                "segment_id": segment_id,
                "subject": "可辨識主體",
                "action": "可見動作",
                "sensory_detail": "可拍攝細節",
                "stakes_or_question": "推動故事的問題",
            }
            for segment_id in ("S00", "S01", "S02", "S03", "S04")
        ],
        "abstract_only_segment_ids": [],
        "curiosity_loop_evidence": [
            {
                "loop_id": f"Q{index}",
                "opening_segment_id": opening,
                "payoff_segment_id": payoff,
                "question": "一個具體問題",
                "payoff": "一個具體答案",
                "status": "resolved",
            }
            for index, (opening, payoff) in enumerate(
                (
                    ("S00", "S01"),
                    ("S01", "S02"),
                    ("S02", "S03"),
                    ("S03", "S04"),
                    ("S04", "S05"),
                ),
                start=1,
            )
        ],
        "delight_beat_evidence": [
            {
                "segment_id": "S00",
                "beat_type": "surprise",
                "text": "巨大的恐龍故事從小腳印開始",
            },
            {
                "segment_id": "S03",
                "beat_type": "reversal",
                "text": "最像恐龍的骨頭也可能不是恐龍",
            },
        ],
        "emotional_turn_evidence": [
            {
                "segment_id": segment_id,
                "from_state": before,
                "to_state": after,
                "cause": "新證據改變理解",
            }
            for segment_id, before, after in (
                ("S01", "surprise", "curiosity"),
                ("S03", "confidence", "doubt"),
                ("S04", "doubt", "awe"),
            )
        ],
        "rhetorical_template_evidence": [
            {"template": "question_then_reveal", "segment_ids": ["S00", "S01"]}
        ],
        "reported_read_aloud_metrics": {
            "sentence_count": 6,
            "long_sentence_ratio": 0.0,
        },
    }


def test_editorial_profile_v2_accepts_evidence_bound_metrics() -> None:
    assert validate_editorial_profile_v2(SCRIPT, _valid_report(), 300) == ()


def test_editorial_profile_v2_recomputes_long_sentence_ratio() -> None:
    report = _valid_report()
    report["reported_read_aloud_metrics"]["long_sentence_ratio"] = 0.2

    violations = validate_editorial_profile_v2(SCRIPT, report, 300)

    assert "editorial_metrics.long_sentence_ratio report mismatch" in violations


def test_editorial_profile_v2_requires_enough_resolved_curiosity_loops() -> None:
    report = _valid_report()
    report["curiosity_loop_evidence"] = report["curiosity_loop_evidence"][:2]

    violations = validate_editorial_profile_v2(SCRIPT, report, 300)

    assert "editorial_metrics.curiosity_loop_count<5" in violations
    assert "editorial_metrics.resolved_curiosity_loop_count<5" in violations


def test_editorial_profile_v2_rejects_unbound_or_repeated_evidence() -> None:
    report = _valid_report()
    report["delight_beat_evidence"][0]["segment_id"] = "S99"
    report["rhetorical_template_evidence"][0]["segment_ids"] = [
        "S00",
        "S01",
        "S02",
    ]

    violations = validate_editorial_profile_v2(SCRIPT, report, 300)

    assert "editorial_metrics evidence references unknown segment: S99" in violations
    assert "editorial_metrics rhetorical template question_then_reveal used>2" in violations


def test_editorial_profile_v2_rejects_non_finite_runtime_without_crashing() -> None:
    violations = validate_editorial_profile_v2(SCRIPT, _valid_report(), float("inf"))

    assert "editorial_metrics target_duration_sec is invalid" in violations


def test_read_aloud_metrics_keep_sentence_closing_quote_with_sentence() -> None:
    script = """### S00
雨滴落在葉子上。下次抬頭想一想：「原來，是地球把水滴拉回來。」
"""

    assert compute_read_aloud_metrics(script) == {
        "sentence_count": 2,
        "long_sentence_count": 0,
        "long_sentence_ratio": 0.0,
    }
