from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from guidesync_agent.schemas import ToolValidationFinding


def validate_tool_result(
    tool_name: str,
    result: object,
) -> list[ToolValidationFinding]:
    if isinstance(result, BaseModel):
        return validate_tool_result(tool_name, result.model_dump(mode="json"))

    findings: list[ToolValidationFinding] = []
    if isinstance(result, Mapping):
        if result.get("ok") is False:
            error = result.get("error")
            message = str(error) if error else f"{tool_name} returned an error."
            findings.append(
                ToolValidationFinding(
                    severity="error",
                    check=f"{tool_name}.ok",
                    message=message,
                )
            )
        pagination = result.get("pagination")
        if isinstance(pagination, Mapping) and pagination.get("truncated"):
            findings.append(
                ToolValidationFinding(
                    severity="info",
                    check=f"{tool_name}.pagination",
                    message=(
                        "Tool result was paginated; read the next window before relying "
                        "on completeness."
                    ),
                )
            )
        return findings
    return findings
