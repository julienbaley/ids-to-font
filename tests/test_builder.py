import json
from pathlib import Path

from fontTools.ttLib import TTFont

from ids_to_font.builder import build
from ids_to_font.zi_tools import SvgResolution


def resolution(ids: str) -> SvgResolution:
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=(
            {
                "d": "M 10,10 L 85,10 L 85,85 L 10,85 Z",
                "transform": "scale(1,1)",
            },
        ),
    )


def test_builds_paired_font_and_mapping(tmp_path: Path) -> None:
    result = build(
        ["⿱弔口", "⿰鳥叴"],
        tmp_path,
        delay=0,
        resolver=resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
    assert mapping["font"] == result.font_path.name
    assert mapping["font_format"] == "woff2"
    assert set(mapping["glyphs"]) == {"⿰鳥叴", "⿱弔口"}
    assert mapping["assignments"] == {
        "⿰鳥叴": "U+E000",
        "⿱弔口": "U+E001",
    }
    assert set(TTFont(result.font_path).getBestCmap()) == {0xE000, 0xE001}
    assert mapping["glyph_license"] == "GPL-3.0-only"


def test_build_is_deterministic_for_each_format(tmp_path: Path) -> None:
    for output_format in ("woff2", "ttf"):
        first = build(
            ["⿰鳥叴"],
            tmp_path / output_format / "first",
            output_format=output_format,
            delay=0,
            resolver=resolution,
        )
        second = build(
            ["⿰鳥叴"],
            tmp_path / output_format / "second",
            output_format=output_format,
            delay=0,
            resolver=resolution,
        )
        assert first.font_path.suffix == f".{output_format}"
        assert first.font_path.name == second.font_path.name
        assert first.font_path.read_bytes() == second.font_path.read_bytes()


def test_builds_ttf_with_the_same_cmap(tmp_path: Path) -> None:
    first = build(
        ["⿰鳥叴", "⿱弔口"],
        tmp_path / "woff2",
        delay=0,
        resolver=resolution,
    )
    second = build(
        ["⿰鳥叴", "⿱弔口"],
        tmp_path / "ttf",
        output_format="ttf",
        delay=0,
        resolver=resolution,
    )
    with TTFont(first.font_path) as woff2, TTFont(second.font_path) as ttf:
        assert woff2.getBestCmap() == ttf.getBestCmap()
        assert woff2.getGlyphOrder() == ttf.getGlyphOrder()


def test_rejects_unknown_output_format(tmp_path: Path) -> None:
    try:
        build(
            ["⿰鳥叴"],
            tmp_path,
            output_format="otf",
            delay=0,
            resolver=resolution,
        )
    except ValueError as error:
        assert "woff2" in str(error)
    else:
        raise AssertionError("Unknown output format was accepted.")


def test_font_date_changes_only_requested_metadata(tmp_path: Path) -> None:
    result = build(
        ["⿰鳥叴"],
        tmp_path,
        font_date="2026-08-25",
        delay=0,
        resolver=resolution,
    )
    with TTFont(result.font_path) as font:
        assert font["head"].created == 3870460800
        names = {record.nameID: record.toUnicode() for record in font["name"].names}
        assert names[3] == "IDS Glyphs 2026-08-25"


def test_previous_mapping_keeps_retired_assignment_reserved(tmp_path: Path) -> None:
    previous = tmp_path / "previous.json"
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
    output = tmp_path / "output"
    result = build(
        ["⿰甲乙", "⿴戊己"],
        output,
        previous_mapping=previous,
        delay=0,
        resolver=resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
    assert mapping["assignments"]["⿱丙丁"] == "U+E001"
    assert mapping["glyphs"]["⿴戊己"]["codepoint"] == "U+E002"
