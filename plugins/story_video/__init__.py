from __future__ import annotations

from . import hooks, schemas, tools


def register(ctx) -> None:
    ctx.register_tool(
        name="story_video_control",
        toolset="story_video",
        schema=schemas.STORY_VIDEO_CONTROL_SCHEMA,
        handler=tools.story_video_control,
    )
    for name, callback in (
        ("pre_gateway_dispatch", hooks.pre_gateway_dispatch),
        ("pre_llm_call", hooks.pre_llm_call),
        ("pre_tool_call", hooks.pre_tool_call),
        ("post_tool_call", hooks.post_tool_call),
        ("pre_api_request", hooks.pre_api_request),
        ("post_api_request", hooks.post_api_request),
        ("api_request_error", hooks.api_request_error),
        ("subagent_start", hooks.subagent_start),
        ("transform_llm_output", hooks.transform_llm_output),
    ):
        ctx.register_hook(name, callback)
