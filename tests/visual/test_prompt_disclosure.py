def test_prompt_disclosure_returns_latest_visual_prompt_without_generation(tmp_path, monkeypatch):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from gateway.session_context import clear_session_vars
    from gateway.session_context import set_session_vars

    ledger_path = tmp_path / "attempts.sqlite3"
    ledger = VisualAttemptLedger(ledger_path)
    ledger.initialize()

    request_id = ledger.record_request(user_prompt="把 ref1 套 ref2", status="completed")
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine",
        prompt_original="把 ref1 套 ref2",
        prompt_mediated="Provider-ready visual prompt with reference role mapping",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/generated.png",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="D0AS3EE04CT",
        thread_id="1782668529.829199",
        delivery_status="sent",
    )

    from agent.visual import prompt_disclosure

    monkeypatch.setattr(prompt_disclosure, "default_visual_ledger_path", lambda: ledger_path)
    tokens = set_session_vars(
        platform="slack",
        chat_id="D0AS3EE04CT",
        thread_id="1782668529.829199",
    )
    try:
        response = prompt_disclosure.build_visual_prompt_disclosure_response(
            "請給我你使用的 prompt"
        )
    finally:
        clear_session_vars(tokens)

    assert response is not None
    assert "Provider-ready visual prompt with reference role mapping" in response
    assert "把 ref1 套 ref2" in response
    assert "xai" in response
    assert "grok-imagine" in response
    assert "已產出圖片" not in response


def test_prompt_disclosure_ignores_prompt_builder_request(tmp_path, monkeypatch):
    from agent.visual import prompt_disclosure

    monkeypatch.setattr(
        prompt_disclosure,
        "default_visual_ledger_path",
        lambda: tmp_path / "missing.sqlite3",
    )

    response = prompt_disclosure.build_visual_prompt_disclosure_response(
        "固定這位角色，替換不同的服裝與構圖，高品質，8K，光影，性感一些。請給我 prompt 就好，不須產圖"
    )

    assert response is None


def test_prompt_disclosure_ignores_threaded_pasted_prompt_edit(tmp_path, monkeypatch):
    from agent.visual import prompt_disclosure

    monkeypatch.setattr(
        prompt_disclosure,
        "default_visual_ledger_path",
        lambda: tmp_path / "missing.sqlite3",
    )
    message = (
        '[Thread context — prior messages in this thread (not yet in conversation history):]\n'
        "[thread parent] simon: 固定這位角色，替換不同的服裝與構圖，高品質，8K，光影，性感一些。"
        "請給我 prompt 就好，不須產圖\n"
        "[End of thread context]\n\n"
        "是這一版 prompt, 再修改性感一點的服裝\n"
        "Use the provided reference images as strict character identity reference.\n"
        "Add layered depth with the character sharply focused in the middle ground.\n"
        "Keep hand-painted lighting, no 3D, no CGI, no plastic render.\n"
        "Negative prompt: AI-generated look, generic anime girl, text, logo, watermark.\n"
        "如果還要更不 AI，可以在 prompt 最後補這句：\n"
        "The image should look like a manually art-directed 2D illustration."
    )

    response = prompt_disclosure.build_visual_prompt_disclosure_response(message)

    assert response is None


def test_prompt_disclosure_says_when_no_exact_prompt_is_available(tmp_path, monkeypatch):
    from agent.visual import prompt_disclosure
    from gateway.session_context import clear_session_vars
    from gateway.session_context import set_session_vars

    monkeypatch.setattr(
        prompt_disclosure,
        "default_visual_ledger_path",
        lambda: tmp_path / "missing.sqlite3",
    )
    tokens = set_session_vars(platform="slack", chat_id="D0AS3EE04CT", thread_id="T1")
    try:
        response = prompt_disclosure.build_visual_prompt_disclosure_response(
            "請給我你使用的 prompt"
        )
    finally:
        clear_session_vars(tokens)

    assert response is not None
    assert "找不到" in response
    assert "不會重產圖" in response


def test_prompt_disclosure_does_not_fallback_to_other_slack_thread(
    tmp_path,
    monkeypatch,
):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from gateway.session_context import clear_session_vars
    from gateway.session_context import set_session_vars

    ledger_path = tmp_path / "attempts.sqlite3"
    ledger = VisualAttemptLedger(ledger_path)
    ledger.initialize()
    request_id = ledger.record_request(user_prompt="other thread", status="completed")
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine",
        prompt_original="OTHER THREAD ORIGINAL",
        prompt_mediated="OTHER THREAD PROVIDER PROMPT",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/other-thread.png",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="D1",
        thread_id="T2",
        delivery_status="sent",
    )

    from agent.visual import prompt_disclosure

    monkeypatch.setattr(prompt_disclosure, "default_visual_ledger_path", lambda: ledger_path)
    tokens = set_session_vars(platform="slack", chat_id="D1", thread_id="T1")
    try:
        response = prompt_disclosure.build_visual_prompt_disclosure_response(
            "請給我剛剛產圖用的 prompt"
        )
    finally:
        clear_session_vars(tokens)

    assert response is not None
    assert "找不到" in response
    assert "OTHER THREAD PROVIDER PROMPT" not in response
    assert "OTHER THREAD ORIGINAL" not in response
