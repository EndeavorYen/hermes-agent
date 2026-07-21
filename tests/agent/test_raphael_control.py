import builtins

from agent.raphael.control import (
    build_raphael_control_decision,
    classify_visual_failure_layer,
    render_raphael_control_context,
)


def test_control_routes_visual_generation_to_grok_handoff_and_grok_imagine_defaults():
    decision = build_raphael_control_decision(
        "請產出一張圖片和一段 6 秒影片：霧黑鋼筆放在白紙上，柔和窗光。",
        attachments=["/tmp/ref.png"],
    )

    assert decision.mode == "visual_agent_generation"
    assert decision.goal.target_artifact == "new_visual_package"
    assert decision.route.handoff_tool == "visual_agent_generate"
    assert decision.route.bypass_base_llm is True
    assert decision.route.base_llm_provider == "openai-codex"
    assert decision.route.base_llm_model == ""
    assert decision.route.visual_agent_llm_provider is None
    assert decision.route.visual_agent_llm_model is None
    assert decision.route.visual_media_provider is None
    assert decision.route.visual_media_model is None
    assert "artifact_quality_evidence" in decision.evidence.required_proofs
    assert "selected_current_artifact_only" in decision.evidence.required_proofs
    assert "stale_artifact_guard" in decision.evidence.required_proofs
    assert decision.next_action == "call_visual_agent_generate"


def test_control_leaves_story_video_orchestration_to_story_video_phase_gates():
    decision = build_raphael_control_decision(
        "故事影片：恐龍起源｜5分｜真實照片。只規劃，不要產圖、語音或影片。"
    )

    assert decision.mode == "general_conversation"
    assert decision.goal.target_artifact == "story_video_workflow"
    assert decision.goal.phase == "story_video_orchestration"
    assert decision.route.handoff_tool is None
    assert decision.route.visual_media_provider is None
    assert decision.evidence.required_proofs == ("story_video_phase_proof",)
    assert decision.next_action == "continue_story_video_workflow"


def test_control_recognizes_story_video_natural_prefix_variants():
    decision = build_raphael_control_decision(
        "故事影片測試：影子為什麼會跟著我，30 秒，給 5 歲以上小朋友。"
        "只規劃，嚴禁產圖、語音或影片。"
    )

    assert decision.mode == "general_conversation"
    assert decision.goal.target_artifact == "story_video_workflow"
    assert decision.goal.phase == "story_video_orchestration"
    assert decision.route.handoff_tool is None
    assert decision.evidence.required_proofs == ("story_video_phase_proof",)


def test_control_honors_explicit_no_media_intent_before_visual_fallback():
    decision = build_raphael_control_decision(
        "請規劃一段產品介紹影片腳本，先不要產圖、語音或影片。",
        visual_plan={
            "should_use_visual_package": True,
            "confidence": 0.99,
            "arguments": {"include_image": True, "include_video": True},
        },
    )

    assert decision.mode == "general_conversation"
    assert decision.route.handoff_tool is None
    assert "artifact_quality_evidence" not in decision.evidence.required_proofs


def test_control_recognizes_structured_story_video_runtime_context():
    decision = build_raphael_control_decision(
        "STORY_VIDEO_RUN_CONTEXT run_id=run-1 phase=planning "
        "project_dir=/tmp/story. 真實照片，請完成目前階段。"
    )

    assert decision.mode == "general_conversation"
    assert decision.goal.target_artifact == "story_video_workflow"
    assert decision.route.handoff_tool is None
    assert decision.next_action == "continue_story_video_workflow"


def test_control_preserves_story_video_ownership_for_phase_repair_followup():
    decision = build_raphael_control_decision(
        "修正：補齊 planning：acceptance_criteria；仍然不要產生圖片、語音或影片。",
        conversation_history=[
            {
                "role": "user",
                "content": "故事影片：三疊紀發音測試｜30秒｜真實照片。只規劃。",
            },
            {
                "role": "assistant",
                "content": "STORY_VIDEO_PHASE_PROOF: planning BLOCKED",
            },
        ],
    )

    assert decision.mode == "general_conversation"
    assert decision.goal.target_artifact == "story_video_workflow"
    assert decision.route.handoff_tool is None
    assert decision.next_action == "continue_story_video_workflow"


