import pytest

from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from gateway.config import Platform, PlatformConfig


class _RecordingAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True), Platform.SLACK)
        self.sent = []
        self.documents = []

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append({"chat_id": chat_id, "content": content, "metadata": metadata})
        return SendResult(success=True, message_id="sent-1")

    async def send_document(self, chat_id, file_path, caption=None, reply_to=None, **kwargs):
        self.documents.append({"chat_id": chat_id, "file_path": file_path, "kwargs": kwargs})
        return SendResult(success=True, message_id="doc-1")


def _event():
    return MessageEvent(
        text="done",
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.SLACK,
            chat_id="C123",
            chat_type="dm",
            thread_id="1777.1",
        ),
        message_id="m1",
    )


@pytest.mark.asyncio
async def test_post_stream_missing_media_tag_uses_text_fallback_without_file_send():
    runner = GatewayRunner.__new__(GatewayRunner)
    adapter = _RecordingAdapter()

    await runner._deliver_media_from_response(
        "Here is the screenshot MEDIA:<screenshot_path>",
        _event(),
        adapter,
    )

    assert adapter.documents == []
    assert adapter.sent == [
        {
            "chat_id": "C123",
            "content": "⚠️ Media attachment unavailable: `<screenshot_path>`",
            "metadata": {"thread_id": "1777.1"},
        }
    ]
