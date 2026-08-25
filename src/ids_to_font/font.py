"""Convert Zi.tools SVG path data into a TrueType or WOFF2 font."""

from __future__ import annotations

import re
import statistics
from datetime import UTC, datetime
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import flagOverlapSimple

from .zi_tools import SvgResolution


def empty_glyph():
    return TTGlyphPen(None).glyph()


def resolution_to_glyph(resolution: SvgResolution):
    pen = TTGlyphPen(None)
    view_x, view_y, view_width, view_height = [
        float(value) for value in resolution.view_box.split()
    ]
    if view_width <= 0 or view_height <= 0:
        raise ValueError(f"Invalid SVG viewBox for {resolution.requested_ids}.")
    scale_to_em = min(976 / view_width, 976 / view_height)
    left = 24 + (976 - view_width * scale_to_em) / 2 - view_x * scale_to_em
    top = 880 - (976 - view_height * scale_to_em) / 2 + view_y * scale_to_em
    for path in resolution.paths:
        transform = path.get("transform", "")
        match = re.fullmatch(r"scale\(([0-9.]+),([0-9.]+)\)", transform)
        if transform and match is None:
            raise ValueError(f"Unsupported SVG transform: {transform}.")
        source_x, source_y = (
            (float(match.group(1)), float(match.group(2)))
            if match
            else (1.0, 1.0)
        )
        transform = (
            source_x * scale_to_em,
            0,
            0,
            -source_y * scale_to_em,
            left,
            top,
        )
        data = path["d"]
        data = data if data.rstrip().upper().endswith("Z") else data + " Z"
        area_pen = AreaPen()
        parse_path(
            data,
            TransformPen(area_pen, transform),
        )
        transformed = TransformPen(pen, transform)
        target = (
            ReverseContourPen(transformed)
            if area_pen.value > 0
            else transformed
        )
        parse_path(data, target)
    glyph = pen.glyph()
    if glyph.numberOfContours > 0:
        glyph.flags[0] |= flagOverlapSimple
    return glyph


def median_vertical_bounds(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, float]:
    if not boxes:
        raise ValueError("No suitable glyph bounds were available for calibration.")
    heights = [top - bottom for _, bottom, _, top in boxes]
    centers = [(top + bottom) / 2 for _, bottom, _, top in boxes]
    return statistics.median(heights), statistics.median(centers)


def reference_han_metrics(path: Path) -> dict:
    """Measure full-width Han glyphs and line metrics in a reference font."""
    with TTFont(path) as font:
        upm = font["head"].unitsPerEm
        cmap = font.getBestCmap()
        glyph_set = font.getGlyphSet()
        boxes = []
        for codepoint, glyph_name in cmap.items():
            if not (
                0x3400 <= codepoint <= 0x9FFF
                or 0x20000 <= codepoint <= 0x323AF
            ):
                continue
            advance = font["hmtx"][glyph_name][0] * 1024 / upm
            if not 900 <= advance <= 1150:
                continue
            bounds_pen = BoundsPen(glyph_set)
            glyph_set[glyph_name].draw(bounds_pen)
            if bounds_pen.bounds is None:
                continue
            boxes.append(
                tuple(
                    value * 1024 / upm
                    for value in bounds_pen.bounds
                )
            )
        height, center = median_vertical_bounds(boxes)

        def normalized(value: int) -> int:
            return round(value * 1024 / upm)

        return {
            "sample_size": len(boxes),
            "height": height,
            "center": center,
            "hhea_ascent": normalized(font["hhea"].ascent),
            "hhea_descent": normalized(font["hhea"].descent),
            "hhea_line_gap": normalized(font["hhea"].lineGap),
            "typo_ascent": normalized(font["OS/2"].sTypoAscender),
            "typo_descent": normalized(font["OS/2"].sTypoDescender),
            "typo_line_gap": normalized(font["OS/2"].sTypoLineGap),
            "win_ascent": normalized(font["OS/2"].usWinAscent),
            "win_descent": normalized(font["OS/2"].usWinDescent),
        }


