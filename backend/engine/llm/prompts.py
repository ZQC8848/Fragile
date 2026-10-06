"""Prompt files: backend/prompts/<role>_v<N>.md, one file per role and version (plan.md section 3.2).

    load_prompt("narrator")          -> Prompt(text, version)   the highest N on disk
    PROMPT_VERSION_NARRATOR=2        pins narrator_v2.md instead

The version goes into the response-cache key and into every log line, so changing a prompt means adding
`<role>_v<N+1>.md`, not editing the old file in place.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class Prompt(NamedTuple):
    text: str
    version: int


def prompt_versions(role: str, directory: Path | None = None) -> dict[int, Path]:
    """Every version of `role` present on disk, {N: path}."""
    directory = directory or PROMPTS_DIR
    pattern = re.compile(rf"^{re.escape(role)}_v(\d+)\.md$")
    out: dict[int, Path] = {}
    if directory.is_dir():
        for path in directory.iterdir():
            m = pattern.match(path.name)
            if m and path.is_file():
                out[int(m.group(1))] = path
    return out


def load_prompt(role: str, directory: Path | None = None) -> Prompt:
    """The role's system prompt and its version. Raises FileNotFoundError when there is no such file."""
    versions = prompt_versions(role, directory)
    env_key = f"PROMPT_VERSION_{role.upper()}"
    pinned = os.getenv(env_key, "").strip()
    if pinned:
        try:
            version = int(pinned.lower().removeprefix("v"))
        except ValueError:
            raise ValueError(f"{env_key}={pinned!r} is not a version number") from None
        if version not in versions:
            raise FileNotFoundError(f"{env_key}={pinned} but {role}_v{version}.md does not exist")
    elif versions:
        version = max(versions)
    else:
        raise FileNotFoundError(f"no prompt file {role}_v<N>.md in {directory or PROMPTS_DIR}")
    return Prompt(versions[version].read_text(encoding="utf-8"), version)
