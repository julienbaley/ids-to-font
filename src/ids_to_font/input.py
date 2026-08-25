"""Read and validate newline-delimited IDS or Unicode inputs."""

from __future__ import annotations

import unicodedata
import re
from pathlib import Path


IDS_OPERATORS = frozenset(chr(value) for value in range(0x2FF0, 0x3000))
CODEPOINT = re.compile(r"U\+([0-9A-Fa-f]{1,6})")


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


def normalize_character(value: str, line_number: int | None = None) -> str:
    value = value.strip()
    location = f" on line {line_number}" if line_number is not None else ""
    match = CODEPOINT.fullmatch(value)
    if match is not None:
        codepoint = int(match.group(1), 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError(f"Invalid Unicode scalar U+{codepoint:X}{location}.")
        return chr(codepoint)
    value = unicodedata.normalize("NFC", value)
    if len(value) != 1:
        raise ValueError(
            f"Encoded input must be one Unicode character or U+ value{location}."
        )
    codepoint = ord(value)
    if 0xD800 <= codepoint <= 0xDFFF:
        raise ValueError(f"Invalid Unicode scalar U+{codepoint:X}{location}.")
    return value


def read_characters(path: Path) -> list[str]:
    """Return unique Unicode scalars in deterministic code-point order."""
    characters = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        characters.add(normalize_character(line, line_number))
    if not characters:
        raise ValueError(f"No Unicode characters were found in {path}.")
    return sorted(characters, key=ord)
