def test_intent_signature_is_stable_and_omits_raw_prompt():
    from agent.visual.intent_signature import build_intent_signature

    sig1 = build_intent_signature(
        {
            "modality": "package",
            "subject_type": "product",
            "style": "clean product photography",
            "aspect_ratio": "16:9",
            "raw_prompt": "private prompt should not leak",
        }
    )
    sig2 = build_intent_signature(
        {
            "aspect_ratio": "16:9",
            "style": "clean product photography",
            "subject_type": "product",
            "modality": "package",
            "raw_prompt": "different private text",
        }
    )

    assert sig1 == sig2
    assert sig1.startswith("visig_")
    assert "private" not in sig1
