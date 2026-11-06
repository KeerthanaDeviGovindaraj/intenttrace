"""Export the CaseFile JSON Schema to docs/case-file.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

from intenttrace.models import CaseFile

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "docs" / "case-file.schema.json"


def render_schema() -> str:
    """Return the deterministic schema text (indent=2, sorted keys, trailing newline)."""
    return json.dumps(CaseFile.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export_schema(path: Path | str = DEFAULT_PATH) -> Path:
    """Write the CaseFile JSON Schema to `path` and return the resolved path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_schema(), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"wrote {export_schema()}")
