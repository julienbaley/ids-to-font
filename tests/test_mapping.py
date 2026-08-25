import json
from pathlib import Path

import pytest

from ids_to_font.mapping import assign_pua, load_previous_assignments


def test_reuses_assignments_and_reserves_removed_values(tmp_path: Path) -> None:
    previous = tmp_path / "mapping.json"
    previous.write_text(
        json.dumps(
            {
                "assignments": {
                    "⿰甲乙": "U+E000",
                    "⿱丙丁": "U+E001",
                }
            }
        ),
        encoding="utf-8",
    )
    assignments = assign_pua(
        ["⿰甲乙", "⿴戊己"],
        load_previous_assignments(previous),
    )
    assert assignments == {
        "⿰甲乙": 0xE000,
        "⿱丙丁": 0xE001,
        "⿴戊己": 0xE002,
    }


def test_accepts_legacy_glyph_only_mapping(tmp_path: Path) -> None:
    previous = tmp_path / "mapping.json"
    previous.write_text(
        json.dumps(
            {"glyphs": {"⿰甲乙": {"character": "\ue000", "codepoint": "U+E000"}}}
        ),
        encoding="utf-8",
    )
    assert load_previous_assignments(previous) == {"⿰甲乙": 0xE000}


def test_rejects_duplicate_previous_codepoints(tmp_path: Path) -> None:
    previous = tmp_path / "mapping.json"
    previous.write_text(
        json.dumps(
            {"assignments": {"⿰甲乙": "U+E000", "⿱丙丁": "U+E000"}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="both"):
        load_previous_assignments(previous)
