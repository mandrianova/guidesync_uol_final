from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

PROMPTS_ROOT = Path(__file__).resolve().parent


class PromptFile(BaseModel):
    id: str
    path: str
    version: str
    content: str
    sha256: str

    def usage_metadata(self, prefix: str) -> dict[str, str]:
        return {
            f"{prefix}_prompt_id": self.id,
            f"{prefix}_prompt_version": self.version,
            f"{prefix}_prompt_sha256": self.sha256,
            f"{prefix}_prompt_path": self.path,
        }


def load_prompt_file(relative_path: str, *, version: str) -> PromptFile:
    normalized_path = Path(relative_path).as_posix()
    path = (PROMPTS_ROOT / normalized_path).resolve()
    path.relative_to(PROMPTS_ROOT)
    content = path.read_text(encoding="utf-8")
    return PromptFile(
        id=prompt_id(normalized_path),
        path=normalized_path,
        version=version,
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def prompt_id(relative_path: str) -> str:
    return Path(relative_path).with_suffix("").as_posix().replace("/", ".")
