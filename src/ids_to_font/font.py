"""Convert Zi.tools SVG path data into a TrueType or WOFF2 font."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
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
        transformed = TransformPen(
            pen,
            (
                source_x * scale_to_em,
                0,
                0,
                -source_y * scale_to_em,
                left,
                top,
            ),
        )
        data = path["d"]
        parse_path(
            data if data.rstrip().upper().endswith("Z") else data + " Z",
            transformed,
        )
    glyph = pen.glyph()
    if glyph.numberOfContours > 0:
        glyph.flags[0] |= flagOverlapSimple
    return glyph


def build_font(
    resolutions: dict[str, SvgResolution],
    assignments: dict[str, int],
    family_name: str,
    font_date: str,
    copyright_notice: str,
    output_format: str,
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
    metrics = {glyph_name: (1024, 24) for glyph_name in glyph_order}

    builder = FontBuilder(1024, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(
        {codepoint: glyph_names[ids] for ids, codepoint in active.items()}
    )
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=1020, descent=-244)
    builder.setupOS2(
        sTypoAscender=1020,
        sTypoDescender=-244,
        usWinAscent=1020,
        usWinDescent=244,
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
    return builder.font
