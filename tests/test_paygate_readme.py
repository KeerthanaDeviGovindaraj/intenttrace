"""README PayGate section must state the required limitations (Req 12.1, 12.4, 12.5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
RESULTS = ROOT / "benchmark" / "RESULTS.md"


def _paygate_section() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"^## PayGate\b.*?(?=^## |\Z)", text, re.S | re.M)
    assert match, "README.md has no '## PayGate' section"
    return match.group(0)


def _anchor(heading: str) -> str:
    slug = heading.strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    return re.sub(r"\s", "-", slug)


LIMITATIONS = [
    "synthetic",
    "english-only",
    "paraphrased attack",
    "not a guarantee of safety",
    "ap2-style",
    "not ap2-compliant",
    "not legal advice",
]

OUT_OF_SCOPE = [
    "out of scope",
    "payment execution",
    "payment rails",
    "card handling",
    "merchant integrations",
    "acp sdk",
    "approval workflows",
    "authentication",
    "rate limiting",
    "multi-tenant",
    "multimodal",
    "post-purchase merchant misrepresentation",
    "training or tuning models",
    "key management",
    "hsm",
    "chargeback",
    "real-world accuracy claims",
]


@pytest.mark.parametrize("phrase", LIMITATIONS)
def test_readme_states_limitation(phrase: str) -> None:
    assert phrase in _paygate_section().lower()


@pytest.mark.parametrize("phrase", OUT_OF_SCOPE)
def test_readme_lists_out_of_scope_item(phrase: str) -> None:
    assert phrase in _paygate_section().lower()


def test_results_link_resolves_to_existing_heading() -> None:
    section = _paygate_section()
    links = re.findall(r"\]\(benchmark/RESULTS\.md#([^)\s]+)\)", section)
    assert links, "PayGate section has no link to a RESULTS.md heading"
    headings = [
        _anchor(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+)$", RESULTS.read_text(encoding="utf-8"), re.M)
    ]
    for anchor in links:
        assert anchor in headings, f"{anchor!r} not found in RESULTS.md headings"
