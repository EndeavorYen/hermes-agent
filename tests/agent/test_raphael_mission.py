from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.mission import update_raphael_mission
from agent.raphael.strategy import RaphaelStrategy, RaphaelStrategySet


def _strategies(required_proofs=("focused_tests",)):
    selected = RaphaelStrategy(
        strategy_id="safe",
        label="safe",
        route="plan_execute_verify",
        expected_benefit="best_reliability",
        risk="low",
        required_proofs=required_proofs,
    )
    return RaphaelStrategySet(candidates=(selected,), selected_strategy_id="safe")


def test_mission_state_is_created_from_appraisal_and_strategy():
    appraisal = RaphaelAppraisal(
        intent="修復 runtime bug",
        task_type="tool_runtime",
        risk_level="medium",
        success_conditions=("focused_tests",),
    )

    mission = update_raphael_mission(None, appraisal, _strategies())

    assert mission.mission_id.startswith("mission-")
    assert mission.goal == "修復 runtime bug"
    assert mission.phase == "strategy_selected"
    assert mission.selected_strategy_id == "safe"
    assert mission.proof_status == "pending"


def test_followup_updates_existing_mission_instead_of_restarting():
    current = update_raphael_mission(
        None,
        RaphaelAppraisal(
            "修復 runtime bug",
            "tool_runtime",
            "medium",
            ("focused_tests",),
        ),
        _strategies(),
    )

    updated = update_raphael_mission(
        current,
        RaphaelAppraisal(
            "再補 runtime smoke",
            "tool_runtime",
            "medium",
            ("focused_tests", "runtime_smoke_when_live_wiring"),
        ),
        _strategies(("focused_tests", "runtime_smoke_when_live_wiring")),
    )

    assert updated.mission_id == current.mission_id
    assert updated.goal == "再補 runtime smoke"
    assert updated.required_proofs == (
        "focused_tests",
        "runtime_smoke_when_live_wiring",
    )


def test_unrelated_goal_starts_new_mission_instead_of_reusing_current_id():
    current = update_raphael_mission(
        None,
        RaphaelAppraisal(
            "修復 gateway fallback bug",
            "tool_runtime",
            "medium",
            ("focused_tests",),
        ),
        _strategies(),
    )

    updated = update_raphael_mission(
        current,
        RaphaelAppraisal(
            "清理 repo stale branches 並建立 release PR",
            "tool_runtime",
            "medium",
            ("focused_tests", "diff_hygiene"),
        ),
        _strategies(("focused_tests", "diff_hygiene")),
    )

    assert updated.mission_id != current.mission_id
    assert updated.goal == "清理 repo stale branches 並建立 release PR"


def test_mission_state_round_trips_through_runtime_state(tmp_path, monkeypatch):
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    mission = update_raphael_mission(
        None,
        RaphaelAppraisal(
            "修復 runtime bug",
            "tool_runtime",
            "medium",
            ("focused_tests",),
        ),
        _strategies(),
    )

    state.write_mission_state(mission)
    loaded = state.read_mission_state()

    assert loaded == mission


def test_mission_state_compatibility_writer_uses_canonical_state(tmp_path, monkeypatch):
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    mission = update_raphael_mission(
        None,
        RaphaelAppraisal(
            "修復 runtime bug",
            "tool_runtime",
            "medium",
            ("focused_tests",),
        ),
        _strategies(),
    )

    state.write_mission_state(mission)

    assert state.read_state().active_mission is not None
    assert state.read_state().active_mission.goal == "修復 runtime bug"
    assert not state.get_raphael_mission_path().exists()


def test_background_observation_cannot_create_foreground_mission(
    tmp_path, monkeypatch
):
    from agent.raphael.observer import build_raphael_observation_context
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        },
    }

    build_raphael_observation_context(
        "Review the conversation above and update the skill library.",
        config,
        turn_origin="background_review",
    )

    assert state.read_state().active_mission is None
    assert state.read_mission_state() is None
    assert not state.get_raphael_mission_path().exists()


def test_background_observation_preserves_existing_foreground_mission(
    tmp_path, monkeypatch
):
    from agent.raphael.observer import build_raphael_observation_context
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        },
    }
    foreground = update_raphael_mission(
        None,
        RaphaelAppraisal(
            "使用者真正目標",
            "tool_runtime",
            "medium",
            ("focused_tests",),
        ),
        _strategies(),
    )
    state.write_mission_state(foreground)

    build_raphael_observation_context(
        "Review the conversation above and update the skill library.",
        config,
        turn_origin="background_review",
    )

    assert state.read_mission_state() == foreground


def test_observation_context_persists_and_updates_current_mission(tmp_path, monkeypatch):
    from agent.raphael.observer import build_raphael_observation_context
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        }
    }

    first_context = build_raphael_observation_context(
        "請修復 gateway fallback bug 並驗證",
        config,
    )
    first_mission = state.read_mission_state()
    second_context = build_raphael_observation_context(
        "再補 install enable disable lifecycle 驗證",
        config,
    )
    second_mission = state.read_mission_state()

    assert "Raphael" in first_context
    assert "Raphael" in second_context
    assert first_mission is not None
    assert second_mission is not None
    assert second_mission.mission_id == first_mission.mission_id
    assert second_mission.goal == "再補 install enable disable lifecycle 驗證"
    assert "focused_tests" in second_mission.required_proofs


def test_observation_context_does_not_overwrite_mission_on_casual_turn(
    tmp_path, monkeypatch
):
    from agent.raphael.observer import build_raphael_observation_context
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "sage_king",
        }
    }

    build_raphael_observation_context("請修復 gateway fallback bug 並驗證", config)
    first_mission = state.read_mission_state()
    build_raphael_observation_context("謝謝，先這樣", config)
    second_mission = state.read_mission_state()

    assert first_mission is not None
    assert second_mission is not None
    assert second_mission.mission_id == first_mission.mission_id
    assert second_mission.goal == first_mission.goal
    assert second_mission.required_proofs == first_mission.required_proofs
