import json


def test_extract_pose_transfer_instruction_keeps_only_pose_geometry(tmp_path):
    from agent.visual.reference_pose import extract_pose_transfer_instruction

    reference = tmp_path / "pose.png"
    reference.write_bytes(b"pose-reference")
    calls = []

    def analyzer(path, prompt):
        calls.append((path, prompt))
        return json.dumps(
            {
                "success": True,
                "analysis": json.dumps(
                {
                    "torso": {"lean_direction": "left", "lean_degrees": 18, "facing": "front"},
                    "head": {"tilt_direction": "left", "tilt_degrees": 25, "chin": "down"},
                    "camera": {"view": "near_frontal_three_quarter", "elevation": "low", "distance": "close"},
                    "framing": {"shot": "tight_upper_body"},
                    "limbs": [
                        {"limb": "subject_left_arm", "direction": "up", "bend": "straight", "visibility": "partial", "foreground": True},
                        {"limb": "subject_right_arm", "direction": "down", "bend": "slight", "visibility": "out_of_frame", "foreground": False},
                    ],
                    "crop": {"top": "clips_arm", "bottom": "clips_waist", "left": "clips_shoulder", "right": "clips_arm"},
                    "identity": "must not survive",
                    "wardrobe": "must not survive",
                    "appearance": "blonde woman wearing red",
                }
                ),
            }
        )

    result = extract_pose_transfer_instruction(
        str(reference),
        analyzer=analyzer,
        cache_dir=tmp_path / "cache",
    )

    assert result["success"] is True
    assert result["source"] == "vision_pose_geometry"
    assert "torso lean left 18 degrees" in result["instruction"]
    assert "subject left arm up, straight, partial, foreground" in result["instruction"]
    assert "must not survive" not in result["instruction"]
    assert "red hair" not in result["instruction"]
    assert "black dress" not in result["instruction"]
    assert "blonde woman" not in result["instruction"]
    assert len(result["instruction"]) <= 680
    assert result["analyzer"]["route"] == "injected"
    assert len(calls) == 1
    assert "Ignore identity, appearance, hair" in calls[0][1]

    cached = extract_pose_transfer_instruction(
        str(reference),
        analyzer=lambda *_args: (_ for _ in ()).throw(AssertionError("cache miss")),
        cache_dir=tmp_path / "cache",
    )
    assert cached["success"] is True
    assert cached["cache_hit"] is True


def test_extract_pose_transfer_instruction_fails_closed_on_unstructured_analysis(tmp_path):
    from agent.visual.reference_pose import extract_pose_transfer_instruction

    reference = tmp_path / "pose.png"
    reference.write_bytes(b"pose-reference")

    result = extract_pose_transfer_instruction(
        str(reference),
        analyzer=lambda *_args: {"success": True, "analysis": "looks nice"},
        cache_dir=tmp_path / "cache",
    )

    assert result["success"] is False
    assert result["error_type"] == "pose_geometry_unavailable"


def test_extract_pose_transfer_instruction_bounds_large_geometry(tmp_path):
    from agent.visual.reference_pose import extract_pose_transfer_instruction

    reference = tmp_path / "pose.png"
    reference.write_bytes(b"large-pose-reference")
    geometry = {
        "torso": {"lean_direction": "left", "lean_degrees": 9999, "facing": "three_quarter_left", "description": "blonde woman" * 100},
        "head": {"tilt_direction": "right", "tilt_degrees": 9999, "chin": "down"},
        "camera": {"view": "near_frontal_three_quarter", "elevation": "low", "distance": "close"},
        "framing": {"shot": "tight_upper_body"},
        "limbs": [
            {"limb": limb, "direction": "up", "bend": "straight", "visibility": "partial", "foreground": True, "description": "wearing red" * 100}
            for limb in ("subject_left_arm", "subject_right_arm", "subject_left_leg", "subject_right_leg")
        ],
        "crop": {"top": "clips_arm", "bottom": "clips_waist", "left": "clips_shoulder", "right": "clips_arm"},
        "extra": "identity wardrobe style " * 1000,
    }

    result = extract_pose_transfer_instruction(
        str(reference),
        analyzer=lambda *_args: {"success": True, "analysis": json.dumps(geometry)},
        cache_dir=tmp_path / "cache",
    )

    assert result["success"] is True
    assert len(result["instruction"]) <= 680
    assert "framing tight upper body" in result["instruction"]
    assert "camera near frontal three quarter, low, close" in result["instruction"]
    assert "torso lean left 90 degrees" in result["instruction"]
    assert "head tilt right 90 degrees" in result["instruction"]
    assert "subject left arm" in result["instruction"]
    assert "crop top clips arm" in result["instruction"]
    assert "blonde" not in result["instruction"]
    assert "wearing red" not in result["instruction"]
