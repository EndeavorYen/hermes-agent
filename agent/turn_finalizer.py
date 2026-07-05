"""Post-loop turn finalization for ``run_conversation``.

Extracted from ``agent/conversation_loop.py`` as part of the god-file
decomposition campaign (``~/.hermes/plans/god-file-decomposition.md``, Phase 1
step 4 — the post-loop ``TurnFinalizer`` seam). ``run_conversation``'s tail
(everything after the main tool-calling ``while`` loop) is lifted here verbatim:
budget-exhaustion summary, trajectory save, session persist, turn diagnostics,
response transforms, result-dict assembly, steer drain, and the memory/skill
review trigger.

Behavior-neutral: the body is moved unchanged. All ``agent.*`` side effects fire
exactly as before; only the post-loop *locals* are passed in as keyword args, and
the assembled ``result`` dict is returned to ``run_conversation`` which returns it
to the caller. The function is synchronous with a single return — mirroring the
region it replaces (no awaits, no early returns).

Module ``logger`` is imported lazily inside the body (``from
agent.conversation_loop import logger``) so this module never imports
``agent.conversation_loop`` at import time -> no import cycle, and the log records
keep the exact logger name (``"agent.conversation_loop"``).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from agent.codex_responses_adapter import _summarize_user_message_for_log

_VISUAL_PROMPT_DRAFT_MAX_CHARS = 1200
_FENCED_BLOCK_RE = re.compile(
    r"```(?:[a-zA-Z0-9_-]+)?[ \t]*\n?(.*?)```",
    flags=re.DOTALL,
)


def finalize_turn(
    agent,
    *,
    final_response,
    api_call_count,
    interrupted,
    failed,
    messages,
    conversation_history,
    effective_task_id,
    turn_id,
    user_message,
    original_user_message,
    _should_review_memory,
    _turn_exit_reason,
):
    """Run the post-loop finalization and return the turn ``result`` dict.

    Lifted verbatim from ``run_conversation`` (the region after the main agent
    loop). See module docstring.
    """
    from agent.conversation_loop import logger

    if final_response is None and (
        api_call_count >= agent.max_iterations
        or agent.iteration_budget.remaining <= 0
    ):
        # Budget exhausted — ask the model for a summary via one extra
        # API call with tools stripped.  _handle_max_iterations injects a
        # user message and makes a single toolless request.
        _turn_exit_reason = f"max_iterations_reached({api_call_count}/{agent.max_iterations})"
        agent._emit_status(
            f"⚠️ Iteration budget exhausted ({api_call_count}/{agent.max_iterations}) "
            "— asking model to summarise"
        )
        if not agent.quiet_mode:
            agent._safe_print(
                f"\n⚠️  Iteration budget exhausted ({api_call_count}/{agent.max_iterations}) "
                "— requesting summary..."
            )
        final_response = agent._handle_max_iterations(messages, api_call_count)

        # If running as a kanban worker, signal the dispatcher that the
        # worker could not complete (rather than treating it as a
        # protocol violation).  The agent loop strips tools before calling
        # _handle_max_iterations, so the model cannot call kanban_block
        # itself — we must do it on its behalf.
        #
        # We route through ``_record_task_failure(outcome="timed_out")``
        # rather than ``kanban_block`` so this counts toward the
        # ``consecutive_failures`` counter and the dispatcher's
        # ``failure_limit`` circuit breaker (#29747 gap 2).  Without this,
        # a task whose worker keeps exhausting its budget would block
        # silently each run, get auto-promoted by the operator (or never
        # surface), and re-block in an endless loop with no signal.
        _kanban_task = os.environ.get("HERMES_KANBAN_TASK")
        if _kanban_task:
            try:
                from hermes_cli import kanban_db as _kb
                _conn = _kb.connect()
                try:
                    _kb._record_task_failure(
                        _conn,
                        _kanban_task,
                        error=(
                            f"Iteration budget exhausted "
                            f"({api_call_count}/{agent.max_iterations}) — "
                            "task could not complete within the allowed "
                            "iterations"
                        ),
                        outcome="timed_out",
                        release_claim=True,
                        end_run=True,
                        event_payload_extra={
                            "budget_used": api_call_count,
                            "budget_max": agent.max_iterations,
                        },
                    )
                    logger.info(
                        "recorded budget-exhausted failure for task %s (%d/%d)",
                        _kanban_task, api_call_count, agent.max_iterations,
                    )
                finally:
                    try:
                        _conn.close()
                    except Exception:
                        pass
            except Exception:
                logger.warning(
                    "Failed to record budget-exhausted failure for task %s",
                    _kanban_task,
                    exc_info=True,
                )

    # Determine if conversation completed successfully
    completed = (
        final_response is not None
        and api_call_count < agent.max_iterations
        and not failed
    )

    # Save trajectory if enabled.  ``user_message`` may be a multimodal
    # list of parts; the trajectory format wants a plain string.
    agent._save_trajectory(messages, _summarize_user_message_for_log(user_message), completed)

    # Clean up VM and browser for this task after conversation completes
    agent._cleanup_task_resources(effective_task_id)

    # Persist session to both JSON log and SQLite only after private retry
    # scaffolding has been removed. Otherwise a later user "continue" turn
    # can replay assistant("(empty)") / recovery nudges and fall into the
    # same empty-response loop again.
    agent._drop_trailing_empty_response_scaffolding(messages)
    agent._persist_session(messages, conversation_history)

    # ── Turn-exit diagnostic log ─────────────────────────────────────
    # Always logged at INFO so agent.log captures WHY every turn ended.
    # When the last message is a tool result (agent was mid-work), log
    # at WARNING — this is the "just stops" scenario users report.
    _last_msg_role = messages[-1].get("role") if messages else None
    _last_tool_name = None
    if _last_msg_role == "tool":
        # Walk back to find the assistant message with the tool call
        for _m in reversed(messages):
            if _m.get("role") == "assistant" and _m.get("tool_calls"):
                _tcs = _m["tool_calls"]
                if _tcs and isinstance(_tcs[0], dict):
                    _last_tool_name = _tcs[-1].get("function", {}).get("name")
                break

    _turn_tool_count = sum(
        1 for m in messages
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls")
    )
    _resp_len = len(final_response) if final_response else 0
    _budget_used = agent.iteration_budget.used if agent.iteration_budget else 0
    _budget_max = agent.iteration_budget.max_total if agent.iteration_budget else 0

    _diag_msg = (
        "Turn ended: reason=%s model=%s api_calls=%d/%d budget=%d/%d "
        "tool_turns=%d last_msg_role=%s response_len=%d session=%s"
    )
    _diag_args = (
        _turn_exit_reason, agent.model, api_call_count, agent.max_iterations,
        _budget_used, _budget_max,
        _turn_tool_count, _last_msg_role, _resp_len,
        agent.session_id or "none",
    )

    if _last_msg_role == "tool" and not interrupted:
        # Agent was mid-work — this is the "just stops" case.
        logger.warning(
            "Turn ended with pending tool result (agent may appear stuck). "
            + _diag_msg + " last_tool=%s",
            *_diag_args, _last_tool_name,
        )
    else:
        logger.info(_diag_msg, *_diag_args)

    # File-mutation verifier footer.
    # If one or more ``write_file`` / ``patch`` calls failed during this
    # turn and were never superseded by a successful write to the same
    # path, append an advisory footer to the assistant response.  This
    # catches the specific case — reported by Ben Eng (#15524-adjacent)
    # — where a model issues a batch of parallel patches, half of them
    # fail with "Could not find old_string", and the model summarises
    # the turn claiming every file was edited.  The user then has to
    # manually run ``git status`` to catch the lie.  With this footer
    # the truth is surfaced on every turn, so over-claiming is
    # structurally impossible past the model.
    #
    # Gate: only applied when a real text response exists for this
    # turn and the user didn't interrupt.  Empty/interrupted turns
    # already have other surface text that shouldn't be augmented.
    if final_response and not interrupted:
        try:
            _failed = getattr(agent, "_turn_failed_file_mutations", None) or {}
            if _failed and agent._file_mutation_verifier_enabled():
                footer = agent._format_file_mutation_failure_footer(_failed)
                if footer:
                    final_response = final_response.rstrip() + "\n\n" + footer
        except Exception as _ver_err:
            logger.debug("file-mutation verifier footer failed: %s", _ver_err)

    # Turn-completion explainer.
    # When a turn ends abnormally after substantive work — empty content
    # after retries, a partial/truncated stream, a still-pending tool
    # result, or an iteration/budget limit — the user otherwise gets a
    # blank or fragmentary response box with no consolidated reason why
    # the agent stopped (#34452).  Surface a single user-visible
    # explanation derived from ``_turn_exit_reason``, mirroring the
    # file-mutation verifier footer pattern above.
    #
    # Gate carefully so healthy turns stay quiet:
    #   - ``text_response(...)`` exits never produce an explanation
    #     (handled inside the formatter), so a terse ``Done.`` is silent.
    #   - We only ACT when there is no genuinely usable reply this turn:
    #     an empty response, the "(empty)" terminal sentinel, or a
    #     suspiciously short partial fragment with no terminating
    #     punctuation (e.g. "The").  A real short answer keeps its text.
    if not interrupted:
        try:
            if agent._turn_completion_explainer_enabled():
                _stripped = (final_response or "").strip()
                _is_empty_terminal = _stripped == "" or _stripped == "(empty)"
                # A short fragment that is not a normal text_response exit
                # and lacks sentence-ending punctuation is treated as a
                # truncated partial (the "The" case from #34452).
                _is_partial_fragment = (
                    not _is_empty_terminal
                    and not str(_turn_exit_reason).startswith("text_response")
                    and len(_stripped) <= 24
                    and _stripped[-1:] not in {".", "!", "?", "。", "！", "？", "`", ")"}
                )
                if _is_empty_terminal or _is_partial_fragment:
                    _explanation = agent._format_turn_completion_explanation(
                        _turn_exit_reason
                    )
                    if _explanation:
                        if _is_empty_terminal:
                            # Replace the bare "(empty)"/blank sentinel with
                            # the actionable explanation.
                            final_response = _explanation
                        else:
                            # Keep the partial fragment, append the reason so
                            # the user sees both what arrived and why it
                            # stopped.
                            final_response = (
                                _stripped + "\n\n" + _explanation
                            )
        except Exception as _exp_err:
            logger.debug("turn-completion explainer failed: %s", _exp_err)

    _response_transformed = False

    # Plugin hook: transform_llm_output
    # Fired once per turn after the tool-calling loop completes.
    # Plugins can transform the LLM's output text before it's returned.
    # First hook to return a string wins; None/empty return leaves text unchanged.
    if final_response and not interrupted:
        try:
            from hermes_cli.plugins import invoke_hook as _invoke_hook
            _transform_results = _invoke_hook(
                "transform_llm_output",
                response_text=final_response,
                session_id=agent.session_id or "",
                model=agent.model,
                platform=getattr(agent, "platform", None) or "",
            )
            for _hook_result in _transform_results:
                if isinstance(_hook_result, str) and _hook_result:
                    final_response = _hook_result
                    _response_transformed = True
                    break  # First non-empty string wins
        except Exception as exc:
            logger.warning("transform_llm_output hook failed: %s", exc)

    if final_response and not interrupted:
        try:
            final_response = _apply_raphael_general_proof_gate(
                final_response,
                user_message=original_user_message,
                messages=messages,
                conversation_history=conversation_history,
                turn_id=turn_id,
                task_id=effective_task_id,
            )
        except Exception as exc:
            logger.debug("Raphael general proof gate skipped: %s", exc)

    if final_response and not interrupted:
        try:
            from agent.raphael.governor import (
                apply_raphael_response_governor,
                should_apply_raphael_response_governor,
            )

            if not _is_explicit_raphael_invocation(original_user_message):
                final_response = apply_raphael_response_governor(
                    final_response,
                    enabled=should_apply_raphael_response_governor(),
                )
        except Exception as exc:
            logger.warning("Raphael response governor failed: %s", exc)

    if final_response and not interrupted:
        try:
            final_response = _apply_raphael_invocation_response_shape(
                final_response,
                user_message=original_user_message,
                conversation_history=conversation_history,
            )
        except Exception as exc:
            logger.debug("Raphael invocation response shaping skipped: %s", exc)

    if final_response and not interrupted and completed:
        try:
            final_response = _apply_visual_prompt_draft_response_shape(
                final_response,
                user_message=original_user_message,
            )
        except Exception as exc:
            logger.debug("visual prompt draft response shaping skipped: %s", exc)

    if final_response and not interrupted and completed:
        try:
            _maybe_record_visual_prompt_draft_arsenal(
                agent,
                user_message=original_user_message,
                final_response=final_response,
            )
        except Exception as exc:
            logger.debug("visual prompt draft arsenal recording skipped: %s", exc)

    # Plugin hook: post_llm_call
    # Fired once per turn after the tool-calling loop completes.
    # Plugins can use this to persist conversation data (e.g. sync
    # to an external memory system).
    if final_response and not interrupted:
        try:
            from hermes_cli.plugins import invoke_hook as _invoke_hook
            _invoke_hook(
                "post_llm_call",
                session_id=agent.session_id,
                task_id=effective_task_id,
                turn_id=turn_id,
                user_message=original_user_message,
                assistant_response=final_response,
                conversation_history=list(messages),
                model=agent.model,
                platform=getattr(agent, "platform", None) or "",
            )
        except Exception as exc:
            logger.warning("post_llm_call hook failed: %s", exc)

    # Extract reasoning from the CURRENT turn only.  Walk backwards
    # but stop at the user message that started this turn — anything
    # earlier is from a prior turn and must not leak into the reasoning
    # box (confusing stale display; #17055).  Within the current turn
    # we still want the *most recent* non-empty reasoning: many
    # providers (Claude thinking, DeepSeek v4, Codex Responses) emit
    # reasoning on the tool-call step and leave the final-answer step
    # with reasoning=None, so picking only the last assistant would
    # silently drop legitimate same-turn reasoning.
    last_reasoning = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            break  # turn boundary — don't cross into prior turns
        if msg.get("role") == "assistant" and msg.get("reasoning"):
            last_reasoning = msg["reasoning"]
            break

    # Build result with interrupt info if applicable
    result = {
        "final_response": final_response,
        "last_reasoning": last_reasoning,
        "messages": messages,
        "api_calls": api_call_count,
        "completed": completed,
        "turn_exit_reason": _turn_exit_reason,
        "failed": failed,
        "partial": False,  # True only when stopped due to invalid tool calls
        "interrupted": interrupted,
        "response_transformed": _response_transformed,
        "response_previewed": getattr(agent, "_response_was_previewed", False),
        "model": agent.model,
        "provider": agent.provider,
        "base_url": agent.base_url,
        "input_tokens": agent.session_input_tokens,
        "output_tokens": agent.session_output_tokens,
        "cache_read_tokens": agent.session_cache_read_tokens,
        "cache_write_tokens": agent.session_cache_write_tokens,
        "reasoning_tokens": agent.session_reasoning_tokens,
        "prompt_tokens": agent.session_prompt_tokens,
        "completion_tokens": agent.session_completion_tokens,
        "total_tokens": agent.session_total_tokens,
        "last_prompt_tokens": getattr(agent.context_compressor, "last_prompt_tokens", 0) or 0,
        "estimated_cost_usd": agent.session_estimated_cost_usd,
        "cost_status": agent.session_cost_status,
        "cost_source": agent.session_cost_source,
        "session_id": agent.session_id,
    }
    if agent._tool_guardrail_halt_decision is not None:
        result["guardrail"] = agent._tool_guardrail_halt_decision.to_metadata()
    # If a /steer landed after the final assistant turn (no more tool
    # batches to drain into), hand it back to the caller so it can be
    # delivered as the next user turn instead of being silently lost.
    _leftover_steer = agent._drain_pending_steer()
    if _leftover_steer:
        result["pending_steer"] = _leftover_steer
    agent._response_was_previewed = False

    # Include interrupt message if one triggered the interrupt
    if interrupted and agent._interrupt_message:
        result["interrupt_message"] = agent._interrupt_message

    # Clear interrupt state after handling
    agent.clear_interrupt()

    # Clear stream callback so it doesn't leak into future calls
    agent._stream_callback = None

    # Check skill trigger NOW — based on how many tool iterations THIS turn used.
    _should_review_skills = False
    if (agent._skill_nudge_interval > 0
            and agent._iters_since_skill >= agent._skill_nudge_interval
            and "skill_manage" in agent.valid_tool_names):
        _should_review_skills = True
        agent._iters_since_skill = 0

    _review_prompt = None
    _review_label = None
    _raphael_evolution = None
    _evolution_metadata = None
    if final_response and not interrupted:
        try:
            from hermes_cli.config import load_config
            from agent.raphael.evolution import (
                append_evolution_record,
                build_raphael_evolution_review_prompt,
                decide_raphael_evolution,
            )
            from agent.raphael.models import SkillTrace
            from agent.raphael.skill_trace import append_skill_trace

            _raphael_evolution = decide_raphael_evolution(
                user_message=original_user_message,
                final_response=final_response,
                messages=messages,
                turn_exit_reason=_turn_exit_reason,
                config=load_config(),
            )
            _evolution_metadata = {
                "task_id": effective_task_id,
                "turn_id": turn_id,
                "turn_exit_reason": _turn_exit_reason,
            }
            if _raphael_evolution.should_review:
                append_evolution_record(
                    _raphael_evolution,
                    status="scheduled",
                    metadata=_evolution_metadata,
                )
                append_skill_trace(
                    SkillTrace(
                        trace_id=f"raphael-evolution-{turn_id}",
                        task_id=str(effective_task_id or ""),
                        created_at=datetime.now(timezone.utc),
                        source="raphael_evolution",
                        skills_used=tuple(
                            skill
                            for skill in (
                                "raphael",
                                "skill_manage" if _raphael_evolution.review_skills else "",
                                "memory" if _raphael_evolution.review_memory else "",
                            )
                            if skill
                        ),
                        tools_used=tuple(
                            tool
                            for tool in (
                                "skill_manage" if _raphael_evolution.review_skills else "",
                                "memory" if _raphael_evolution.review_memory else "",
                            )
                            if tool
                        ),
                        outcome="scheduled",
                        user_corrections=tuple(_raphael_evolution.reason_codes),
                        risk_incidents=(),
                        metadata={
                            "mode": _raphael_evolution.mode,
                            "reason_codes": list(_raphael_evolution.reason_codes),
                            "evidence_summary": _raphael_evolution.evidence_summary,
                            "turn_exit_reason": _turn_exit_reason,
                        },
                    ),
                    max_string_length=500,
                )
                _should_review_memory = (
                    _should_review_memory or _raphael_evolution.review_memory
                )
                _should_review_skills = (
                    _should_review_skills or _raphael_evolution.review_skills
                )
                _review_prompt = build_raphael_evolution_review_prompt(
                    _raphael_evolution
                )
                _review_label = _raphael_evolution.review_label
            elif _raphael_evolution.proposal_only:
                append_evolution_record(
                    _raphael_evolution,
                    status="proposal_only",
                    metadata=_evolution_metadata,
                )
                append_skill_trace(
                    SkillTrace(
                        trace_id=f"raphael-evolution-{turn_id}",
                        task_id=str(effective_task_id or ""),
                        created_at=datetime.now(timezone.utc),
                        source="raphael_evolution",
                        skills_used=("raphael",),
                        tools_used=(),
                        outcome="proposal_only",
                        user_corrections=(),
                        risk_incidents=tuple(_raphael_evolution.reason_codes),
                        metadata={
                            "mode": _raphael_evolution.mode,
                            "reason_codes": list(_raphael_evolution.reason_codes),
                            "evidence_summary": _raphael_evolution.evidence_summary,
                            "turn_exit_reason": _turn_exit_reason,
                        },
                    ),
                    max_string_length=500,
                )
        except Exception as exc:
            logger.debug("Raphael evolution scheduling skipped: %s", exc)

    # External memory provider: sync the completed turn + queue next prefetch.
    agent._sync_external_memory_for_turn(
        original_user_message=original_user_message,
        final_response=final_response,
        interrupted=interrupted,
        messages=messages,
    )

    # Background memory/skill review — runs AFTER the response is delivered
    # so it never competes with the user's task for model attention.
    if final_response and not interrupted and (_should_review_memory or _should_review_skills):
        try:
            agent._spawn_background_review(
                messages_snapshot=list(messages),
                review_memory=_should_review_memory,
                review_skills=_should_review_skills,
                review_prompt=_review_prompt,
                review_label=_review_label,
            )
        except Exception as exc:
            logger.debug("Background review spawn failed: %s", exc)
            if _raphael_evolution is not None and _evolution_metadata is not None:
                try:
                    from agent.raphael.evolution import append_evolution_record
                    from agent.raphael.models import SkillTrace
                    from agent.raphael.skill_trace import append_skill_trace

                    append_evolution_record(
                        _raphael_evolution,
                        status="background_spawn_failed",
                        metadata={
                            **_evolution_metadata,
                            "error": str(exc),
                        },
                    )
                    append_skill_trace(
                        SkillTrace(
                            trace_id=f"raphael-evolution-spawn-failed-{turn_id}",
                            task_id=str(effective_task_id or ""),
                            created_at=datetime.now(timezone.utc),
                            source="raphael_evolution",
                            skills_used=("raphael",),
                            tools_used=(),
                            outcome="background_spawn_failed",
                            user_corrections=(),
                            risk_incidents=tuple(_raphael_evolution.reason_codes),
                            metadata={
                                "mode": _raphael_evolution.mode,
                                "reason_codes": list(_raphael_evolution.reason_codes),
                                "turn_exit_reason": _turn_exit_reason,
                                "error": str(exc),
                            },
                        ),
                        max_string_length=500,
                    )
                except Exception as record_exc:
                    logger.debug(
                        "Raphael background review failure recording skipped: %s",
                        record_exc,
                    )

    # Note: Memory provider on_session_end() + shutdown_all() are NOT
    # called here — run_conversation() is called once per user message in
    # multi-turn sessions. Shutting down after every turn would kill the
    # provider before the second message. Actual session-end cleanup is
    # handled by the CLI (atexit / /reset) and gateway (session expiry /
    # _reset_session).

    # Plugin hook: on_session_end
    # Fired at the very end of every run_conversation call.
    # Plugins can use this for cleanup, flushing buffers, etc.
    try:
        from hermes_cli.plugins import invoke_hook as _invoke_hook
        _invoke_hook(
            "on_session_end",
            session_id=agent.session_id,
            task_id=effective_task_id,
            turn_id=turn_id,
            completed=completed,
            interrupted=interrupted,
            model=agent.model,
            platform=getattr(agent, "platform", None) or "",
        )
    except Exception as exc:
        logger.warning("on_session_end hook failed: %s", exc)

    return result


def _apply_raphael_general_proof_gate(
    final_response,
    *,
    user_message,
    messages,
    conversation_history,
    turn_id,
    task_id,
):
    from agent.raphael.control import build_raphael_control_decision
    from agent.raphael.observer import should_inject_raphael_observation
    from agent.raphael.proof import raphael_has_required_proof
    from agent.visual.agent_mode.handoff import is_visual_prompt_builder_request

    if not should_inject_raphael_observation():
        return final_response
    prompt_text = _plain_text_for_visual_prompt_learning(user_message)
    if is_visual_prompt_builder_request(prompt_text):
        return final_response
    decision = build_raphael_control_decision(
        user_message,
        conversation_history=conversation_history,
    )
    is_visual_task = str(decision.mode).startswith("visual_agent")
    if decision.mode != "tool_task" and not is_visual_task:
        return final_response
    if not _raphael_claims_completion(final_response):
        return final_response
    required = decision.evidence.required_proofs or ()
    if raphael_has_required_proof(messages, required):
        return final_response

    decision_payload = decision.to_dict()
    evidence = dict(decision_payload.get("evidence") or {})
    evidence["failure_layer"] = "artifact_quality" if is_visual_task else "proof_gate"
    evidence["next_repair_action"] = "run_required_proofs_before_completion_claim"
    decision_payload["evidence"] = evidence
    decision_payload["next_action"] = "run_required_proofs_before_completion_claim"
    try:
        from agent.raphael.state import record_control_decision

        record_control_decision(
            decision_payload,
            turn_id=turn_id,
            task_id=task_id,
            source="general_tool_proof_gate",
        )
    except Exception:
        pass
    required_text = ", ".join(str(item) for item in required) or "verification evidence"
    risk_text = (
        "這是 visual/artifact 任務，但目前缺少 "
        if is_visual_task
        else "這是工具/runtime 任務，但目前缺少 "
    )
    next_step = (
        "先透過 visual_agent_generate 或等效 handoff 產出目前選中 artifact，"
        "再回報 artifact quality、selection、delivery 證據。"
        if is_visual_task
        else "先執行必要測試或 runtime smoke，再回報具體證據。"
    )
    return "\n".join(
        [
            "狀態：還不能判定完成，Raphael proof gate 沒看到足夠證據。",
            f"風險：{risk_text}{required_text}。",
            f"下一步：{next_step}",
        ]
    )


def _apply_visual_prompt_draft_response_shape(
    final_response,
    *,
    user_message,
):
    prompt = _plain_text_for_visual_prompt_learning(user_message)
    if not prompt:
        return final_response
    from agent.visual.agent_mode.handoff import is_visual_prompt_builder_request

    if not is_visual_prompt_builder_request(prompt):
        return final_response
    copy_text = _extract_visual_prompt_copy_text(str(final_response or ""))
    if not copy_text:
        return final_response
    focused = _limit_visual_prompt_draft_text(copy_text)
    return f"```text\n{focused}\n```"


def _extract_visual_prompt_copy_text(response_text: str) -> str:
    text = str(response_text or "").strip()
    if not text:
        return ""
    matches = list(_FENCED_BLOCK_RE.finditer(text))
    if not matches:
        return _clean_visual_prompt_copy_text(text)

    blocks: list[str] = []
    for match in matches:
        block = _clean_visual_prompt_copy_text(match.group(1))
        if not block:
            continue
        prefix = text[max(0, match.start() - 120):match.start()]
        if _looks_like_negative_prompt_label(prefix) and not _starts_with_negative_prompt_label(block):
            block = "Negative prompt: " + block
        blocks.append(block)
    return _clean_visual_prompt_copy_text("\n".join(blocks))


def _clean_visual_prompt_copy_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"^\s*(?:positive\s+prompt|正面\s*prompt|正面提示詞|正面提示词)\s*[:：]\s*", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _looks_like_negative_prompt_label(value: str) -> bool:
    lowered = str(value or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    return any(
        marker in lowered
        for marker in ("negative prompt", "negative constraints", "negative:")
    ) or any(marker in compact for marker in ("負面prompt", "負面提示詞", "負面提示词", "反向提示詞", "反向提示词"))


def _starts_with_negative_prompt_label(value: str) -> bool:
    text = str(value or "").strip().lower()
    compact = re.sub(r"\s+", "", text)
    return text.startswith(("negative prompt", "negative constraints", "negative:")) or compact.startswith(
        ("負面prompt", "負面提示詞", "負面提示词", "反向提示詞", "反向提示词")
    )


def _limit_visual_prompt_draft_text(
    value: str,
    *,
    max_chars: int = _VISUAL_PROMPT_DRAFT_MAX_CHARS,
) -> str:
    text = _clean_visual_prompt_copy_text(value)
    if len(text) <= max_chars:
        return text

    marker = _negative_prompt_marker(text)
    if marker is None:
        return _truncate_prompt_text(text, max_chars)

    positive = text[: marker.start()].strip()
    negative = text[marker.start():].strip()
    negative_limit = min(420, max_chars // 2)
    negative = _truncate_prompt_text(negative, negative_limit) if len(negative) > negative_limit else negative
    positive_limit = max(240, max_chars - len(negative) - 2)
    positive = _truncate_prompt_text(positive, positive_limit)
    return (positive + "\n" + negative).strip()


def _negative_prompt_marker(value: str) -> re.Match[str] | None:
    return re.search(
        r"(?im)(?:^|\n)\s*(?:negative\s+prompt|negative\s+constraints|negative|負面\s*prompt|負面提示詞|負面提示词|反向提示詞|反向提示词)\s*[:：]",
        value,
    )


def _truncate_prompt_text(value: str, max_chars: int) -> str:
    text = _clean_visual_prompt_copy_text(value)
    if len(text) <= max_chars:
        return text
    clipped = text[:max(0, max_chars)].rstrip()
    boundary_floor = max(0, int(max_chars * 0.55))
    boundary = max(
        clipped.rfind(separator, boundary_floor)
        for separator in ("。", "；", ";", ".", "，", ",", "\n")
    )
    if boundary > boundary_floor:
        clipped = clipped[:boundary].rstrip()
    return clipped.rstrip(" ,，;；")


def _maybe_record_visual_prompt_draft_arsenal(
    agent,
    *,
    user_message,
    final_response,
) -> None:
    prompt = _plain_text_for_visual_prompt_learning(user_message)
    if not prompt:
        return
    from agent.visual.agent_mode.handoff import is_visual_prompt_builder_request

    if not is_visual_prompt_builder_request(prompt):
        return
    from agent.visual import tracking as _visual_tracking
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.prompt_arsenal import record_prompt_draft_arsenal_entry

    ledger = VisualAttemptLedger(_visual_tracking.default_visual_ledger_path())
    record_prompt_draft_arsenal_entry(
        ledger,
        user_prompt=prompt,
        prompt_response=str(final_response or ""),
        platform=str(getattr(agent, "platform", "") or ""),
        channel_id=str(getattr(agent, "channel_id", None) or getattr(agent, "_channel_id", "") or ""),
        thread_id=str(
            getattr(agent, "thread_id", None)
            or getattr(agent, "_thread_id", None)
            or getattr(agent, "_thread_ts", "")
            or ""
        ),
        message_id=str(getattr(agent, "message_id", None) or getattr(agent, "_message_ts", "") or ""),
    )


def _plain_text_for_visual_prompt_learning(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif item.get("type") in {"text", "input_text"} and isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(part for part in parts if part).strip()
    return ""


def _apply_raphael_invocation_response_shape(
    final_response,
    *,
    user_message,
    conversation_history,
):
    from agent.raphael.appraisal import appraise_raphael_situation
    from agent.raphael.invocation import (
        is_raphael_invocation,
        render_raphael_invocation_response,
    )
    from agent.raphael.mission import update_raphael_mission
    from agent.raphael.observer import should_inject_raphael_observation
    from agent.raphael.state import read_mission_state
    from agent.raphael.strategy import simulate_raphael_strategies

    if not should_inject_raphael_observation():
        return final_response
    if not is_raphael_invocation(user_message):
        return final_response
    response_text = str(final_response or "")
    if "解析完成。" in response_text and (
        "局勢判讀" in response_text or "狀態：Raphael 待命" in response_text
    ):
        return final_response
    if "還不能判定完成" in response_text or "Raphael proof gate" in response_text:
        return final_response
    if _raphael_user_requested_exact_reply_shape(user_message):
        return final_response
    appraisal = appraise_raphael_situation(
        user_message,
        conversation_history=conversation_history,
    )
    strategies = simulate_raphael_strategies(appraisal)
    mission = update_raphael_mission(read_mission_state(), appraisal, strategies)
    prefix = render_raphael_invocation_response(appraisal, strategies, mission)
    return f"{prefix}\n\n回應：\n{response_text}"


def _is_explicit_raphael_invocation(user_message) -> bool:
    try:
        from agent.raphael.invocation import is_raphael_invocation

        return is_raphael_invocation(user_message)
    except Exception:
        return False


def _raphael_user_requested_exact_reply_shape(user_message) -> bool:
    text = str(user_message or "").lower()
    compact = "".join(text.split())
    reply_markers = (
        "只回覆",
        "只回答",
        "只用",
        "僅回覆",
        "仅回复",
        "only reply",
        "only respond",
        "reply only",
        "respond only",
    )
    shape_markers = (
        "三行",
        "二行",
        "兩行",
        "两行",
        "四行",
        "五行",
        "六行",
        "2行",
        "3行",
        "4行",
        "5行",
        "6行",
        "2 lines",
        "3 lines",
        "4 lines",
        "5 lines",
        "6 lines",
        "two lines",
        "three lines",
        "four lines",
        "five lines",
        "six lines",
        "一句",
        "一行",
        "one line",
        "single line",
    )
    return any(marker in text or marker in compact for marker in reply_markers) and any(
        marker in text or marker in compact for marker in shape_markers
    )


def _raphael_claims_completion(text) -> bool:
    lowered = str(text or "").lower()
    negative_markers = (
        "不能宣稱完成",
        "不要宣稱完成",
        "不可宣稱完成",
        "不應宣稱完成",
        "不該宣稱完成",
        "不能說完成",
        "不可說完成",
        "不能判定完成",
        "還不能判定完成",
        "尚不能判定完成",
        "不可以宣稱完成",
        "不算完成",
        "not complete",
        "not completed",
        "cannot claim completion",
        "can't claim completion",
        "do not claim completion",
        "should not claim completion",
    )
    if any(marker in lowered for marker in negative_markers):
        return False
    markers = (
        "done",
        "fixed",
        "completed",
        "passed",
        "verified",
        "已完成",
        "完成",
        "修好了",
        "修復完成",
        "驗證完成",
        "測試通過",
        "可以上線",
        "已產出",
        "已生成",
        "產出圖片",
        "生成圖片",
    )
    return any(marker in lowered for marker in markers)
