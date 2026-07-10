from __future__ import annotations

import json
import types

from agent.turn_finalizer import finalize_turn


class _FakeBudget:
    remaining = 10
    used = 0
    max_total = 10


class _FakeAgent:
    max_iterations = 20
    quiet_mode = True
    model = "grok-4.3"
    provider = "xai-oauth"
    base_url = "https://api.x.ai/v1"
    session_id = "sess-1"
    iteration_budget = _FakeBudget()
    session_input_tokens = 0
    session_output_tokens = 0
    session_cache_read_tokens = 0
    session_cache_write_tokens = 0
    session_reasoning_tokens = 0
    session_prompt_tokens = 0
    session_completion_tokens = 0
    session_total_tokens = 0
    session_estimated_cost_usd = 0.0
    session_cost_status = ""
    session_cost_source = ""
    context_compressor = types.SimpleNamespace(last_prompt_tokens=0)
    _tool_guardrail_halt_decision = None
    _response_was_previewed = False
    _interrupt_message = None
    _skill_nudge_interval = 0
    _iters_since_skill = 0
    valid_tool_names = set()
    _stream_callback = None

    def __init__(self):
        self.background_review_calls = []

    def _save_trajectory(self, *_args, **_kwargs):
        pass

    def _cleanup_task_resources(self, *_args, **_kwargs):
        pass

    def _drop_trailing_empty_response_scaffolding(self, *_args, **_kwargs):
        pass

    def _persist_session(self, *_args, **_kwargs):
        pass

    def _file_mutation_verifier_enabled(self):
        return False

    def _turn_completion_explainer_enabled(self):
        return False

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self):
        pass

    def _sync_external_memory_for_turn(self, **_kwargs):
        pass

    def _spawn_background_review(self, **kwargs):
        self.background_review_calls.append(kwargs)


class _FakeRaphaelEvidence:
    required_proofs = ("focused_tests", "runtime_smoke_when_live_wiring")


class _FakeRaphaelDecision:
    mode = "tool_task"
    evidence = _FakeRaphaelEvidence()

    def to_dict(self):
        return {
            "mode": self.mode,
            "evidence": {
                "required_proofs": list(self.evidence.required_proofs),
            },
        }


class _FakeVisualRaphaelDecision:
    mode = "visual_agent_generation"
    evidence = types.SimpleNamespace(
        required_proofs=(
            "direct_handoff_metadata",
            "provider_attempt_evidence",
            "artifact_quality_evidence",
            "selected_current_artifact_only",
        )
    )

    def to_dict(self):
        return {
            "mode": self.mode,
            "evidence": {
                "required_proofs": list(self.evidence.required_proofs),
            },
        }


def test_finalize_turn_applies_raphael_response_governor(monkeypatch):
    import agent.raphael.governor as governor

    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: f"{text}\nRaphael governed={enabled}",
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response="Line one",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "hi"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="hi",
        original_user_message="hi",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == "Line one\nRaphael governed=True"


def test_finalize_turn_preserves_story_video_validation_block_under_proof_gate(
    monkeypatch,
):
    import agent.raphael.control as control
    import agent.raphael.observer as observer
    import agent.raphael.proof as proof
    import agent.visual.agent_mode.handoff as handoff

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    monkeypatch.setattr(handoff, "is_visual_prompt_builder_request", lambda _text: False)
    monkeypatch.setattr(
        control,
        "build_raphael_control_decision",
        lambda *_args, **_kwargs: _FakeRaphaelDecision(),
    )
    monkeypatch.setattr(proof, "raphael_has_required_proof", lambda *_args, **_kwargs: False)

    response = (
        "檢查完成：BLOCKED\n"
        "阻塞原因：舊 v1 checklist 缺 render-contract evidence。\n"
        "下一步：migrate to v2 and rerender with structured render QC."
    )
    result = finalize_turn(
        _FakeAgent(),
        final_response=response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {
                "role": "tool",
                "name": "terminal",
                "content": (
                    '{"success": false, "output": "STORY_VIDEO_GATE: BLOCKED\\n'
                    'FAIL schema: v1 checklist cannot certify final after render-contract gates"}'
                ),
            }
        ],
        conversation_history=[],
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="只檢查 story-video 專案是否可以稱為 final",
        original_user_message="只檢查 story-video 專案是否可以稱為 final",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == response
    assert "Raphael proof gate" not in result["final_response"]