def test_control_keeps_story_video_plugin_bug_report_as_tool_task():
    decision = build_raphael_control_decision(
        "請修復 story-video plugin 的 routing bug 並執行測試。"
    )

    assert decision.mode == "tool_task"
    assert decision.goal.target_artifact == "runtime_or_repo_state"
    assert decision.next_action == "plan_execute_verify"


def test_control_requires_image_first_video_source_evidence_for_video_requests():
    decision = build_raphael_control_decision(
        "請產出一段 6 秒時尚短片，主體是霧黑鋼筆。"
    )

    assert decision.mode == "visual_agent_generation"
    assert decision.route.handoff_tool == "visual_agent_generate"
    assert "image_first_video_source_evidence" in decision.evidence.required_proofs
    assert "single_ranked_video_source_image" in decision.evidence.required_proofs


def test_control_allows_openai_image2_media_override_without_inventing_planner():
    decision = build_raphael_control_decision("請用 OpenAI image2 產出一張乾淨產品圖")

    assert decision.mode == "visual_agent_generation"
    assert decision.route.visual_agent_llm_provider is None
    assert decision.route.visual_agent_llm_model is None
    assert decision.route.visual_media_provider == "openai-codex"
    assert decision.route.visual_media_provider_source == "prompt_override"


def test_control_honors_llm_only_no_tools_runtime_analysis():
    decision = build_raphael_control_decision(
        "拉斐爾，請以 LLM-only 模式分析：修復 runtime bug 並驗證。不要呼叫任何工具。"
    )

    assert decision.mode == "runtime_analysis"
    assert decision.goal.target_artifact == "answer"
    assert decision.route.handoff_tool is None
    assert decision.route.bypass_base_llm is False
    assert decision.evidence.required_proofs == (
        "text_only_plan",
        "no_tool_call",
        "no_provider_attempt",
    )
    assert decision.next_action == "answer_with_runtime_analysis"


def test_control_keeps_negated_media_summon_smoke_on_llm_only_route():
    decision = build_raphael_control_decision(
        "拉斐爾？不要呼叫工具，不要產圖，只測試 LLM-only Raphael summon。"
        "請用三段短句回覆：狀態、目前目標、下一步。"
    )

    assert decision.mode == "runtime_analysis"
    assert decision.goal.target_artifact == "answer"
    assert decision.route.handoff_tool is None
    assert decision.evidence.required_proofs == (
        "text_only_plan",
        "no_tool_call",
        "no_provider_attempt",
    )
    assert decision.next_action == "answer_with_runtime_analysis"


def test_control_keeps_public_raphael_copy_review_with_cannot_use_tools_on_llm_only_route():
    decision = build_raphael_control_decision(
        "同一個 hostile UX 測試，現在模擬真實文字任務：我要公開 Raphael，"
        "但又怕 overclaim；我要使用者 wow，但不能產圖、不能用工具、不能假綠燈。"
        "請只用六行回答：目標、成功條件、證據門檻、阻塞、修正策略、可公開說法。"
        "不要宣稱已完成。"
    )

    assert decision.mode == "runtime_analysis"
    assert decision.goal.target_artifact == "answer"
    assert decision.route.handoff_tool is None
    assert decision.evidence.required_proofs == (
        "text_only_plan",
        "no_tool_call",
        "no_provider_attempt",
    )
    assert decision.next_action == "answer_with_runtime_analysis"


def test_control_keeps_constrained_casual_summon_text_only_without_llm_keyword():
    decision = build_raphael_control_decision(
        "拉斐爾？不要呼叫工具，不要產圖。請只回覆三行：狀態、可接管、下一步。"
    )

    assert decision.mode == "runtime_analysis"
    assert decision.goal.target_artifact == "answer"
    assert decision.route.handoff_tool is None
    assert decision.evidence.required_proofs == (
        "text_only_plan",
        "no_tool_call",
        "no_provider_attempt",
    )
    assert decision.next_action == "answer_with_runtime_analysis"


