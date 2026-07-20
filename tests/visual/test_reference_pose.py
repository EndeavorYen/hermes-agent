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
                        {
                            "limb": "subject_left_arm",
                            "direction": "up",
                            "bend": "straight",
                            "visibility": "partial",
                            "foreground": True,
                            "frame_side": "right",
                            "prominence": "dominant",
                        },
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
    assert (
        "key action: raise subject left arm vertically overhead on frame right, "
        "elbow nearly straight, dominant in the foreground, partially cropped"
        in result["instruction"]
    )
    assert "replace the identity anchor's original arm layout; do not leave both arms down" in result["instruction"]
    assert "must not survive" not in result["instruction"]
    assert "red hair" not in result["instruction"]
    assert "black dress" not in result["instruction"]
    assert "blonde woman" not in result["instruction"]
    assert len(result["instruction"]) <= 680
    assert result["analyzer"]["route"] == "injected"
    assert len(calls) == 1
    assert "Ignore identity, appearance, hair" in calls[0][1]
    assert '"frame_side":"left|center|right"' in calls[0][1]
    assert '"prominence":"dominant|clear|secondary"' in calls[0][1]

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


def test_extract_pose_transfer_instruction_retries_transient_analyzer_envelope(tmp_path):
    from agent.visual.reference_pose import extract_pose_transfer_instruction

    reference = tmp_path / "pose.png"
    reference.write_bytes(b"pose-reference")
    calls = []
    geometry = {
        "torso": {"lean_direction": "left", "lean_degrees": 12, "facing": "three_quarter_right"},
        "head": {"tilt_direction": "left", "tilt_degrees": 18, "chin": "down"},
        "camera": {"view": "near_frontal_three_quarter", "elevation": "eye_level", "distance": "close"},
        "framing": {"shot": "tight_upper_body"},
        "limbs": [
            {
                "limb": "subject_left_arm",
                "direction": "up",
                "bend": "straight",
                "visibility": "partial",
                "foreground": True,
                "frame_side": "right",
                "prominence": "dominant",
            }
        ],
        "crop": {"top": "clips_arm", "bottom": "clips_torso", "left": "clips_torso", "right": "clips_arm"},
    }

    def analyzer(*_args):
        calls.append(1)
        if len(calls) == 1:
            return {"success": False, "error": "Connection error: client has been closed"}
        return {"success": True, "analysis": json.dumps(geometry)}

    result = extract_pose_transfer_instruction(
        str(reference),
        analyzer=analyzer,
        cache_dir=tmp_path / "cache",
    )

    assert result["success"] is True
    assert result["analyzer_attempts"] == 2
    assert len(calls) == 2


def test_extract_pose_transfer_instruction_does_not_retry_unstructured_success(tmp_path):
    from agent.visual.reference_pose import extract_pose_transfer_instruction

    reference = tmp_path / "pose.png"
    reference.write_bytes(b"pose-reference")
    calls = []

    result = extract_pose_transfer_instruction(
        str(reference),
        analyzer=lambda *_args: calls.append(1) or {"success": True, "analysis": "looks nice"},
        cache_dir=tmp_path / "cache",
    )

    assert result["success"] is False
    assert len(calls) == 1


def test_extract_pose_transfer_instruction_preserves_diagonal_raised_arm_direction(tmp_path):
    from agent.visual.reference_pose import extract_pose_transfer_instruction

    reference = tmp_path / "pose.png"
    reference.write_bytes(b"diagonal-pose-reference")
    geometry = {
        "torso": {"lean_direction": "none", "lean_degrees": 0, "facing": "front"},
        "head": {"tilt_direction": "none", "tilt_degrees": 0, "chin": "level"},
        "camera": {"view": "front", "elevation": "eye_level", "distance": "medium"},
        "framing": {"shot": "upper_body"},
        "limbs": [
            {
                "limb": "subject_right_arm",
                "direction": "diagonal_up_left",
                "bend": "straight",
                "visibility": "full",
                "foreground": False,
                "frame_side": "left",
                "prominence": "clear",
            }
        ],
        "crop": {"top": "none", "bottom": "clips_torso", "left": "none", "right": "none"},
    }

    result = extract_pose_transfer_instruction(
        str(reference),
        analyzer=lambda *_args: {"success": True, "analysis": json.dumps(geometry)},
        cache_dir=tmp_path / "cache",
    )

    assert result["success"] is True
    assert "raise subject right arm diagonally up toward frame left" in result["instruction"]
    assert "right arm vertically overhead" not in result["instruction"]


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
