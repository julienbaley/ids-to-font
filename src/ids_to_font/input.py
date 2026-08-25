"""Read and validate newline-delimited IDS expressions."""

from __future__ import annotations

import unicodedata
from pathlib import Path


IDS_OPERATORS = frozenset(chr(value) for value in range(0x2FF0, 0x3000))


def normalize_ids(value: str, line_number: int | None = None) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    location = f" on line {line_number}" if line_number is not None else ""
    if not value:
        raise ValueError(f"Empty IDS expression{location}.")
    if value[0] not in IDS_OPERATORS:
        raise ValueError(f"IDS expression must begin with an IDS operator{location}.")
    if value.startswith("{") or value.endswith("}"):
        raise ValueError(f"IDS expressions must not be enclosed in braces{location}.")
    if any(character.isspace() for character in value):
        raise ValueError(f"IDS expressions must not contain whitespace{location}.")
    return value


def read_ids(path: Path) -> list[str]:
    """Return unique normalized IDS expressions in deterministic order."""
    expressions = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        expressions.add(normalize_ids(line, line_number))
    if not expressions:
        raise ValueError(f"No IDS expressions were found in {path}.")
    return sorted(expressions)
