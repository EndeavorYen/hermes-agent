def test_delivery_manifest_selects_only_selected_artifacts():
    from agent.visual.delivery_manifest import build_visual_delivery_manifest
    from agent.visual.delivery_manifest import select_deliverable_artifacts

    payload = {
        "visual_request_id": "vrq_1",
        "images": ["/tmp/selected.png"],
        "videos": ["https://vidgen.example/current.mp4"],
        "delivery_metadata": {
            "selected_visual_artifact_ids": ["var_selected", "var_video"],
            "visual_artifacts": {
                "/tmp/selected.png": {
                    "request_id": "vrq_1",
                    "attempt_id": "vat_1",
                    "artifact_id": "var_selected",
                    "kind": "image",
                    "content_hash": "hash-selected",
                },
                "/tmp/old.png": {
                    "request_id": "vrq_old",
                    "attempt_id": "vat_old",
                    "artifact_id": "var_old",
                    "kind": "image",
                    "content_hash": "hash-old",
                },
                "https://vidgen.example/current.mp4": {
                    "request_id": "vrq_1",
                    "attempt_id": "vat_2",
                    "artifact_id": "var_video",
                    "kind": "video",
                    "source_identity": "https://vidgen.example/current.mp4",
                },
            },
        },
    }

    manifest = build_visual_delivery_manifest(payload)
    deliverables = select_deliverable_artifacts(manifest)

    assert manifest["request_id"] == "vrq_1"
    assert [item["artifact_id"] for item in deliverables] == ["var_selected", "var_video"]
    assert deliverables[0]["ref"] == "/tmp/selected.png"
    assert deliverables[0]["identity"] == "hash-selected"
    assert deliverables[1]["ref"] == "https://vidgen.example/current.mp4"
    assert deliverables[1]["identity"] == "https://vidgen.example/current.mp4"


def test_delivery_manifest_deduplicates_selected_artifacts_by_identity():
    from agent.visual.delivery_manifest import build_visual_delivery_manifest
    from agent.visual.delivery_manifest import select_deliverable_artifacts

    payload = {
        "visual_request_id": "vrq_1",
        "delivery_metadata": {
            "selected_visual_artifact_ids": ["var_a", "var_b"],
            "visual_artifacts": {
                "/tmp/a.png": {"request_id": "vrq_1", "artifact_id": "var_a", "content_hash": "same"},
                "/tmp/b.png": {"request_id": "vrq_1", "artifact_id": "var_b", "content_hash": "same"},
            },
        },
    }

    manifest = build_visual_delivery_manifest(payload)

    assert [item["artifact_id"] for item in select_deliverable_artifacts(manifest)] == ["var_a"]


def test_delivery_manifest_deduplicates_same_artifact_with_multiple_lookup_refs():
    from agent.visual.delivery_manifest import build_visual_delivery_manifest
    from agent.visual.delivery_manifest import select_deliverable_artifacts

    payload = {
        "visual_request_id": "vrq_1",
        "images": ["/tmp/current.png"],
        "delivery_metadata": {
            "selected_visual_artifact_ids": ["var_img"],
            "visual_artifacts": {
                "/tmp/current.png": {"request_id": "vrq_1", "artifact_id": "var_img"},
                "file:///tmp/current.png": {"request_id": "vrq_1", "artifact_id": "var_img"},
            },
        },
    }

    manifest = build_visual_delivery_manifest(payload)

    deliverables = select_deliverable_artifacts(manifest)
    assert [item["artifact_id"] for item in deliverables] == ["var_img"]
    assert deliverables[0]["ref"] == "/tmp/current.png"


def test_delivery_manifest_empty_payload_is_safe():
    from agent.visual.delivery_manifest import build_visual_delivery_manifest
    from agent.visual.delivery_manifest import select_deliverable_artifacts

    manifest = build_visual_delivery_manifest({})

    assert manifest["request_id"] is None
    assert select_deliverable_artifacts(manifest) == []