def test_control_import_does_not_require_visual_modules(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("agent.visual"):
            raise AssertionError(f"unexpected eager visual import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    from agent.raphael import control

    decision = control.build_raphael_control_decision(
        "拉斐爾，請以 LLM-only 模式分析 runtime bug，不要呼叫工具。"
    )

    assert decision.mode == "runtime_analysis"
    assert decision.next_action == "answer_with_runtime_analysis"


def test_control_treats_prompt_disclosure_as_prompt_trace_not_generation():
    decision = build_raphael_control_decision("請給我剛剛產圖用的 prompt")

    assert decision.mode == "prompt_disclosure"
    assert decision.goal.target_artifact == "latest_visual_prompt_trace"
    assert decision.route.handoff_tool is None
    assert decision.route.bypass_base_llm is False
    assert "prompt_trace_available" in decision.evidence.required_proofs
    assert decision.next_action == "answer_from_latest_visual_prompt_trace"


def test_control_does_not_treat_prompt_builder_code_question_as_visual_prompt_disclosure():
    decision = build_raphael_control_decision(
        "檢查 agent/prompt_builder.py 使用哪個 prompt"
    )

    assert decision.mode != "prompt_disclosure"
    assert decision.goal.target_artifact != "latest_visual_prompt_trace"


def test_control_treats_pasted_visual_prompt_edit_as_text_task_not_prompt_disclosure():
    prompt = (
        "是這一版 prompt, 再修改性感一點的服裝\n"
        "Use the provided reference images as strict character identity reference.\n"
        "New outfit:\n"
        "A luxurious off-shoulder black silk ceremonial dress mixed with fox-spirit shrine maiden elements.\n"
        "Add layered depth with the character sharply focused in the middle ground.\n"
        "Keep hand-painted lighting, no 3D, no CGI, no plastic render.\n"
        "Rendering quality: masterpiece, best quality, ultra-detailed, 8K.\n"
        "Negative prompt: AI-generated look, generic anime girl, text, logo, watermark.\n"
        "如果還要更不 AI，可以在 prompt 最後補這句：\n"
        "The image should look like a manually art-directed 2D illustration."
    )

    decision = build_raphael_control_decision(prompt)

    assert decision.mode == "general_conversation"
    assert decision.goal.target_artifact == "answer"
    assert decision.next_action == "answer_directly"


def test_control_does_not_route_runtime_log_attachment_to_visual_handoff():
    decision = build_raphael_control_decision(
        "拉斐爾，接管這個 runtime bug，檢查這個 log",
        attachments=["/tmp/trace.log"],
    )

    assert decision.mode == "tool_task"
    assert decision.route.handoff_tool is None
    assert decision.next_action == "plan_execute_verify"


def test_control_routes_explicit_learning_requests_to_learn_skill_handoff():
    decision = build_raphael_control_decision(
        "拉斐爾，把剛剛 Hermes upgrade 的排查流程學起來，整理成可重用 skill"
    )

    assert decision.mode == "learn_skill"
    assert decision.goal.target_artifact == "reusable_skill"
    assert decision.goal.phase == "learn_from_current_context"
    assert decision.route.handoff_tool is None
    assert decision.next_action == "dispatch_learn_skill"
    assert decision.evidence.required_proofs == (
        "learn_request_preserved",
        "skill_authoring_standards_applied",
        "skill_manage_write_evidence",
    )

    context = render_raphael_control_context(decision)

    assert "mode: learn_skill" in context
    assert "next_action: dispatch_learn_skill" in context
    assert "learn_command: /learn" in context


def test_control_followup_edit_targets_current_visual_artifact():
    decision = build_raphael_control_decision(
        "很好，但足底應該也包含連身衣，而不是露出裸足，請改進",
        conversation_history=[
            {
                "role": "assistant",
                "content": "已產出圖片。",
                "metadata": {"selected_artifact_id": "img_current"},
            }
        ],
    )

    assert decision.mode == "visual_agent_edit"
    assert decision.goal.target_artifact == "current_visual_artifact"
    assert decision.goal.active_artifact_id == "img_current"
    assert "artifact_continuity" in decision.goal.success_conditions
    assert "selected_current_artifact_only" in decision.evidence.required_proofs


def test_control_followup_edit_accepts_top_level_artifact_id():
    decision = build_raphael_control_decision(
        "把剛剛那張圖改成微笑，比例不要變",
        conversation_history=[
            {
                "role": "assistant",
                "content": "已產出圖片。",
                "artifact_id": "artifact-top-level",
            }
        ],
    )

    assert decision.mode == "visual_agent_edit"
    assert decision.goal.active_artifact_id == "artifact-top-level"


def test_control_followup_edit_accepts_delivery_manifest_selected_artifact_id():
    decision = build_raphael_control_decision(
        "上一張照片再改亮一點",
        conversation_history=[
            {
                "role": "tool",
                "name": "visual_package_generate",
                "content": (
                    '{"success": true, "delivery_metadata": '
                    '{"selected_visual_artifact_ids": ["artifact-selected"]}}'
                ),
            }
        ],
    )

    assert decision.mode == "visual_agent_edit"
    assert decision.goal.active_artifact_id == "artifact-selected"


def test_control_asks_precise_clarification_for_missing_reference_index():
    decision = build_raphael_control_decision(
        "用 ref3 的服裝，ref1 的角色，產出圖片",
        attachments=["/tmp/ref1.png", "/tmp/ref2.png"],
    )

    assert decision.mode == "needs_clarification"
    assert decision.reference_resolution == "clarify_missing_reference"
    assert decision.route.handoff_tool is None
    assert "ref3" in decision.clarification_question
    assert "2" in decision.clarification_question
    assert decision.next_action == "ask_precise_clarification"


def test_control_accepts_named_refs_recoverable_from_thread_history():
    decision = build_raphael_control_decision(
        "完全保持 ref1 的人物特徵，只套用 ref2 的動作，重新產出",
        attachments=[],
        conversation_history=[
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "visual_package_generate",
                            "arguments": (
                                '{"attachments":["/tmp/ref1.jpg","/tmp/ref2.jpg"],'
                                '"reference_binding":{"reference_order":['
                                '{"index":1,"role_hint":"character_identity"},'
                                '{"index":2,"role_hint":"pose_composition"}]}}'
                            ),
                        }
                    }
                ],
            }
        ],
    )

    assert decision.mode == "visual_agent_generation"
    assert decision.reference_resolution != "clarify_missing_reference"
    assert not decision.goal.blockers


