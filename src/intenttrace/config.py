"""Tunable thresholds (design.md section 8). Kept in one place so the benchmark can sweep them."""

from __future__ import annotations

from pydantic import BaseModel


class Thresholds(BaseModel):
    # V6: flagged spans + deviation + influence at or above this => MANIPULATED (medium).
    influence_manipulated: float = 0.6
    # V8: flagged spans + no deviation + influence below this => LEGITIMATE (medium).
    influence_legitimate: float = 0.3


DEFAULT_THRESHOLDS = Thresholds()
