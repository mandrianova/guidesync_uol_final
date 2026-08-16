from __future__ import annotations

from guidesync_agent.prompts.loader import PromptFile, load_prompt_file

SCREENSHOT_VISION_PROMPT_VERSION = "screenshot-vision-v2"


def screenshot_vision_prompt_file() -> PromptFile:
    return load_prompt_file(
        "screenshot_vision/system.md",
        version=SCREENSHOT_VISION_PROMPT_VERSION,
    )