def test_finalize_turn_preserves_story_video_planning_only_scope_with_phase_proof(
    monkeypatch,
):
    import agent.raphael.control as control
    import agent.raphael.observer as observer
    import agent.raphael.proof as proof
    import agent.visual.agent_mode.handoff as handoff

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    monkeypatch.setattr(handoff, "is_visual_prompt_builder_request", lambda _text: False)
    monkeypatch.setattr(
        control,
        "build_raphael_control_decision",
        lambda *_args, **_kwargs: _FakeVisualRaphaelDecision(),
    )
    monkeypatch.setattr(proof, "raphael_has_required_proof", lambda *_args, **_kwargs: False)

    user_message = (
        "幫我做一部恐龍起源的科普影片（可用之前故事影片的 skill 或流程），"
        "圖片走真實照片風格，大概 5mins。先不要產圖或產影片，請先建立 "
        "project contract、storyboard、scene ledger、production checklist，"
        "確認會走 story-video workflow。"
    )
    response = (
        "已完成規劃文件：PROJECT_CONTRACT.md、storyboard.md、scene_ledger.json、"
        "production_checklist.json。\n下一步：故事影片下一步"
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response=response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": user_message},
            {
                "role": "tool",
                "name": "story_video_control",
                "content": (
                    '{"success": true, "proof": '
                    '"STORY_VIDEO_PHASE_PROOF: planning PASS"}'
                ),
            },
            {"role": "assistant", "content": response},
        ],
        conversation_history=[],
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message=user_message,
        original_user_message=user_message,
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == response
    assert "Raphael proof gate" not in result["final_response"]
    assert "visual_agent_generate" not in result["final_response"]
    assert "artifact_quality_evidence" not in result["final_response"]


def test_finalize_turn_requires_story_video_planning_phase_proof(
    monkeypatch,
):
    import agent.raphael.control as control
    import agent.raphael.observer as observer
    import agent.raphael.proof as proof
    import agent.visual.agent_mode.handoff as handoff

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    monkeypatch.setattr(handoff, "is_visual_prompt_builder_request", lambda _text: False)
    monkeypatch.setattr(
        control,
        "build_raphael_control_decision",
        lambda *_args, **_kwargs: _FakeVisualRaphaelDecision(),
    )
    monkeypatch.setattr(proof, "raphael_has_required_proof", lambda *_args, **_kwargs: False)

    user_message = (
        "故事影片：恐龍起源｜5min｜真實照片。先不要產圖或影片，先建立 "
        "project contract、storyboard、scene ledger、production checklist。"
    )
    response = "已完成規劃文件。"

    result = finalize_turn(
        _FakeAgent(),
        final_response=response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response},
        ],
        conversation_history=[],
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message=user_message,
        original_user_message=user_message,
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "故事影片 planning 尚未通過" in result["final_response"]
    assert "story_video_control(action=validate)" in result["final_response"]
    assert "visual_agent_generate" not in result["final_response"]


def test_finalize_turn_does_not_add_fixed_story_video_footer(
    monkeypatch,
):
    import agent.raphael.observer as observer
    import agent.visual.agent_mode.handoff as handoff

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: False)
    monkeypatch.setattr(handoff, "is_visual_prompt_builder_request", lambda _text: False)

    user_message = "故事影片：恐龍起源｜5min｜真實照片"
    response = "已建立 PROJECT_CONTRACT.md、storyboard.md、scene_ledger.json。"

    result = finalize_turn(
        _FakeAgent(),
        final_response=response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response},
        ],
        conversation_history=[],
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message=user_message,
        original_user_message=user_message,
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == response


