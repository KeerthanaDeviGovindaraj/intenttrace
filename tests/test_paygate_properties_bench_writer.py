"""Property test for the PayGate results writer (Requirements 11.8)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from intenttrace.bench import (
    PAYGATE_BEGIN,
    PAYGATE_END,
    render_paygate_section,
    write_paygate_results,
    write_results,
)

# No "<" so drawn text can never contain a marker; no "\r" since text mode normalizes it.
_text = st.text(
    alphabet=st.characters(blacklist_characters="\r<", blacklist_categories=("Cs",)),
    max_size=60,
)
_name = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12)
_rate = st.floats(min_value=0, max_value=1, allow_nan=False)
_json_value = st.recursive(
    st.none() | st.booleans() | st.integers(-1000, 1000) | _text,
    lambda c: st.lists(c, max_size=3) | st.dictionaries(_text, c, max_size=3),
    max_leaves=6,
)
_other_json = st.dictionaries(_text.filter(lambda k: k != "paygate"), _json_value, max_size=5)


@st.composite
def _existing_json(draw) -> dict:
    data = draw(_other_json)
    if draw(st.booleans()):
        data["paygate"] = draw(_json_value)
    return data


@st.composite
def _existing_md(draw) -> tuple[str, str | None, str | None]:
    """(text, prefix, suffix); prefix/suffix are None when the text has no block."""
    if draw(st.booleans()):
        return draw(_text), None, None
    prefix, inner, suffix = draw(_text), draw(_text), draw(_text)
    return prefix + PAYGATE_BEGIN + inner + PAYGATE_END + suffix, prefix, suffix


def _rates(draw, n: int) -> dict:
    return {
        "n": n,
        "block_rate": draw(_rate),
        "ask_human_rate": draw(_rate),
        "allow_rate": draw(_rate),
    }


@st.composite
def _paygate_results(draw) -> dict:
    by = st.dictionaries(
        _name, st.fixed_dictionaries({"n": st.integers(1, 300), "block_rate": _rate}), max_size=4
    )
    return {
        "provider": draw(_name),
        "model": draw(_name),
        "seed": draw(st.none() | st.integers(0, 10**6)),
        "n": draw(st.integers(0, 300)),
        "date": "2025-01-31",
        "pipeline_test_only": draw(st.booleans()),
        "attack": _rates(draw, draw(st.integers(0, 300))),
        "legitimate": _rates(draw, draw(st.integers(0, 300))),
        "false_block_rate": draw(_rate),
        "excluded": {
            "merchant_misrepresentation": {"count": draw(st.integers(0, 50)), "reason": "r1"},
            "payment_only_integrity": {"count": draw(st.integers(0, 50)), "reason": "r2"},
        },
        "block_rate_by_label": draw(by),
        "block_rate_by_attack_type": draw(by),
        "block_rate_by_cause": draw(by),
        "latency_ms": {"p50": draw(_rate), "p95": draw(_rate)},
    }


def _bench_results() -> dict:
    pass_metrics = {
        "macro_f1": 0.5,
        "coverage": 1.0,
        "false_accusation_rate": 0.0,
        "latency_ms": {"p50": 1.0, "p95": 2.0},
        "per_verdict": {
            v: {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 1}
            for v in (
                "LEGITIMATE",
                "MANIPULATED",
                "OUT_OF_SCOPE",
                "MERCHANT_MISREPRESENTATION",
                "INTEGRITY_FAILURE",
            )
        },
        "confusion_matrix": {
            t: dict.fromkeys(
                (
                    "LEGITIMATE",
                    "MANIPULATED",
                    "OUT_OF_SCOPE",
                    "MERCHANT_MISREPRESENTATION",
                    "INTEGRITY_FAILURE",
                    "INCONCLUSIVE",
                ),
                0,
            )
            for t in (
                "LEGITIMATE",
                "MANIPULATED",
                "OUT_OF_SCOPE",
                "MERCHANT_MISREPRESENTATION",
                "INTEGRITY_FAILURE",
            )
        },
        "manipulated_recall_by_attack": {"x": {"caught": 1, "support": 1, "recall": 1.0}},
    }
    return {
        "provider": "fake",
        "model": "fake",
        "prompt_version": "v1",
        "seed": 1,
        "n": 1,
        "date": "2025-01-31",
        "pipeline_test_only": True,
        "replay_on": pass_metrics,
        "replay_off": pass_metrics,
        "llm": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }


# Feature: paygate, Property 12: PayGate results section is idempotent and non-destructive
# **Validates: Requirements 11.8**
@settings(max_examples=100, deadline=None)
@given(md=_existing_md(), existing=_existing_json(), results=_paygate_results())
def test_paygate_results_writer_idempotent_and_non_destructive(md, existing, results):
    text, prefix, suffix = md
    block = render_paygate_section(results)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "RESULTS.md").write_text(text, encoding="utf-8")
        (out / "results.json").write_text(json.dumps(existing), encoding="utf-8")

        write_paygate_results(results, out)
        md1 = (out / "RESULTS.md").read_bytes()
        js1 = (out / "results.json").read_bytes()
        write_paygate_results(results, out)
        assert (out / "RESULTS.md").read_bytes() == md1
        assert (out / "results.json").read_bytes() == js1

        out_text = md1.decode("utf-8")
        assert out_text.count(PAYGATE_BEGIN) == 1
        assert out_text.count(PAYGATE_END) == 1
        assert block in out_text
        if prefix is None:
            assert out_text.startswith(text.rstrip("\n"))
        else:
            assert out_text == prefix + block + suffix
        data = json.loads(js1)
        assert data["paygate"] == json.loads(json.dumps(results))
        for key, value in existing.items():
            if key != "paygate":
                assert data[key] == value
        assert set(data) == (set(existing) | {"paygate"})

        # A later write_results keeps the PayGate block and key.
        write_results(_bench_results(), out)
        final = (out / "RESULTS.md").read_text(encoding="utf-8")
        assert final.count(PAYGATE_BEGIN) == 1
        assert final.count(PAYGATE_END) == 1
        assert block in final
        final_json = json.loads((out / "results.json").read_text(encoding="utf-8"))
        assert final_json["paygate"] == data["paygate"]
        assert final_json["provider"] == "fake"
