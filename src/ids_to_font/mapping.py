"""Maintain permanent IDS-to-PUA assignments."""

from __future__ import annotations

import json
import re
from pathlib import Path


PUA_START = 0xE000
PUA_END = 0xF8FF
CODEPOINT = re.compile(r"^U\+([0-9A-Fa-f]{4,6})$")


def parse_codepoint(value: str) -> int:
    match = CODEPOINT.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid code point {value!r}.")
    codepoint = int(match.group(1), 16)
    if not PUA_START <= codepoint <= PUA_END:
        raise ValueError(f"Code point {value!r} is outside the BMP Private Use Area.")
    return codepoint


def load_previous_assignments(path: Path | None) -> dict[str, int]:
    """Load assignment history from an earlier generated mapping."""
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    raw_assignments = document.get("assignments")
    if raw_assignments is None:
        raw_assignments = {
            ids: record["codepoint"]
            for ids, record in document.get("glyphs", {}).items()
        }
    if not isinstance(raw_assignments, dict):
        raise ValueError("Previous mapping assignments must be a JSON object.")
    assignments = {
        str(ids): parse_codepoint(str(codepoint))
        for ids, codepoint in raw_assignments.items()
    }
    reverse: dict[int, str] = {}
    for ids, codepoint in assignments.items():
        if codepoint in reverse:
            raise ValueError(
                f"Previous mapping assigns U+{codepoint:04X} to both "
                f"{reverse[codepoint]!r} and {ids!r}."
            )
        reverse[codepoint] = ids
    return assignments


def assign_pua(
    active_ids: list[str],
    previous_assignments: dict[str, int] | None = None,
) -> dict[str, int]:
    """Preserve existing assignments and allocate new PUA values."""
    assignments = dict(previous_assignments or {})
    used = set(assignments.values())
    available = (
        codepoint
        for codepoint in range(PUA_START, PUA_END + 1)
        if codepoint not in used
    )
    for ids in sorted(set(active_ids)):
        if ids in assignments:
            continue
        try:
            assignments[ids] = next(available)
        except StopIteration as error:
            raise ValueError("The BMP Private Use Area is exhausted.") from error
    return assignments


def serialize_assignments(assignments: dict[str, int]) -> dict[str, str]:
    return {
        ids: f"U+{codepoint:04X}"
        for ids, codepoint in sorted(assignments.items(), key=lambda item: item[1])
    }