def calibrate_glyphs(glyphs: dict, match_font: Path | None) -> dict | None:
    """Scale and shift generated glyphs to match a reference Han font."""
    if match_font is None:
        return None
    source_boxes = []
    for glyph_name, glyph in glyphs.items():
        if glyph_name == ".notdef" or glyph.numberOfContours <= 0:
            continue
        glyph.recalcBounds(None)
        source_boxes.append((glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax))
    source_height, source_center = median_vertical_bounds(source_boxes)
    target = reference_han_metrics(match_font)
    scale = target["height"] / source_height
    vertical_shift = target["center"] - source_center * scale
    for glyph_name, glyph in glyphs.items():
        if glyph_name == ".notdef" or glyph.numberOfContours <= 0:
            continue
        coordinates, _, _ = glyph.getCoordinates(None)
        for index, (x, y) in enumerate(coordinates):
            coordinates[index] = (
                round(512 + (x - 512) * scale),
                round(y * scale + vertical_shift),
            )
        glyph.coordinates = coordinates
        glyph.recalcBounds(None)
    return {
        **target,
        "source_height": source_height,
        "source_center": source_center,
        "scale": scale,
        "vertical_shift": vertical_shift,
    }


def build_font(
    resolutions: dict[str, SvgResolution],
    assignments: dict[str, int],
    family_name: str,
    font_date: str,
    copyright_notice: str,
    output_format: str,
    match_font: Path | None,
):
    try:
        metadata_date = datetime.fromisoformat(f"{font_date}T00:00:00+00:00")
    except ValueError as error:
        raise ValueError("Font date must use YYYY-MM-DD format.") from error
    active = {ids: assignments[ids] for ids in resolutions}
    glyph_names = {
        ids: f"uni{codepoint:04X}" for ids, codepoint in active.items()
    }
    ordered_ids = sorted(active, key=lambda ids: active[ids])
    glyph_order = [".notdef"] + [glyph_names[ids] for ids in ordered_ids]
    glyphs = {".notdef": empty_glyph()}
    glyphs.update(
        {
            glyph_names[ids]: resolution_to_glyph(resolutions[ids])
            for ids in ordered_ids
        }
    )
    calibration = calibrate_glyphs(glyphs, match_font)
    metrics = {glyph_name: (1024, 24) for glyph_name in glyph_order}

    builder = FontBuilder(1024, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(
        {codepoint: glyph_names[ids] for ids, codepoint in active.items()}
    )
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(
        ascent=calibration["hhea_ascent"] if calibration else 1020,
        descent=calibration["hhea_descent"] if calibration else -244,
        lineGap=calibration["hhea_line_gap"] if calibration else 0,
    )
    builder.setupOS2(
        sTypoAscender=calibration["typo_ascent"] if calibration else 1020,
        sTypoDescender=calibration["typo_descent"] if calibration else -244,
        sTypoLineGap=calibration["typo_line_gap"] if calibration else 0,
        usWinAscent=calibration["win_ascent"] if calibration else 1020,
        usWinDescent=calibration["win_descent"] if calibration else 244,
    )
    postscript_name = re.sub(r"[^A-Za-z0-9-]", "", family_name.replace(" ", ""))
    builder.setupNameTable(
        {
            "familyName": family_name,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{family_name} {font_date}",
            "fullName": family_name,
            "psName": postscript_name or "IDSGlyphs",
            "version": "Version 1.0",
            "copyright": copyright_notice,
            "licenseDescription": "GNU General Public License, version 3.",
            "licenseInfoURL": "https://www.gnu.org/licenses/gpl-3.0.html",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    epoch = int(metadata_date.timestamp()) + 2082844800
    builder.font["head"].created = epoch
    builder.font["head"].modified = epoch
    builder.font.recalcTimestamp = False
    builder.font.flavor = "woff2" if output_format == "woff2" else None
    return builder.font, calibration