def test_finalize_turn_records_visual_prompt_draft_in_prompt_arsenal(monkeypatch, tmp_path):
    import agent.visual.tracking as tracking
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.prompt_arsenal import approved_prompt_arsenal_entries

    ledger_path = tmp_path / "visual.sqlite3"
    monkeypatch.setattr(tracking, "default_visual_ledger_path", lambda: ledger_path)

    result = finalize_turn(
        _FakeAgent(),
        final_response=(
            "Use the uploaded references as a collective identity lock. "
            "Create a premium 2D anime key visual with intentional pose, "
            "refined sensual outfit design, clear light-source logic, and polished hands."
        ),
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {
                "role": "user",
                "content": "固定這位角色，替換不同服裝與構圖，高品質，請給我 prompt 就好，不須產圖",
            }
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="固定這位角色，替換不同服裝與構圖，高品質，請給我 prompt 就好，不須產圖",
        original_user_message="固定這位角色，替換不同服裝與構圖，高品質，請給我 prompt 就好，不須產圖",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "collective identity lock" in result["final_response"]
    ledger = VisualAttemptLedger(ledger_path)
    entries = approved_prompt_arsenal_entries(
        ledger,
        request_category="anime_character",
        limit=1,
    )
    assert len(entries) == 1
    assert "clear light-source logic" in entries[0]["prompt_mediated"]


def test_finalize_turn_does_not_record_visual_prompt_disclosure_as_prompt_draft(
    monkeypatch,
    tmp_path,
):
    import agent.visual.tracking as tracking
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger_path = tmp_path / "visual.sqlite3"
    monkeypatch.setattr(tracking, "default_visual_ledger_path", lambda: ledger_path)

    finalize_turn(
        _FakeAgent(),
        final_response="上一輪可追溯的 visual prompt 如下：\n\n實際送進 image/video provider 的 prompt：...",
        api_call_count=0,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "請給我你使用的 prompt"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請給我你使用的 prompt",
        original_user_message="請給我你使用的 prompt",
        _should_review_memory=False,
        _turn_exit_reason="visual_prompt_disclosure",
    )

    ledger = VisualAttemptLedger(ledger_path)
    ledger.initialize()
    assert ledger._list("visual_shadow_updates") == []


def test_finalize_turn_merges_visual_prompt_draft_negative_prompt_into_one_copy_block(
    monkeypatch,
    tmp_path,
):
    import agent.visual.tracking as tracking

    ledger_path = tmp_path / "visual.sqlite3"
    monkeypatch.setattr(tracking, "default_visual_ledger_path", lambda: ledger_path)

    result = finalize_turn(
        _FakeAgent(),
        final_response=(
            "Positive prompt:\n"
            "```text\n"
            "Premium 2D anime key visual, strict character identity lock, elegant fox-spirit woman, "
            "cinematic low-angle composition, refined silk outfit, warm lantern light and cool moon rim light.\n"
            "```\n\n"
            "Negative prompt:\n"
            "```text\n"
            "generic anime girl, bad hands, extra fingers, flat lighting, watermark, logo, text, cheap 3D render\n"
            "```"
        ),
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "幫我改 prompt，prompt 就好，不須產圖"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="幫我改 prompt，prompt 就好，不須產圖",
        original_user_message="幫我改 prompt，prompt 就好，不須產圖",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    response = result["final_response"]
    assert response.startswith("```text\n")
    assert response.count("```") == 2
    assert "Premium 2D anime key visual" in response
    assert "Negative prompt:" in response
    assert "bad hands" in response


def test_finalize_turn_keeps_visual_prompt_draft_focused_and_preserves_negative_prompt(
    monkeypatch,
    tmp_path,
):
    import agent.visual.tracking as tracking

    ledger_path = tmp_path / "visual.sqlite3"
    monkeypatch.setattr(tracking, "default_visual_ledger_path", lambda: ledger_path)
    long_positive = " ".join(
        f"ornamental detail layer {index}, cinematic lighting note {index}, fabric rendering cue {index};"
        for index in range(80)
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response=(
            "```text\n"
            f"{long_positive}\n"
            "Negative prompt: bad anatomy, bad hands, extra fingers, watermark, logo, text, cheap 3D render\n"
            "```"
        ),
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "請給我一版 prompt 就好，不須產圖"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請給我一版 prompt 就好，不須產圖",
        original_user_message="請給我一版 prompt 就好，不須產圖",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    prompt_text = result["final_response"].removeprefix("```text\n").removesuffix("\n```")
    assert len(prompt_text) <= 1200
    assert "Negative prompt:" in prompt_text
    assert "bad anatomy" in prompt_text


def test_finalize_turn_shapes_explicit_raphael_summon_response(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="我會處理。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "拉斐爾，分析這個 runtime 任務"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="拉斐爾，分析這個 runtime 任務",
        original_user_message="拉斐爾，分析這個 runtime 任務",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"].startswith("解析完成。")
    assert "局勢判讀" in result["final_response"]
    assert "並列推演" in result["final_response"]
    assert "最優路線" in result["final_response"]
    assert "我會處理。" in result["final_response"]
    assert "type=" not in result["final_response"]
    assert "risk=" not in result["final_response"]
    assert "focused_tests" not in result["final_response"]
    assert "plan_execute_verify" not in result["final_response"]


def test_finalize_turn_shapes_casual_raphael_summon_as_standby_prompt(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="在。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "拉斐爾？"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="拉斐爾？",
        original_user_message="拉斐爾？",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"].startswith("解析完成。")
    assert "狀態：Raphael 待命" in result["final_response"]
    assert "可接管：目標判讀、策略推演、證據驗證、演化提案" in result["final_response"]
    assert "請給我任務目標" in result["final_response"]
    assert "回應：\n在。" in result["final_response"]
    assert "目標：拉斐爾" not in result["final_response"]
    assert "局勢判讀" not in result["final_response"]
    assert "並列推演" not in result["final_response"]


def test_finalize_turn_preserves_explicit_three_line_raphael_summon_format(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    response = "\n".join(
        [
            "狀態：已喚醒；文字模式，禁止工具與產圖。",
            "可接管：可以；我會只做判讀、壓縮、決策建議。",
            "下一步：給我目標或現況，我直接切成最小可執行動作。",
        ]
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response=response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {
                "role": "user",
                "content": "拉斐爾？不要呼叫工具，不要產圖。請只回覆三行：狀態、可接管、下一步。",
            }
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="拉斐爾？不要呼叫工具，不要產圖。請只回覆三行：狀態、可接管、下一步。",
        original_user_message="拉斐爾？不要呼叫工具，不要產圖。請只回覆三行：狀態、可接管、下一步。",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == response
    assert "解析完成。" not in result["final_response"]
    assert "回應：" not in result["final_response"]
    assert len(result["final_response"].splitlines()) == 3


def test_finalize_turn_does_not_double_wrap_existing_standby_summon_response(
    monkeypatch,
):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    standby = "\n".join(
        [
            "解析完成。",
            "狀態：Raphael 待命；請給我任務目標。",
            "可接管：目標判讀、策略推演、證據驗證、演化提案。",
            "下一步：說出你要我接管的任務、artifact 或阻塞點。",
        ]
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response=standby,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "拉斐爾？"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="拉斐爾？",
        original_user_message="拉斐爾？",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == standby
    assert result["final_response"].count("解析完成。") == 1
    assert "回應：" not in result["final_response"]


def test_finalize_turn_preserves_raphael_summon_shape_after_governor(monkeypatch):
    import agent.raphael.governor as governor
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="下一步：先規劃，再執行，最後用證據驗證",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "拉斐爾，請分析這個 runtime bug"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="拉斐爾，請分析這個 runtime bug",
        original_user_message="拉斐爾，請分析這個 runtime bug",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"].startswith("解析完成。")
    assert "局勢判讀" in result["final_response"]
    assert "並列推演" in result["final_response"]
    assert "最優路線" in result["final_response"]
    assert "必要證據" in result["final_response"]
    assert "回應：" in result["final_response"]


def test_finalize_turn_keeps_full_raphael_summon_body_when_governor_enabled(monkeypatch):
    import agent.raphael.governor as governor
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="\n".join(
            [
                "局勢判讀：這是 runtime 文字分析。",
                "細節分析：這行是原始推理摘要，不能被治理器裁掉。",
                "必要證據：tool_call_count=0。",
                "下一步：保持 LLM-only。",
            ]
        ),
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "拉斐爾，請 LLM-only 分析 runtime bug"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="拉斐爾，請 LLM-only 分析 runtime bug",
        original_user_message="拉斐爾，請 LLM-only 分析 runtime bug",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"].startswith("解析完成。")
    assert "回應：" in result["final_response"]
    assert "細節分析：這行是原始推理摘要，不能被治理器裁掉。" in result["final_response"]
    assert "必要證據：tool_call_count=0。" in result["final_response"]
    assert "下一步：保持 LLM-only。" in result["final_response"]


def test_finalize_turn_schedules_raphael_evolution_review(monkeypatch):
    import agent.raphael.evolution as evolution
    import agent.raphael.skill_trace as skill_trace

    decision = evolution.RaphaelEvolutionDecision(
        should_review=True,
        review_skills=True,
        review_memory=False,
        proposal_only=False,
        mode="active_evolution",
        reason_codes=("user_correction",),
        evidence_summary="user corrected Raphael behavior",
        review_label="Raphael evolution review",
        risk_level="R1",
        user_message_preview="不對，要主動進化",
    )
    records = []
    traces = []

    monkeypatch.setattr(
        evolution,
        "decide_raphael_evolution",
        lambda **_kwargs: decision,
    )
    monkeypatch.setattr(
        evolution,
        "build_raphael_evolution_review_prompt",
        lambda _decision: "CUSTOM RAPHAEL EVOLUTION PROMPT",
    )
    monkeypatch.setattr(
        evolution,
        "append_evolution_record",
        lambda _decision, *, status, metadata=None: records.append(
            {"status": status, "metadata": metadata or {}}
        ),
    )
    monkeypatch.setattr(
        skill_trace,
        "append_skill_trace",
        lambda trace, **_kwargs: traces.append(trace),
    )

    agent = _FakeAgent()
    agent.valid_tool_names = {"skill_manage"}

    result = finalize_turn(
        agent,
        final_response="收到，我會修正",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "不對，要主動進化"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="不對，要主動進化",
        original_user_message="不對，要主動進化",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == "收到，我會修正"
    assert records == [
        {
            "status": "scheduled",
            "metadata": {
                "task_id": "task-1",
                "turn_id": "turn-1",
                "turn_exit_reason": "text_response",
            },
        }
    ]
    assert agent.background_review_calls == [
        {
            "messages_snapshot": result["messages"],
            "review_memory": False,
            "review_skills": True,
            "review_prompt": "CUSTOM RAPHAEL EVOLUTION PROMPT",
            "review_label": "Raphael evolution review",
        }
    ]
    assert len(traces) == 1
    assert traces[0].task_id == "task-1"
    assert traces[0].source == "raphael_evolution"
    assert traces[0].skills_used == ("raphael", "skill_manage")
    assert traces[0].outcome == "scheduled"
    assert traces[0].metadata["reason_codes"] == ["user_correction"]


def test_finalize_turn_records_raphael_background_review_spawn_failure(monkeypatch):
    import agent.raphael.evolution as evolution
    import agent.raphael.skill_trace as skill_trace

    decision = evolution.RaphaelEvolutionDecision(
        should_review=True,
        review_skills=True,
        review_memory=False,
        proposal_only=False,
        mode="active_evolution",
        reason_codes=("visual_or_provider_failure",),
        evidence_summary="failure layers: artifact_quality",
        review_label="Raphael evolution review",
        risk_level="R1",
        user_message_preview="生成圖片",
    )
    records = []
    traces = []

    monkeypatch.setattr(evolution, "decide_raphael_evolution", lambda **_kwargs: decision)
    monkeypatch.setattr(
        evolution,
        "build_raphael_evolution_review_prompt",
        lambda _decision: "CUSTOM RAPHAEL EVOLUTION PROMPT",
    )
    monkeypatch.setattr(
        evolution,
        "append_evolution_record",
        lambda _decision, *, status, metadata=None: records.append(
            {"status": status, "metadata": metadata or {}}
        ),
    )
    monkeypatch.setattr(
        skill_trace,
        "append_skill_trace",
        lambda trace, **_kwargs: traces.append(trace),
    )

    class FailingReviewAgent(_FakeAgent):
        def _spawn_background_review(self, **_kwargs):
            raise RuntimeError("review spawn failed")

    agent = FailingReviewAgent()
    agent.valid_tool_names = {"skill_manage"}

    result = finalize_turn(
        agent,
        final_response="視覺生成失敗：候選圖未通過。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "生成圖片"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="生成圖片",
        original_user_message="生成圖片",
        _should_review_memory=False,
        _turn_exit_reason="direct_visual_agent_handoff",
    )

    assert result["final_response"] == "視覺生成失敗：候選圖未通過。"
    assert [record["status"] for record in records] == [
        "scheduled",
        "background_spawn_failed",
    ]
    assert traces[-1].outcome == "background_spawn_failed"
    assert traces[-1].risk_incidents == ("visual_or_provider_failure",)


def test_finalize_turn_blocks_unverified_tool_task_completion_claim(monkeypatch):
    import agent.raphael.observer as observer
    import agent.raphael.state as raphael_state

    recorded = []
    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    monkeypatch.setattr(
        raphael_state,
        "record_control_decision",
        lambda decision, **kwargs: recorded.append((decision, kwargs)),
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response="已完成修復並驗證。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "請修復這個 runtime bug 並驗證"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復這個 runtime bug 並驗證",
        original_user_message="請修復這個 runtime bug 並驗證",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" in result["final_response"]
    assert "focused_tests" in result["final_response"]
    assert recorded
    decision = recorded[-1][0]
    assert decision["mode"] == "tool_task"
    assert decision["evidence"]["failure_layer"] == "proof_gate"


def test_finalize_turn_preserves_explicit_non_completion_tool_task_review(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    final_response = "不能宣稱完成：目前缺少 focused tests 與 runtime smoke。"

    result = finalize_turn(
        _FakeAgent(),
        final_response=final_response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請審查這個 runtime bug 是否可以宣稱完成"},
            {"role": "assistant", "content": final_response},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請審查這個 runtime bug 是否可以宣稱完成",
        original_user_message="請審查這個 runtime bug 是否可以宣稱完成",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == final_response


def test_finalize_turn_blocks_completion_claim_after_unrelated_tool_call(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="已完成修復並驗證。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復這個 runtime bug 並驗證"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}]},
            {"role": "tool", "name": "read_file", "content": "read README only"},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復這個 runtime bug 並驗證",
        original_user_message="請修復這個 runtime bug 並驗證",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" in result["final_response"]


def test_finalize_turn_blocks_completion_claim_when_read_file_mentions_tests(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="已完成修復並驗證。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復這個 runtime bug 並驗證"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}]},
            {
                "role": "tool",
                "name": "read_file",
                "content": "README says pytest passed in CI last week.",
            },
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復這個 runtime bug 並驗證",
        original_user_message="請修復這個 runtime bug 並驗證",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" in result["final_response"]


def test_finalize_turn_blocks_nameless_read_file_tool_result_mentions_tests(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="已完成修復並驗證。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復這個 runtime bug 並驗證"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "function": {"name": "read_file"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_read",
                "content": "README says pytest passed in CI last week.",
            },
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復這個 runtime bug 並驗證",
        original_user_message="請修復這個 runtime bug 並驗證",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" in result["final_response"]


def test_finalize_turn_blocks_assistant_text_mentions_tests_without_tool_proof(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="已完成修復並驗證。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復這個 runtime bug 並驗證"},
            {"role": "assistant", "content": "我看到 pytest passed，所以完成。"},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復這個 runtime bug 並驗證",
        original_user_message="請修復這個 runtime bug 並驗證",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" in result["final_response"]


def test_finalize_turn_blocks_runtime_completion_claim_without_runtime_smoke(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="已完成修復並驗證。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復這個 runtime bug 並驗證"},
            {
                "role": "tool",
                "name": "exec_command",
                "content": "venv/bin/python -m pytest tests/foo_test.py -q\n1 passed",
            },
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復這個 runtime bug 並驗證",
        original_user_message="請修復這個 runtime bug 並驗證",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" in result["final_response"]
    assert "runtime_smoke_when_live_wiring" in result["final_response"]


def test_finalize_turn_blocks_unverified_visual_completion_claim_when_handoff_not_used(
    monkeypatch,
):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="已產出圖片。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請產出一張圖片"},
            {"role": "assistant", "content": "已產出圖片。"},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請產出一張圖片",
        original_user_message="請產出一張圖片",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" in result["final_response"]
    assert "visual/artifact 任務" in result["final_response"]
    assert "artifact_quality_evidence" in result["final_response"]


def test_finalize_turn_preserves_visual_completion_when_image_tool_delivered(
    monkeypatch,
    tmp_path,
):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    image_path = tmp_path / "selected.png"
    image_path.write_bytes(b"png")

    result = finalize_turn(
        _FakeAgent(),
        final_response="已產出圖片。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "Use the two reference images to create an anime image"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-image",
                        "function": {"name": "image_generate"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-image",
                "name": "image_generate",
                "content": json.dumps(
                    {
                        "success": True,
                        "image": str(image_path),
                        "images": [str(image_path)],
                        "delivery_metadata": {
                            "selected_visual_artifact_ids": ["artifact-1"],
                        },
                    }
                ),
            },
            {"role": "assistant", "content": "已產出圖片。"},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="Use the two reference images to create an anime image",
        original_user_message="Use the two reference images to create an anime image",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == "已產出圖片。"


def test_finalize_turn_does_not_proof_gate_visual_prompt_builder_response(
    monkeypatch,
    tmp_path,
):
    import agent.raphael.observer as observer
    import agent.visual.tracking as tracking

    ledger_path = tmp_path / "visual.sqlite3"
    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    monkeypatch.setattr(tracking, "default_visual_ledger_path", lambda: ledger_path)
    user_message = "你看，很普，請給我改進的 prompt"
    final_response = (
        "已完成改進 prompt：\n"
        "```text\n"
        "Character: fixed adult anime heroine identity from references. "
        "Pose: dynamic contrapposto, torso twist, hip tilt, off-axis low-angle three-quarter camera. "
        "Lighting: warm key light, cool rim light, layered cast shadows. "
        "Outfit: specific seductive glossy corset dress with high slit and tasteful adult coverage. "
        "Negative prompt: rough sketch, stiff pose, flat lighting, bad hands, loli, nude, watermark.\n"
        "```"
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response=final_response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": final_response},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message=user_message,
        original_user_message=user_message,
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "還不能判定完成" not in result["final_response"]
    assert "artifact_quality_evidence" not in result["final_response"]
    assert result["final_response"].startswith("```text\n")
    assert "dynamic contrapposto" in result["final_response"]
    assert "Negative prompt:" in result["final_response"]


def test_finalize_turn_preserves_text_only_public_raphael_copy_review(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)
    user_message = (
        "同一個 hostile UX 測試，現在模擬真實文字任務：我要公開 Raphael，"
        "但又怕 overclaim；我要使用者 wow，但不能產圖、不能用工具、不能假綠燈。"
        "請只用六行回答：目標、成功條件、證據門檻、阻塞、修正策略、可公開說法。"
        "不要宣稱已完成。"
    )
    final_response = "\n".join(
        [
            "目標：公開 Raphael，但避免 overclaim。",
            "成功條件：使用者看得懂能力邊界，且不需要工具或產圖。",
            "證據門檻：只用已驗證的 LLM-only hostile UX 證據。",
            "阻塞：現在不能宣稱完成。",
            "修正策略：補回歸測試與 live smoke，再更新可公開說法。",
            "可公開說法：Raphael 是正在強化的控制層，不是已全能的終局。",
        ]
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response=final_response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": final_response},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message=user_message,
        original_user_message=user_message,
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == final_response
    assert "visual_agent_generate" not in result["final_response"]
    assert "artifact_quality_evidence" not in result["final_response"]
    assert "direct_handoff_metadata" not in result["final_response"]


def test_finalize_turn_allows_completion_claim_with_all_required_evidence(monkeypatch):
    import agent.raphael.observer as observer

    monkeypatch.setattr(observer, "should_inject_raphael_observation", lambda: True)

    result = finalize_turn(
        _FakeAgent(),
        final_response="已完成修復並驗證。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復這個 runtime bug 並驗證"},
                {
                    "role": "tool",
                    "name": "exec_command",
                    "exit_code": 0,
                    "content": "venv/bin/python -m pytest tests/foo_test.py -q\n1 passed",
                },
                {
                    "role": "tool",
                    "name": "exec_command",
                    "exit_code": 0,
                    "content": "hermes gateway status\nservice loaded, pid 123, running",
                },
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復這個 runtime bug 並驗證",
        original_user_message="請修復這個 runtime bug 並驗證",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == "已完成修復並驗證。"
