"""Write the committed 12-case sample (2 per ground-truth bucket) to benchmark/sample/.

Usage: python scripts/make_sample.py [--seed 7] [--n 60]
Deterministic: the same seed and n always select and write the same files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from intenttrace.sim.generate import build_cases


def bucket_of(label: dict) -> str:
    cause = label["cause"]
    if cause.startswith("scope_"):
        return "oos"
    return {
        "no_attack": "clean",
        "attack_present_choice_unchanged": "not_fooled",
        "attack_changed_choice": "manipulated",
    }.get(cause, label["label"])


def pick(generated, per_bucket: int = 2):
    """First ``per_bucket`` cases of each bucket, preferring distinct causes/attack types."""
    chosen: dict[str, list] = {}
    for require_distinct in (True, False):
        for g in generated:
            got = chosen.setdefault(bucket_of(g.label), [])
            key = (g.label["cause"], g.label["attack_type"])
            distinct = all((x.label["cause"], x.label["attack_type"]) != key for x in got)
            if len(got) < per_bucket and g not in got and (distinct or not require_distinct):
                got.append(g)
    return [g for bucket in sorted(chosen) for g in chosen[bucket]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--n", type=int, default=60)
    parser.add_argument("--out", type=Path, default=Path("benchmark/sample"))
    args = parser.parse_args()

    picked = pick(build_cases(args.n, args.seed))
    args.out.mkdir(parents=True, exist_ok=True)
    for stale in args.out.glob("case-*.json"):
        stale.unlink()
    for g in picked:
        text = json.dumps(g.case.model_dump(), sort_keys=True, indent=2) + "\n"
        (args.out / f"{g.case.case_id}.json").write_text(text, encoding="utf-8")
    lines = [json.dumps(g.label, sort_keys=True) for g in picked]
    (args.out / "labels.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(picked)} sample cases to {args.out}")


if __name__ == "__main__":
    main()
