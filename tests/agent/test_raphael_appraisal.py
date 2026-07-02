from agent.raphael.appraisal import appraise_raphael_situation


def test_appraisal_classifies_tool_runtime_task_with_required_proofs():
    appraisal = appraise_raphael_situation("拉斐爾，修復 runtime bug 並驗證")

    assert appraisal.task_type == "tool_runtime"
    assert appraisal.risk_level == "medium"
    assert appraisal.success_conditions == (
        "focused_tests",
        "runtime_smoke_when_live_wiring",
    )
    assert appraisal.blockers == ()


def test_appraisal_classifies_natural_chinese_tool_task_as_tool_runtime():
    appraisal = appraise_raphael_situation(
        "拉斐爾，請幫我完成一個工具任務，規劃、執行、驗證，並在失敗時主動修正。"
    )

    assert appraisal.task_type == "tool_runtime"
    assert appraisal.success_conditions == (
        "focused_tests",
        "runtime_smoke_when_live_wiring",
    )


def test_appraisal_classifies_blank_screen_repair_as_tool_runtime_not_visual():
    appraisal = appraise_raphael_situation("拉斐爾，接管這個任務：畫面空白，請修復")

    assert appraisal.task_type == "tool_runtime"
    assert appraisal.success_conditions == (
        "focused_tests",
        "runtime_smoke_when_live_wiring",
    )


def test_appraisal_classifies_llm_only_runtime_request_as_text_runtime_analysis():
    appraisal = appraise_raphael_situation(
        "拉斐爾，請以 LLM-only 模式分析：修復 runtime bug 並驗證。"
        "不要呼叫任何工具，不要產圖或影片。"
    )

    assert appraisal.task_type == "runtime_analysis"
    assert appraisal.risk_level == "low"
    assert appraisal.success_conditions == (
        "text_only_plan",
        "no_tool_call",
        "no_provider_attempt",
    )


def test_appraisal_does_not_route_negated_media_summon_smoke_to_visual_generation():
    appraisal = appraise_raphael_situation(
        "拉斐爾？不要呼叫工具，不要產圖，只測試 LLM-only Raphael summon。"
        "請用三段短句回覆：狀態、目前目標、下一步。"
    )

    assert appraisal.task_type == "runtime_analysis"
    assert appraisal.risk_level == "low"
    assert appraisal.success_conditions == (
        "text_only_plan",
        "no_tool_call",
        "no_provider_attempt",
    )


def test_appraisal_keeps_constrained_casual_summon_text_only_without_llm_keyword():
    appraisal = appraise_raphael_situation(
        "拉斐爾？不要呼叫工具，不要產圖。請只回覆三行：狀態、可接管、下一步。"
    )

    assert appraisal.task_type == "runtime_analysis"
    assert appraisal.risk_level == "low"
    assert appraisal.success_conditions == (
        "text_only_plan",
        "no_tool_call",
        "no_provider_attempt",
    )


def test_appraisal_detects_missing_reference_blocker():
    appraisal = appraise_raphael_situation(
        "拉斐爾，用 ref3 的服裝產圖",
        attachments=["/tmp/ref1.png", "/tmp/ref2.png"],
    )

    assert appraisal.task_type == "visual_generation"
    assert "missing_ref3" in appraisal.blockers
    assert "reference_mapping_confirmed" in appraisal.success_conditions


def test_appraisal_classifies_natural_chinese_image_request_as_visual_generation():
    appraisal = appraise_raphael_situation("請做一張角色站姿圖")

    assert appraisal.task_type == "visual_generation"
    assert "selected_current_artifact_only" in appraisal.success_conditions


def test_appraisal_classifies_visual_route_analysis_as_text_only_analysis():
    appraisal = appraise_raphael_situation(
        "請分析如果使用者要求產圖和生成影片，應該路由到哪個 provider / proof gate？"
    )

    assert appraisal.task_type == "visual_analysis"
    assert appraisal.success_conditions == ("text_only_plan", "no_provider_attempt")


def test_appraisal_preserves_active_artifact_for_followup_edit():
    appraisal = appraise_raphael_situation(
        "拉斐爾，把剛剛那張改成夜景",
        conversation_history=[
            {
                "role": "assistant",
                "metadata": {"selected_artifact_id": "img_current"},
            }
        ],
    )

    assert appraisal.task_type == "visual_edit"
    assert appraisal.active_artifact_id == "img_current"


def test_appraisal_preserves_top_level_artifact_for_natural_followup_edit():
    appraisal = appraise_raphael_situation(
        "把剛剛那張圖改成微笑，比例不要變",
        conversation_history=[
            {
                "role": "assistant",
                "content": "已產出圖片。",
                "artifact_id": "artifact-top-level",
            }
        ],
    )

    assert appraisal.task_type == "visual_edit"
    assert appraisal.active_artifact_id == "artifact-top-level"


def test_appraisal_preserves_visual_delivery_manifest_artifact_for_followup_edit():
    appraisal = appraise_raphael_situation(
        "上一張照片再改亮一點",
        conversation_history=[
            {
                "role": "tool",
                "name": "visual_package_generate",
                "content": '{"success": true}',
                "metadata": {
                    "delivery_metadata": {
                        "selected_visual_artifact_ids": ["artifact-selected"]
                    }
                },
            }
        ],
    )

    assert appraisal.task_type == "visual_edit"
    assert appraisal.active_artifact_id == "artifact-selected"
