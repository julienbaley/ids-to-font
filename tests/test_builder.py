import json
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import flagOverlapSimple

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


def mixed_winding_resolution(ids: str) -> SvgResolution:
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=(
            {
                "d": "M 10,10 L 40,10 L 40,40 L 10,40 Z",
                "transform": "scale(1,1)",
            },
            {
                "d": "M 30,30 L 30,70 L 70,70 L 70,30 Z",
                "transform": "scale(1,1)",
            },
        ),
    )


def separated_strokes_resolution(ids: str) -> SvgResolution:
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=(
            {"d": "M 10,10 L 20,10 L 20,85 L 10,85 Z"},
            {"d": "M 75,10 L 85,10 L 85,85 L 75,85 Z"},
        ),
    )


def contour_areas(font: TTFont, glyph_name: str) -> list[float]:
    glyph = font["glyf"][glyph_name]
    coordinates, end_points, _ = glyph.getCoordinates(font["glyf"])
    areas = []
    start = 0
    for end in end_points:
        points = coordinates[start : end + 1]
        areas.append(
            sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            )
            / 2
        )
        start = end + 1
    return areas


def write_reference_font(path: Path) -> None:
    pen = TTGlyphPen(None)
    pen.moveTo((50, -100))
    pen.lineTo((950, -100))
    pen.lineTo((950, 900))
    pen.lineTo((50, 900))
    pen.closePath()
    builder = FontBuilder(1024, isTTF=True)
    builder.setupGlyphOrder([".notdef", "uni4E00"])
    builder.setupCharacterMap({0x4E00: "uni4E00"})
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "uni4E00": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (1024, 0), "uni4E00": (1024, 50)})
    builder.setupHorizontalHeader(ascent=900, descent=-100, lineGap=20)
    builder.setupOS2(
        sTypoAscender=900,
        sTypoDescender=-100,
        sTypoLineGap=20,
        usWinAscent=900,
        usWinDescent=100,
    )
    builder.setupNameTable(
        {
            "familyName": "Reference Han",
            "styleName": "Regular",
            "fullName": "Reference Han",
            "psName": "ReferenceHan",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.font.save(path)


def write_light_reference_font(path: Path) -> None:
    pen = TTGlyphPen(None)
    for left, right in ((50, 150), (850, 950)):
        pen.moveTo((left, -100))
        pen.lineTo((right, -100))
        pen.lineTo((right, 900))
        pen.lineTo((left, 900))
        pen.closePath()
    builder = FontBuilder(1024, isTTF=True)
    builder.setupGlyphOrder([".notdef", "uni4E00"])
    builder.setupCharacterMap({0x4E00: "uni4E00"})
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "uni4E00": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (1024, 0), "uni4E00": (1024, 50)})
    builder.setupHorizontalHeader(ascent=900, descent=-100)
    builder.setupOS2(
        sTypoAscender=900,
        sTypoDescender=-100,
        usWinAscent=900,
        usWinDescent=100,
    )
    builder.setupNameTable(
        {
            "familyName": "Light Reference Han",
            "styleName": "Regular",
            "fullName": "Light Reference Han",
            "psName": "LightReferenceHan",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.font.save(path)


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
    assert result.style_path is None
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
    mapping = json.loads(second.mapping_path.read_text(encoding="utf-8"))
    assert second.style_path == tmp_path / "ttf" / "ids-glyphs.sty"
    assert mapping["latex_package"] == "ids-glyphs.sty"


def test_ttf_package_maps_ids_expressions_to_pua_characters(
    tmp_path: Path,
) -> None:
    result = build(
        ["⿰鳥叴", "⿱弔口"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=resolution,
    )
    style = result.style_path.read_text(encoding="utf-8")
    assert f"{{{result.font_path.name}}}" in style
    assert "{ ⿰鳥叴 } { \\char_generate:nn { \"E000 } { 12 } }" in style
    assert "{ ⿱弔口 } { \\char_generate:nn { \"E001 } { 12 } }" in style
    assert r"\NewDocumentCommand \ids { m }" in style
    assert r"\NewDocumentCommand \idschar { m }" in style


def test_generated_glyphs_mark_overlapping_contours(tmp_path: Path) -> None:
    result = build(
        ["⿰鳥叴"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=resolution,
    )
    with TTFont(result.font_path) as font:
        glyph_name = font.getBestCmap()[0xE000]
        glyph = font["glyf"][glyph_name]
        assert glyph.numberOfContours > 0
        assert glyph.flags[0] & flagOverlapSimple


def test_separately_filled_paths_use_consistent_contour_winding(
    tmp_path: Path,
) -> None:
    result = build(
        ["⿰鳥叴"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=mixed_winding_resolution,
    )
    with TTFont(result.font_path) as font:
        glyph_name = font.getBestCmap()[0xE000]
        areas = contour_areas(font, glyph_name)
        assert len(areas) == 2
        assert all(area < 0 for area in areas)


def test_matches_reference_han_size_baseline_and_metrics(tmp_path: Path) -> None:
    reference = tmp_path / "reference.ttf"
    write_reference_font(reference)
    result = build(
        ["⿰鳥叴"],
        tmp_path / "output",
        output_format="ttf",
        match_font=reference,
        delay=0,
        resolver=resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
    assert mapping["calibration"]["reference_font"] == "reference.ttf"
    assert mapping["calibration"]["reference_sample_size"] == 1
    with TTFont(result.font_path) as font:
        glyph = font["glyf"][font.getBestCmap()[0xE000]]
        glyph.recalcBounds(font["glyf"])
        assert 999 <= glyph.yMax - glyph.yMin <= 1001
        assert 399 <= (glyph.yMax + glyph.yMin) / 2 <= 401
        assert font["hhea"].ascent == 900
        assert font["hhea"].descent == -100
        assert font["hhea"].lineGap == 20


def test_match_font_thins_glyphs_for_a_lighter_reference(tmp_path: Path) -> None:
    reference = tmp_path / "light-reference.ttf"
    write_light_reference_font(reference)
    result = build(
        ["⿰鳥叴"],
        tmp_path / "output",
        output_format="ttf",
        match_font=reference,
        delay=0,
        resolver=separated_strokes_resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
    calibration = mapping["calibration"]
    assert calibration["outline_inset"] > 0
    assert calibration["matched_density"] < 0.27
    with TTFont(result.font_path) as font:
        glyph = font["glyf"][font.getBestCmap()[0xE000]]
        assert glyph.numberOfContours == 2


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