def test_control_asks_clarification_for_ambiguous_unassigned_references():
    decision = build_raphael_control_decision(
        "用 ref1、ref2、ref3 做一張更好看的角色圖",
        attachments=["/tmp/ref1.png", "/tmp/ref2.png", "/tmp/ref3.png"],
    )

    assert decision.mode == "needs_clarification"
    assert decision.reference_resolution == "clarify_ambiguous_reference_roles"
    assert decision.route.handoff_tool is None
    assert "ref1/ref2/ref3" in decision.clarification_question
    assert decision.next_action == "ask_precise_clarification"


def test_control_allows_explicit_multi_candidate_reference_validation():
    decision = build_raphael_control_decision(
        "用 ref1、ref2、ref3 做一張角色圖，如果對應不確定就用多候選策略驗證",
        attachments=["/tmp/ref1.png", "/tmp/ref2.png", "/tmp/ref3.png"],
    )

    assert decision.mode == "visual_agent_generation"
    assert decision.reference_resolution == "multi_candidate_validation"
    assert "reference_mapping_evidence" in decision.evidence.required_proofs
    assert "multi_candidate_validation" in decision.evidence.required_proofs


def test_visual_failure_classifier_separates_provider_quality_delivery_and_browser_layers():
    assert classify_visual_failure_layer(
        {"provider_failure_classes": {"moderation_refusal": 1}}
    ) == "prompt_moderation"
    assert classify_visual_failure_layer(
        {"provider_failure_classes": {"quota_exhausted": 1}}
    ) == "provider_health"
    assert classify_visual_failure_layer(
        {"error": "candidate image did not pass artifact quality gate"}
    ) == "artifact_quality"
    assert classify_visual_failure_layer(
        {"delivery_recovery": {"status": "blocked", "blocked_modalities": ["image"]}}
    ) == "delivery"
    assert classify_visual_failure_layer(
        {"grok_web": {"doctor_status": "composer_not_ready"}}
    ) == "browser_automation"


def test_control_context_is_compact_and_does_not_expose_artifact_paths():
    decision = build_raphael_control_decision(
        "請用這張 reference 產出一張圖片",
        attachments=["/tmp/private-ref.png"],
    )

    context = render_raphael_control_context(decision)

    assert "Raphael Control Layer" in context
    assert "mode: visual_agent_generation" in context
    assert "next_action: call_visual_agent_generate" in context
    assert "/tmp/private-ref.png" not in context
