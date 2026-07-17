from __future__ import annotations

from . import hooks, schemas, tools, visual_judge


def register(ctx) -> None:
    visual_judge.configure_plugin_llm(ctx.llm)
    ctx.register_command(
        "story-video",
        hooks.handle_story_video_command,
        description="Story-video help, status, examples, writing, and voices.",
        args_hint="[status|examples|writing|voices]",
    )
    ctx.register_tool(
        name="story_video_control",
        toolset="story_video",
        schema=schemas.STORY_VIDEO_CONTROL_SCHEMA,
        handler=tools.story_video_control,
    )
    ctx.register_tool(
        name="story_video_voice_manager",
        toolset="story_video",
        schema=schemas.STORY_VIDEO_VOICE_MANAGER_SCHEMA,
        handler=tools.story_video_voice_manager,
    )
    ctx.register_tool(
        name="story_video_audio_director",
        toolset="story_video",
        schema=schemas.STORY_VIDEO_AUDIO_DIRECTOR_SCHEMA,
        handler=tools.story_video_audio_director,
    )
    ctx.register_tool(
        name="story_video_quality_control",
        toolset="story_video",
        schema=schemas.STORY_VIDEO_QUALITY_CONTROL_SCHEMA,
        handler=visual_judge.story_video_quality_control,
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
        ("auto_continue_llm_output", hooks.auto_continue_llm_output),
    ):
        ctx.register_hook(name, callback)
