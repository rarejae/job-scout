"""Personal markdowns: gitignored files, or blocks inlined in the job prompt.

The scheduled routine does not read these from git. It gets them as
attachments / <profile> blocks in its saved prompt, then writes them into
the checkout (still gitignored) so the rest of the pipeline can open them.
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

PROFILE = "profile.md"
RESUME = "resume.md"
APPLY_FACTS = "apply-facts.md"

_ENV = {
    PROFILE: "SCOUT_PROFILE",
    RESUME: "SCOUT_RESUME",
    APPLY_FACTS: "SCOUT_APPLY_FACTS",
}


def path_for(name: str) -> pathlib.Path:
    env = os.environ.get(_ENV[name])
    return pathlib.Path(env) if env else ROOT / name


def load_text(name: str, *, required: bool = True) -> str:
    path = path_for(name)
    if not path.exists():
        if not required:
            return ""
        example = EXAMPLES / name
        raise SystemExit(
            f"missing {path}. Copy {example} → {ROOT / name}, fill it in, "
            f"then attach it to the scheduled job (python -m scout.prompt "
            f"inlines it). The file is gitignored; do not commit it."
        )
    return path.read_text()


def load_profile() -> str:
    return load_text(PROFILE)
