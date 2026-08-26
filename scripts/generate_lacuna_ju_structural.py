from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

from ids_to_font.lacuna import svg_strokes
from ids_to_font.zi_tools import SvgResolution


HERE = Path(__file__).parent
CACHE = HERE / "lacuna-zitools-cache.json"
OUTPUT = HERE / "lacuna-ju-structural.svg"
FONT_PATH = Path(
    "/home/julien/projets/spelling/vendor/babelstone-han/BabelStoneHan.ttf"
)


def dotted_box(region):
    left, top, right, bottom = region
    step = max(3.8, min(right - left, bottom - top) / 7)
    radius = min(1, step * 0.22)
    columns = max(2, round((right - left) / step))
    rows = max(2, round((bottom - top) / step))
    centers = []
    for index in range(columns + 1):
        x = left + (right - left) * index / columns
        centers.extend(((x, top), (x, bottom)))
    for index in range(1, rows):
        y = top + (bottom - top) * index / rows
        centers.extend(((left, y), (right, y)))
    return "".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}"/>'
        for x, y in centers
    )


def zi_tools_example():
    template = "⿰爿居"
    value = json.loads(CACHE.read_text(encoding="utf-8"))[template]
    resolution = SvgResolution(
        requested_ids=template,
        resolved_ids=value["resolved_ids"],
        view_box=value["view_box"],
        paths=tuple(value["paths"]),
    )
    strokes = svg_strokes(resolution)
    retained = [
        stroke.path
        for stroke in strokes
        if stroke.bounds[0] >= 35
    ]
    paths = "".join(
        f'<path d="{escape(path["d"])}" '
        f'transform="{escape(path.get("transform", ""))}"/>'
        for path in retained
    )
    return (4, 4, 35, 91), paths, len(retained)


def babelstone_example():
    font = TTFont(FONT_PATH)
    cmap = font.getBestCmap()
    glyph_set = font.getGlyphSet()
    glyph_name = cmap[ord("崌")]
    full_bounds_pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(full_bounds_pen)
    x_min, y_min, x_max, y_max = full_bounds_pen.bounds
    glyph = deepcopy(font["glyf"][glyph_name])
    coordinates, end_points, flags = glyph.getCoordinates(font["glyf"])

    # In 崌, contours 0-3 are the contextual 居; contour 4 is 山.
    glyph.coordinates = coordinates[: end_points[3] + 1]
    glyph.endPtsOfContours = end_points[:4]
    glyph.flags = flags[: end_points[3] + 1]
    glyph.numberOfContours = 4

    scale = min(87 / (x_max - x_min), 87 / (y_max - y_min))
    x_offset = 4 + (87 - (x_max - x_min) * scale) / 2 - x_min * scale
    y_offset = 4 + (87 - (y_max - y_min) * scale) / 2 + y_max * scale

    path_pen = SVGPathPen(glyph_set)
    glyph.draw(path_pen, font["glyf"])
    path = (
        f'<path d="{escape(path_pen.getCommands())}" '
        f'transform="matrix({scale:.8f} 0 0 {-scale:.8f} '
        f'{x_offset:.8f} {y_offset:.8f})"/>'
    )
    font.close()
    return (4, 4, 34, 91), path, 4


def main():
    zi_region, zi_paths, zi_count = zi_tools_example()
    bs_region, bs_path, bs_count = babelstone_example()
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
 viewBox="0 0 230 132" width="920" height="528">
<rect width="230" height="132" fill="white"/>
<style>
.heading {{ font: bold 6px sans-serif; text-anchor: middle; }}
.note {{ font: 4px sans-serif; text-anchor: middle; fill: #666; }}
.frame {{ fill: none; stroke: #d22; stroke-width: .7; }}
</style>
<text class="heading" x="62.5" y="12">Zi.tools: retained KAGE strokes</text>
<text class="heading" x="167.5" y="12">BabelStone: retained contours</text>
<text class="note" x="62.5" y="120">{zi_count} 居 stroke paths; no mask</text>
<text class="note" x="167.5" y="120">{bs_count} 居 contours; no mask</text>
<g transform="translate(15 18)">
  <g fill="#111">{dotted_box(zi_region)}</g>
  <g fill="#111" fill-rule="nonzero">{zi_paths}</g>
  <rect class="frame" width="95" height="95"/>
</g>
<g transform="translate(120 18)">
  <g fill="#111">{dotted_box(bs_region)}</g>
  <g fill="#111" fill-rule="nonzero">{bs_path}</g>
  <rect class="frame" width="95" height="95"/>
</g>
</svg>
"""
    OUTPUT.write_text(svg, encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
