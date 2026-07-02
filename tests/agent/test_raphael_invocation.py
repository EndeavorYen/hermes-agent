from agent.raphael.appraisal import RaphaelAppraisal
from agent.raphael.invocation import (
    is_raphael_invocation,
    render_raphael_invocation_response,
)
from agent.raphael.mission import update_raphael_mission
from agent.raphael.strategy import simulate_raphael_strategies


def test_detects_english_and_chinese_summon_phrases():
    assert is_raphael_invocation("Raphael, analyze this")
    assert is_raphael_invocation("拉斐爾，接管這個任務")
    assert is_raphael_invocation("請拉斐爾接管這個任務")
    assert is_raphael_invocation("大賢者，解析")
    assert is_raphael_invocation("賢者之王")
    assert not is_raphael_invocation("請修復這個 bug")


def test_does_not_treat_file_paths_or_topic_mentions_as_summons():
    assert not is_raphael_invocation("請閱讀 docs/raphael-mode.md")
    assert not is_raphael_invocation("agent/raphael/invocation.py 有一個 bug")
    assert not is_raphael_invocation("請問 Raphael mode 的設計文件在哪裡？")
    assert not is_raphael_invocation("整理拉斐爾 release evidence")


def test_render_summon_response_contains_appraisal_strategy_and_proof():
    appraisal = RaphaelAppraisal(
        intent="修復 runtime bug",
        task_type="tool_runtime",
        risk_level="medium",
        success_conditions=("focused_tests", "runtime_smoke_when_live_wiring"),
    )
    strategies = simulate_raphael_strategies(appraisal)

    response = render_raphael_invocation_response(appraisal, strategies)

    assert "解析完成" in response
    assert "目標：修復 runtime bug" in response
    assert "並列推演：" in response
    assert "最優路線：穩定執行" in response
    assert "必要證據：聚焦測試通過、live runtime smoke 通過" in response
    assert "下一步：先規劃，再執行，最後用證據驗證" in response
    assert "type=" not in response
    assert "risk=" not in response
    assert "focused_tests" not in response
    assert "runtime_smoke_when_live_wiring" not in response
    assert "plan_execute_verify" not in response


def test_render_casual_summon_asks_for_mission_target_instead_of_treating_name_as_goal():
    appraisal = RaphaelAppraisal(
        intent="拉斐爾？",
        task_type="general",
        risk_level="low",
        success_conditions=("answer_matches_user_intent",),
    )
    strategies = simulate_raphael_strategies(appraisal)

    response = render_raphael_invocation_response(appraisal, strategies)

    assert response.startswith("解析完成。")
    assert "狀態：Raphael 待命" in response
    assert "可接管：目標判讀、策略推演、證據驗證、演化提案" in response
    assert "請給我任務目標" in response
    assert "artifact" in response
    assert "目標：拉斐爾" not in response
    assert "局勢判讀" not in response
    assert "並列推演" not in response


def test_render_summon_response_hides_internal_mission_id():
    appraisal = RaphaelAppraisal(
        intent="修復 runtime bug",
        task_type="tool_runtime",
        risk_level="medium",
        success_conditions=("focused_tests",),
    )
    strategies = simulate_raphael_strategies(appraisal)
    mission = update_raphael_mission(None, appraisal, strategies)

    response = render_raphael_invocation_response(appraisal, strategies, mission)

    assert mission.mission_id not in response
    assert "任務：已選定策略" in response
    assert "mission-" not in response


def test_render_summon_response_explains_llm_only_runtime_analysis():
    appraisal = RaphaelAppraisal(
        intent="LLM-only 分析 runtime bug",
        task_type="runtime_analysis",
        risk_level="low",
        success_conditions=("text_only_plan", "no_tool_call", "no_provider_attempt"),
    )
    strategies = simulate_raphael_strategies(appraisal)

    response = render_raphael_invocation_response(appraisal, strategies)

    assert "局勢判讀：這是 LLM-only 文字分析回合" in response
    assert "必要證據：保持文字分析路線、不呼叫工具、不呼叫生成 provider" in response
    assert "runtime_analysis" not in response
    assert "no_tool_call" not in response


def test_render_live_llm_only_summon_smoke_does_not_claim_visual_generation():
    from agent.raphael.appraisal import appraise_raphael_situation

    appraisal = appraise_raphael_situation(
        "拉斐爾？不要呼叫工具，不要產圖，只測試 LLM-only Raphael summon。"
        "請用三段短句回覆：狀態、目前目標、下一步。"
    )
    strategies = simulate_raphael_strategies(appraisal)

    response = render_raphael_invocation_response(appraisal, strategies)

    assert "局勢判讀：這是 LLM-only 文字分析回合" in response
    assert "runtime 修復" not in response
    assert "視覺生成任務" not in response
    assert "品質與參考一致性" not in response
    assert "不呼叫工具" in response
    assert "不呼叫生成 provider" in response


def test_render_constrained_casual_summon_does_not_claim_visual_generation():
    from agent.raphael.appraisal import appraise_raphael_situation

    appraisal = appraise_raphael_situation(
        "拉斐爾？不要呼叫工具，不要產圖。請只回覆三行：狀態、可接管、下一步。"
    )
    strategies = simulate_raphael_strategies(appraisal)

    response = render_raphael_invocation_response(appraisal, strategies)

    assert "局勢判讀：這是 LLM-only 文字分析回合" in response
    assert "視覺生成任務" not in response
    assert "品質與參考一致性" not in response
    assert "不呼叫工具" in response
    assert "不呼叫生成 provider" in response


def test_render_summon_response_translates_blocker_without_internal_ids():
    appraisal = RaphaelAppraisal(
        intent="用 ref3 的服裝產圖",
        task_type="visual_generation",
        risk_level="medium",
        success_conditions=("reference_mapping_confirmed",),
        blockers=("missing_ref3",),
    )
    strategies = simulate_raphael_strategies(appraisal)

    response = render_raphael_invocation_response(appraisal, strategies)

    assert "局勢判讀：這是視覺生成任務" in response
    assert "阻塞：找不到使用者指定的 ref3" in response
    assert "missing_ref3" not in response
    assert "ask_precise_clarification" not in response
