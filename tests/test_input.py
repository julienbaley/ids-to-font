from pathlib import Path

import pytest

from ids_to_font.input import (
    normalize_character,
    normalize_ids,
    read_characters,
    read_ids,
)


def test_reads_unique_sorted_newline_input(tmp_path: Path) -> None:
    path = tmp_path / "ids.txt"
    path.write_text("⿱弔口\n\n⿰鳥叴\n⿱弔口\n", encoding="utf-8")
    assert read_ids(path) == ["⿰鳥叴", "⿱弔口"]


def test_reads_question_tofu_request(tmp_path: Path) -> None:
    path = tmp_path / "ids.txt"
    path.write_text("{?}\n", encoding="utf-8")

    assert read_ids(path) == ["?"]


@pytest.mark.parametrize("value", ["鳥", "{⿰鳥叴}", "⿰鳥 叴"])
def test_rejects_non_plain_ids(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_ids(value)


def test_rejects_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "ids.txt"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No IDS"):
        read_ids(path)


def test_reads_unicode_characters_and_codepoint_notation(tmp_path: Path) -> None:
    path = tmp_path / "characters.txt"
    path.write_text("U+26B82\n𬘄\nU+26B82\n", encoding="utf-8")
    assert read_characters(path) == ["𦮂", "𬘄"]


@pytest.mark.parametrize("value", ["AB", "U+110000", "U+D800"])
def test_rejects_invalid_encoded_input(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_character(value)
