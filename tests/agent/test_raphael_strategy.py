from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.strategy import simulate_raphael_strategies


def test_strategy_simulation_emits_fast_safe_quality_routes():
    appraisal = RaphaelAppraisal(
        intent="修復 runtime bug",
        task_type="tool_runtime",
        risk_level="medium",
        success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
    )

    strategies = simulate_raphael_strategies(appraisal)

    assert [strategy.label for strategy in strategies.candidates] == [
        "fast",
        "safe",
        "quality",
    ]
    assert strategies.selected_strategy_id == "safe"
    assert "focused_tests" in strategies.selected.required_proofs


def test_strategy_blocks_when_appraisal_has_blockers():
    appraisal = RaphaelAppraisal(
        intent="用 ref3 產圖",
        task_type="visual_generation",
        risk_level="medium",
        success_conditions=("reference_mapping_confirmed",),
        blockers=("missing_ref3",),
    )

    strategies = simulate_raphael_strategies(appraisal)

    assert strategies.selected.label == "blocked"
    assert strategies.selected.blocked_reason == "missing_ref3"


def test_strategy_keeps_visual_analysis_on_safe_text_route():
    appraisal = RaphaelAppraisal(
        intent="分析 image/video provider route",
        task_type="visual_analysis",
        risk_level="low",
        success_conditions=("text_only_plan", "no_provider_attempt"),
    )

    strategies = simulate_raphael_strategies(appraisal)

    assert strategies.selected_strategy_id == "safe"
    assert strategies.selected.required_proofs == (
        "text_only_plan",
        "no_provider_attempt",
    )
