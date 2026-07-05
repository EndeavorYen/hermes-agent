def test_metadata_hygiene_removes_private_local_metadata_only():
    from agent.visual.metadata_hygiene import sanitize_deliverable_metadata

    result = sanitize_deliverable_metadata(
        {
            "local_path": "/Users/simon/.hermes/cache/private.png",
            "gps_latitude": "25.0",
            "camera_model": "private camera",
            "cache_key": "abc",
            "license": "user-provided",
            "compliance": {"provider": "xai"},
            "width": 1024,
            "height": 768,
            "content_hash": "hash",
        }
    )

    assert result == {
        "license": "user-provided",
        "compliance": {"provider": "xai"},
        "width": 1024,
        "height": 768,
        "content_hash": "hash",
    }


def test_metadata_hygiene_does_not_change_dimensions():
    from agent.visual.metadata_hygiene import sanitize_deliverable_metadata

    result = sanitize_deliverable_metadata({"width": 720, "height": 1280, "pixel_aspect_ratio": "1:1"})

    assert result["width"] == 720
    assert result["height"] == 1280
    assert result["pixel_aspect_ratio"] == "1:1"
