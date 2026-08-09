from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from guidesync_agent.schemas import (
    EvaluationConditionProtocol,
    EvaluationExperimentManifest,
    FrozenUiEvidenceManifest,
)


def condition_protocol_checksum(protocol: EvaluationConditionProtocol) -> str:
    payload = protocol.model_dump(mode="json")
    payload["condition"]["config_checksum"] = None
    return payload_checksum(payload)


def experiment_checksum(experiment: EvaluationExperimentManifest) -> str:
    payload = experiment.model_dump(mode="json", exclude={"id"})
    return payload_checksum(payload)


def model_checksum(model: BaseModel) -> str:
    return payload_checksum(model.model_dump(mode="json"))


def ui_evidence_manifest_checksum(manifest: FrozenUiEvidenceManifest) -> str:
    return payload_checksum(manifest.model_dump(mode="json", exclude={"checksum"}))


def payload_checksum(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def stable_hash(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


def stable_seed(base_seed: int, *values: str) -> int:
    return (base_seed + int(stable_hash(*values)[:16], 16)) % (2**31)


def safe_id(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip(
        "-"
    )
