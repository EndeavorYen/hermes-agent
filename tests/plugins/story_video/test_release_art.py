from plugins.story_video.release_art import compile_release_art_brief


def test_release_art_brief_promotes_topic_hero_over_bland_first_clue() -> None:
    ledger = {
        "visual_style": "photoreal science documentary",
        "scenes": [
            {
                "shots": [
                    {
                        "subject": "a flat gray rock sample",
                        "action": "the sample rests on a table",
                        "viewer_takeaway": "the evidence begins with a clue",
                        "engagement_role": "hook",
                        "composition_energy": "curious",
                        "shot_scale": "insert",
                    },
                    {
                        "subject": "a small early dinosaur sprinting through a storm-lit floodplain",
                        "action": "the dinosaur leaps over a fallen trunk as rain and ash cross the light",
                        "story_moment": "its foot leaves the mud at the peak of the leap",
                        "viewer_takeaway": "early dinosaurs survived by staying agile",
                        "engagement_role": "payoff",
                        "composition_energy": "kinetic",
                        "shot_scale": "medium",
                    },
                ]
            }
        ],
    }

    brief = compile_release_art_brief("恐龍的起源", ledger)

    assert "small early dinosaur sprinting" in brief["prompt"]
    assert "flat gray rock sample" not in brief["prompt"]


def test_release_art_brief_builds_educational_cinematic_ending_from_story_payoff() -> None:
    ledger = {
        "visual_style": "cinematic natural-history reconstruction",
        "quality_contract_version": 4,
        "style_bible": {
            "style_id": "theatrical-discovery-v1",
            "anchor_shot_id": "S00_SH00",
            "medium": "cinematic photoreal reconstruction",
            "palette": "mineral green and volcanic amber",
            "lighting": "motivated shafts with dimensional contrast",
            "lens_language": "low 35mm hero perspective",
            "texture": "tactile skin, dust, and vegetation",
            "atmosphere": "wonder with controlled danger",
            "subject_treatment": "one dominant story action",
            "forbidden_drift": ["flat encyclopedia plate"],
        },
        "story_engine": {
            "knowledge_payoff": "恐龍的興起，是身體特徵與環境共同寫下的結果。",
            "ending_echo": "原來，改變世界的第一步，可能只是一枚小腳印。",
        },
        "scenes": [
            {
                "viewer_takeaway": "最小的線索也能改寫我們對遠古世界的理解",
                "shots": [
                    {
                        "subject": "small early dinosaur crossing a storm-lit floodplain",
                        "action": "leaves one crisp footprint in wet mud",
                        "story_moment": "the foot lifts and reveals the track",
                        "viewer_takeaway": "a small footprint can preserve a major clue",
                        "engagement_role": "payoff",
                        "composition_energy": "awe",
                        "shot_scale": "medium",
                    }
                ],
            }
        ],
    }

    brief = compile_release_art_brief("恐龍的起源", ledger)

    assert brief["ending_heading"] == "原來，改變世界的第一步，可能只是一枚小腳印。"
    assert brief["ending_takeaway"] == "恐龍的興起，是身體特徵與環境共同寫下的結果。"
    assert brief["ending_label"] == "今天帶走的發現"
    assert "Style bible lock: theatrical-discovery-v1" in brief["prompt"]
