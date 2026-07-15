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
