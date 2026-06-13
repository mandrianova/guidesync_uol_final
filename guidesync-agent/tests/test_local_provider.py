from __future__ import annotations

from guidesync_agent.providers import extract_json_object, local_message_content


def test_local_message_content_uses_last_message_output() -> None:
    response = {
        "output": [
            {"type": "reasoning", "content": "hidden reasoning"},
            {"type": "message", "content": '{"title": "Update"}'},
        ]
    }

    assert local_message_content(response) == '{"title": "Update"}'


def test_extract_json_object_accepts_fenced_json() -> None:
    payload = extract_json_object('```json\n{"title": "Update"}\n```')

    assert payload == {"title": "Update"}
