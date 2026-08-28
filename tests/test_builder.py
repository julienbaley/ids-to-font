import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import flagOverlapSimple
from shapely.geometry import Point

from ids_to_font import font as font_module
from ids_to_font.builder import build, build_encoded
from ids_to_font.font import (
    glyph_geometry,
    reference_han_metrics,
    resolution_to_glyph,
)
from ids_to_font.zi_tools import EncodedResolution, SvgResolution


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


def curved_counter_resolution(ids: str) -> SvgResolution:
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=(
            {
                "d": (
                    "M10 48 Q10 10 48 10 Q85 10 85 48 "
                    "Q85 85 48 85 Q10 85 10 48 Z "
                    "M35 48 Q35 60 48 60 Q60 60 60 48 "
                    "Q60 35 48 35 Q35 35 35 48 Z"
                ),
            },
        ),
    )


def encoded_resolution(character: str) -> EncodedResolution:
    return EncodedResolution(
        character=character,
        decompositions=("⿲糹叀糹", "⿰𦁆糸"),
        view_box="0 0 95 95",
        paths=(
            {
                "d": "M 10,10 L 85,10 L 85,85 L 10,85 Z",
                "transform": "scale(1,1)",
            },
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
    question_pen = TTGlyphPen(None)
    question_pen.moveTo((350, 200))
    question_pen.lineTo((650, 200))
    question_pen.lineTo((650, 700))
    question_pen.lineTo((350, 700))
    question_pen.closePath()
    builder = FontBuilder(1024, isTTF=True)
    builder.setupGlyphOrder([".notdef", "uni003F", "uni4E00"])
    builder.setupCharacterMap({0x003F: "uni003F", 0x4E00: "uni4E00"})
    builder.setupGlyf(
        {
            ".notdef": TTGlyphPen(None).glyph(),
            "uni003F": question_pen.glyph(),
            "uni4E00": pen.glyph(),
        }
    )
    builder.setupHorizontalMetrics(
        {
            ".notdef": (1024, 0),
            "uni003F": (1024, 0),
            "uni4E00": (1024, 50),
        }
    )
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


def test_caches_reference_han_metrics_by_font_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference = tmp_path / "reference.ttf"
    write_reference_font(reference)
    cache = tmp_path / "cache"
    calls = []
    measure = font_module.measure_reference_han_metrics

    def counting_measure(path: Path) -> dict:
        calls.append(path)
        return measure(path)

    monkeypatch.setattr(
        font_module,
        "measure_reference_han_metrics",
        counting_measure,
    )
    first = reference_han_metrics(reference, cache)
    second = reference_han_metrics(reference, cache)

    assert first == second
    assert calls == [reference]
    assert len(list(cache.glob("*.json"))) == 1


def test_reference_metrics_cache_invalidates_when_font_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference = tmp_path / "reference.ttf"
    write_reference_font(reference)
    cache = tmp_path / "cache"
    calls = []
    measure = font_module.measure_reference_han_metrics

    def counting_measure(path: Path) -> dict:
        calls.append(path)
        return measure(path)

    monkeypatch.setattr(
        font_module,
        "measure_reference_han_metrics",
        counting_measure,
    )
    reference_han_metrics(reference, cache)
    with TTFont(reference) as font:
        font["head"].fontRevision = 2.0
        font.save(reference)
    reference_han_metrics(reference, cache)

    assert calls == [reference, reference]
    assert len(list(cache.glob("*.json"))) == 2


def test_corrupt_reference_metrics_cache_fails_clearly(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.ttf"
    write_reference_font(reference)
    cache = tmp_path / "cache"
    reference_han_metrics(reference, cache)
    cache_path = next(cache.glob("*.json"))
    cache_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt reference metrics cache entry"):
        reference_han_metrics(reference, cache)


def test_builds_paired_fonts_and_mapping_by_default(tmp_path: Path) -> None:
    result = build(
        ["⿱弔口", "⿰鳥叴"],
        tmp_path,
        delay=0,
        resolver=resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
    assert mapping["fonts"] == {
        output_format: path.name
        for output_format, path in result.font_paths.items()
    }
    assert mapping["font_formats"] == ["woff2", "ttf"]
    assert result.style_path == tmp_path / "ids-glyphs.sty"
    assert set(mapping["glyphs"]) == {"⿰鳥叴", "⿱弔口"}
    assert mapping["mode"] == "ligature"
    assert "assignments" not in mapping
    assert set(TTFont(result.font_path).getBestCmap()) == {
        0x2FF0,
        0x2FF1,
        0x53E3,
        0x53F4,
        0x5F14,
        0x9CE5,
    }
    assert mapping["glyph_license"] == "GPL-3.0-only"


def test_builds_local_question_tofu_with_selected_style(tmp_path: Path) -> None:
    calls = []

    def unexpected_resolver(ids: str) -> SvgResolution:
        calls.append(ids)
        raise AssertionError("Question tofu should not use Zi.tools.")

    result = build(
        ["?"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=unexpected_resolver,
        lacuna_style="dashes",
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))

    assert calls == []
    assert mapping["glyphs"]["?"] == {
        "glyph": "ids00000",
        "synthetic_tofu": True,
        "lacuna_style": "dashes",
        "outline_provider": "synthetic",
    }
    with TTFont(result.font_path) as font:
        assert font.getBestCmap() == {ord("?"): "uni003F"}
        assert font["hmtx"]["uni003F"] == (0, 0)
        assert font["glyf"]["ids00000"].numberOfContours > 2


def test_question_tofu_uses_match_font_question_mark(tmp_path: Path) -> None:
    reference = tmp_path / "reference.ttf"
    write_reference_font(reference)

    result = build(
        ["?"],
        tmp_path / "build",
        output_format="ttf",
        match_font=reference,
        delay=0,
        resolver=lambda ids: pytest.fail(f"Unexpected lookup for {ids}"),
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))

    assert mapping["glyphs"]["?"]["outline_provider"] == "reference.ttf"
    assert mapping["glyphs"]["?"]["outline_character"] == "?"


def test_builds_required_ligature_font_with_zero_width_components(
    tmp_path: Path,
) -> None:
    result = build(
        ["⿰鳥叴", "⿱弔口"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
    assert mapping["mode"] == "ligature"
    assert "assignments" not in mapping
    style = result.style_path.read_text(encoding="utf-8")
    assert r"\__ids_to_font_literal:n" in style
    assert r"\prop_gput:Nnn \g__ids_to_font_supported_prop" in style
    assert r"\char_generate:nn" not in style
    with TTFont(result.font_path) as font:
        cmap = font.getBestCmap()
        assert set(cmap) == {0x2FF0, 0x2FF1, 0x53E3, 0x53F4, 0x5F14, 0x9CE5}
        assert all(font["hmtx"][name] == (0, 0) for name in cmap.values())
        assert all(
            record["glyph"] not in cmap.values()
            for record in mapping["glyphs"].values()
        )
        features = font["GSUB"].table.FeatureList.FeatureRecord
        assert [record.FeatureTag for record in features] == ["rlig"]
        lookup = font["GSUB"].table.LookupList.Lookup[0]
        ligature = lookup.SubTable[0].ligatures["uni2FF0"][0]
        assert ligature.LigGlyph == "ids00000"
        assert ligature.CompCount == 3


def test_ligature_mode_reuses_component_placeholders(tmp_path: Path) -> None:
    result = build(
        ["⿰鳥叴", "⿲鳥叴鳥"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=resolution,
    )
    with TTFont(result.font_path) as font:
        assert set(font.getBestCmap()) == {0x2FF0, 0x2FF2, 0x53F4, 0x9CE5}


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


def test_builds_both_formats_with_one_manifest_and_package(tmp_path: Path) -> None:
    result = build(
        ["⿰鳥叴", "⿱弔口"],
        tmp_path,
        output_format="both",
        delay=0,
        resolver=resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))

    assert set(result.font_paths) == {"woff2", "ttf"}
    assert mapping["fonts"] == {
        output_format: path.name
        for output_format, path in result.font_paths.items()
    }
    assert mapping["font_formats"] == ["woff2", "ttf"]
    assert "font" not in mapping
    assert "font_format" not in mapping
    assert mapping["latex_package"] == "ids-glyphs.sty"
    assert result.style_path == tmp_path / "ids-glyphs.sty"
    assert result.font_paths["ttf"].name in result.style_path.read_text(
        encoding="utf-8"
    )
    assert "Ligatures=Required" in result.style_path.read_text(encoding="utf-8")
    assert "Script=CJK" in result.style_path.read_text(encoding="utf-8")
    assert r"\tex_XeTeXgenerateactualtext:D = 1" in result.style_path.read_text(
        encoding="utf-8"
    )
    assert r"\tex_XeTeXcharclass:D `##1 = 0" in result.style_path.read_text(
        encoding="utf-8"
    )
    with (
        TTFont(result.font_paths["woff2"]) as woff2,
        TTFont(result.font_paths["ttf"]) as ttf,
    ):
        assert woff2.getBestCmap() == ttf.getBestCmap()
        assert woff2.getGlyphOrder() == ttf.getGlyphOrder()


def test_ttf_package_validates_and_emits_literal_ids(
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
    assert r"\prop_gput:Nnn \g__ids_to_font_supported_prop { ⿰鳥叴 }" in style
    assert r"\prop_gput:Nnn \g__ids_to_font_supported_prop { ⿱弔口 }" in style
    assert r"\char_generate:nn" not in style
    assert r"\NewDocumentCommand \ids { m }" in style
    assert r"\NewDocumentCommand \idschar { m }" in style
    assert r"\__ids_to_font_typeset_literal:n { #1 }" in style


def test_xelatex_package_preserves_literal_ids_with_xecjk(
    tmp_path: Path,
) -> None:
    xelatex = shutil.which("xelatex")
    pdftotext = shutil.which("pdftotext")
    kpsewhich = shutil.which("kpsewhich")
    if xelatex is None or pdftotext is None or kpsewhich is None:
        pytest.skip("XeLaTeX integration tools are unavailable.")
    xecjk = subprocess.run(
        [kpsewhich, "xeCJK.sty"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not xecjk:
        pytest.skip("xeCJK is unavailable.")

    result = build(
        ["⿰鳥叴", "⿰□區"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=resolution,
    )
    font_name = result.font_paths["ttf"].name
    (tmp_path / "specimen.tex").write_text(
        rf"""\documentclass{{article}}
\usepackage{{xeCJK}}
\setCJKmainfont[Path=./]{{{font_name}}}
\usepackage{{ids-glyphs}}
\pagestyle{{empty}}
\begin{{document}}
START-A:\ids{{⿰鳥叴}}:END-A

START-B:\ids{{⿰□區}}:END-B
\end{{document}}
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            xelatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "specimen.tex",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    extracted = subprocess.run(
        [pdftotext, "specimen.pdf", "-"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout

    assert "START-A:⿰鳥叴:END-A" in extracted
    assert "START-B:⿰□區:END-B" in extracted


def test_builds_encoded_unicode_supplement_and_alias_package(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary.ttf"
    write_reference_font(primary)
    result = build_encoded(
        ["𬘄"],
        tmp_path / "output",
        output_format="ttf",
        latex_primary_font=primary,
        delay=0,
        resolver=encoded_resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
    assert mapping["mode"] == "unicode"
    assert mapping["glyphs"]["𬘄"] == {
        "character": "𬘄",
        "codepoint": "U+2C604",
        "decompositions": ["⿲糹叀糹", "⿰𦁆糸"],
        "preferred_decomposition": "⿲糹叀糹",
    }
    assert mapping["latex_primary_font"] == "primary.ttf"
    with TTFont(result.font_path) as font:
        assert set(font.getBestCmap()) == {0x2C604}
        assert font.getBestCmap()[0x2C604] == "u2C604"
    style = result.style_path.read_text(encoding="utf-8")
    assert "{ ⿲糹叀糹 } { \\char_generate:nn { \"2C604 } { 12 } }" in style
    assert r"\setCJKfallbackfamilyfont" in style
    assert "luaotfload.add_fallback" in style
    assert r"\idshanfamily" in style


def test_builds_encoded_supplement_in_both_formats(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary.ttf"
    write_reference_font(primary)
    result = build_encoded(
        ["𬘄"],
        tmp_path / "output",
        output_format="both",
        latex_primary_font=primary,
        delay=0,
        resolver=encoded_resolution,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))

    assert set(result.font_paths) == {"woff2", "ttf"}
    assert mapping["fonts"] == {
        output_format: path.name
        for output_format, path in result.font_paths.items()
    }
    assert mapping["font_formats"] == ["woff2", "ttf"]
    assert mapping["latex_package"] == "unicode-supplement.sty"
    assert result.font_paths["ttf"].name in result.style_path.read_text(
        encoding="utf-8"
    )
    with (
        TTFont(result.font_paths["woff2"]) as woff2,
        TTFont(result.font_paths["ttf"]) as ttf,
    ):
        assert woff2.getBestCmap() == ttf.getBestCmap() == {0x2C604: "u2C604"}


def test_rejects_ambiguous_encoded_decomposition(tmp_path: Path) -> None:
    def ambiguous(character: str) -> EncodedResolution:
        return EncodedResolution(
            character=character,
            decompositions=("⿰甲乙",),
            view_box="0 0 95 95",
            paths=resolution("⿰甲乙").paths,
        )

    with pytest.raises(ValueError, match="ambiguous"):
        build_encoded(
            ["𬘄", "𦸗"],
            tmp_path,
            output_format="ttf",
            delay=0,
            resolver=ambiguous,
        )


def test_generated_glyphs_mark_overlapping_contours(tmp_path: Path) -> None:
    result = build(
        ["⿰鳥叴"],
        tmp_path,
        output_format="ttf",
        delay=0,
        resolver=resolution,
    )
    with TTFont(result.font_path) as font:
        mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
        glyph_name = mapping["glyphs"]["⿰鳥叴"]["glyph"]
        glyph = font["glyf"][glyph_name]
        assert glyph.numberOfContours > 0
        assert glyph.flags[0] & flagOverlapSimple


def test_density_geometry_supports_curves_and_counters() -> None:
    geometry = glyph_geometry(resolution_to_glyph(curved_counter_resolution("⿰鳥叴")))

    assert geometry.area > 100_000
    assert not geometry.contains(Point(512, 390))


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
        mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
        glyph_name = mapping["glyphs"]["⿰鳥叴"]["glyph"]
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
        glyph_name = mapping["glyphs"]["⿰鳥叴"]["glyph"]
        glyph = font["glyf"][glyph_name]
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
        glyph_name = mapping["glyphs"]["⿰鳥叴"]["glyph"]
        glyph = font["glyf"][glyph_name]
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
