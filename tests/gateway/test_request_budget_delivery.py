import asyncio
import json
import logging

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, SendResult
from gateway.session import SessionSource, build_session_key


class DeliveryTimingAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="fake-token"), Platform.SLACK)
        self.sent = []

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        await asyncio.sleep(0)
        self.sent.append({"chat_id": chat_id, "content": content})
        return SendResult(success=True, message_id="1")

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        return None

    async def get_chat_info(self, chat_id: str):
        return {"id": chat_id}


@pytest.mark.asyncio
async def test_gateway_delivery_budget_logs_final_send_timing(caplog):
    adapter = DeliveryTimingAdapter()

    async def handler(_event):
        return "ack"

    async def hold_typing(_chat_id, interval=2.0, metadata=None):
        await asyncio.Event().wait()

    adapter.set_message_handler(handler)
    adapter._keep_typing = hold_typing

    event = MessageEvent(
        text="hello",
        source=SessionSource(
            platform=Platform.SLACK,
            chat_id="C123",
            chat_type="group",
            user_id="U123",
        ),
        message_id="m1",
    )

    with caplog.at_level(logging.INFO):
        await adapter._process_message_background(event, build_session_key(event.source))

    records = [
        r.getMessage().split("request_budget.gateway_delivery.v1 ", 1)[1]
        for r in caplog.records
        if "request_budget.gateway_delivery.v1 " in r.getMessage()
    ]
    assert records
    payload = json.loads(records[-1])
    assert payload["platform"] == "slack"
    assert payload["gateway_delivery_ms"] >= 0
    assert payload["response_chars"] == 3
    assert payload["delivery_succeeded"] is True
