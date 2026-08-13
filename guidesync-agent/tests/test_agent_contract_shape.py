from __future__ import annotations

from typing import Any

from guidesync_agent.prompts.contracts import workflow_prompt_contracts
from guidesync_agent.schemas import ProjectProfileAgentOutput
from guidesync_agent.services.ui_evidence.validation import ScreenshotVisionModelOutput
from guidesync_agent.tools.code_change_agent import code_change_tool_descriptors
from guidesync_agent.tools.project_profile_agent import project_profile_tool_descriptors

PRIMITIVE_TYPES = {"string", "integer", "number", "boolean"}


def test_workflow_prompt_contract_outputs_stay_shallow() -> None:
    for contract in workflow_prompt_contracts():
        assert_shallow_model_output(
            contract.output_json_schema,
            contract.output_schema_name,
        )


def test_project_profile_agent_output_stays_shallow() -> None:
    assert_shallow_model_output(
        ProjectProfileAgentOutput.model_json_schema(),
        "ProjectProfileAgentOutput",
    )


def test_screenshot_vision_output_stays_shallow() -> None:
    assert_shallow_model_output(
        ScreenshotVisionModelOutput.model_json_schema(),
        "ScreenshotVisionModelOutput",
    )


def test_agent_tool_input_schemas_stay_flat() -> None:
    descriptors = [*project_profile_tool_descriptors(), *code_change_tool_descriptors()]

    for descriptor in descriptors:
        assert_flat_tool_arguments(
            descriptor.argument_schema,
            f"{descriptor.name.value} arguments",
        )


def assert_shallow_model_output(schema: dict[str, Any], context: str) -> None:
    assert schema.get("type") == "object", context
    for name, prop in schema.get("properties", {}).items():
        assert_flat_property(prop, f"{context}.{name}", schema)


def assert_flat_tool_arguments(schema: dict[str, Any], context: str) -> None:
    if not schema:
        return
    assert schema.get("type") == "object", context
    assert schema.get("additionalProperties") is False, context
    for name, prop in schema.get("properties", {}).items():
        assert_flat_property(prop, f"{context}.{name}", schema)


def assert_flat_property(
    prop: dict[str, Any],
    context: str,
    root_schema: dict[str, Any],
) -> None:
    if "$ref" in prop:
        prop = resolve_local_schema_ref(root_schema, str(prop["$ref"]))

    if "anyOf" in prop:
        for option in prop["anyOf"]:
            if option.get("type") != "null":
                assert_flat_property(option, context, root_schema)
        return

    prop_type = prop.get("type")
    if prop_type == "array":
        items = prop.get("items", {})
        if "$ref" in items:
            items = resolve_local_schema_ref(root_schema, str(items["$ref"]))
        assert items.get("type") in PRIMITIVE_TYPES, context
        assert "properties" not in items, context
        return

    assert prop_type in PRIMITIVE_TYPES, context
    assert "properties" not in prop, context


def resolve_local_schema_ref(
    root_schema: dict[str, Any],
    reference: str,
) -> dict[str, Any]:
    assert reference.startswith("#/"), reference
    target: Any = root_schema
    for part in reference.removeprefix("#/").split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    assert isinstance(target, dict), reference
    return target
