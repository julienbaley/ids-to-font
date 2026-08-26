from __future__ import annotations

import json
import math
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

from ids_to_font.lacuna import (
    align_proxy_resolutions,
    extract_surviving_strokes,
    ids_definitions,
    lacuna_path,
    load_cjkvi_ids,
    matching_characters,
    normalize_same_axis,
    parse_ids,
    replace_lacuna,
    serialize_ids,
)
from ids_to_font.zi_tools import SvgResolution, fetch_resolution


OUTPUT = Path(__file__).with_name(
    "lacuna-17-zitools-babelstone-"
    f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.svg"
)
CACHE = Path(__file__).with_name("lacuna-zitools-cache.json")
FONT_PATH = Path(
    "/home/julien/projets/spelling/vendor/babelstone-han/BabelStoneHan.ttf"
)
EXPRESSIONS = [
    "⿰□區",
    "⿰□古",
    "⿰□台",
    "⿰□它",
    "⿰□居",
    "⿰□昜",
    "⿰□暴",
    "⿰□灰",
    "⿰□白",
    "⿰□睪",
    "⿰□胃",
    "⿰氵⿱□口",
    "⿰爿□",
    "⿱□心",
    "⿱□木",
    "⿱□皿",
    "⿱甾□",
]
PROXIES = ("丯", "巛", "巿", "爿", "𡵂")
BABELSTONE_OVERRIDES = {
    "⿰□睪": {
        "character": "澤",
        "contours": (3, 4, 5, 6),
    },
    "⿱甾□": {
        "character": "甾",
        "contours": tuple(range(8)),
        "target": (4, 4, 91, 61),
        "region": (4, 64, 91, 91),
    },
}


@dataclass(frozen=True)
class FontContour:
    path: str
    bounds: tuple[float, float, float, float]

    @property
    def center(self):
        left, top, right, bottom = self.bounds
        return (left + right) / 2, (top + bottom) / 2


def median_region(samples):
    return tuple(
        statistics.median(sample[1][index] for sample in samples)
        for index in range(4)
    )


def closest(samples, region):
    return min(
        samples,
        key=lambda sample: sum(
            (sample[1][index] - region[index]) ** 2
            for index in range(4)
        ),
    )


def valid_region(region):
    left, top, right, bottom = region
    return (
        all(math.isfinite(value) for value in region)
        and right > left
        and bottom > top
    )


def dotted_box(region):
    left, top, right, bottom = region
    inset = min(5, max(2.5, min(right - left, bottom - top) * 0.08))
    left, top = left + inset, top + inset
    right, bottom = right - inset, bottom - inset
    width, height = right - left, bottom - top
    step = max(3.8, min(width, height) / 7)
    radius = min(1, step * 0.22)
    columns = max(2, round(width / step))
    rows = max(2, round(height / step))
    centers = []
    for index in range(columns + 1):
        x = left + width * index / columns
        centers.extend(((x, top), (x, bottom)))
    for index in range(1, rows):
        y = top + height * index / rows
        centers.extend(((left, y), (right, y)))
    return "".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}"/>'
        for x, y in centers
    )


def zi_paths(strokes):
    paths = "".join(
        f'<path d="{escape(stroke.path["d"])}" '
        f'transform="{escape(stroke.path.get("transform", ""))}"/>'
        for stroke in strokes
    )
    return f'<g fill="#111" fill-rule="nonzero">{paths}</g>'


def fit_transform(bounds, target=(4, 4, 91, 91)):
    x_min, y_min, x_max, y_max = bounds
    width, height = x_max - x_min, y_max - y_min
    left, top, right, bottom = target
    target_width, target_height = right - left, bottom - top
    scale = min(target_width / width, target_height / height)
    x_offset = left + (target_width - width * scale) / 2 - x_min * scale
    y_offset = top + (target_height - height * scale) / 2 + y_max * scale
    return scale, x_offset, y_offset


def retain_enclosed_contours(all_contours, retained):
    retained_ids = {id(contour) for contour in retained}
    for contour in all_contours:
        if id(contour) in retained_ids:
            continue
        left, top, right, bottom = contour.bounds
        if any(
            parent.bounds[0] <= left
            and parent.bounds[1] <= top
            and parent.bounds[2] >= right
            and parent.bounds[3] >= bottom
            for parent in retained
        ):
            retained_ids.add(id(contour))
    return [
        contour
        for contour in all_contours
        if id(contour) in retained_ids
    ]


def font_contours(
    font,
    glyph_set,
    cmap,
    character,
    target=(4, 4, 91, 91),
):
    glyph_name = cmap[ord(character)]
    bounds_pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(bounds_pen)
    scale, x_offset, y_offset = fit_transform(bounds_pen.bounds, target)

    recording = RecordingPen()
    glyph_set[glyph_name].draw(recording)
    contour_records = []
    current = []
    for record in recording.value:
        current.append(record)
        if record[0] in {"closePath", "endPath"}:
            contour_records.append(current)
            current = []
    contours = []
    for records in contour_records:
        contour = RecordingPen()
        contour.value = records
        raw_bounds = BoundsPen(glyph_set)
        contour.replay(raw_bounds)
        if raw_bounds.bounds is None:
            continue
        left, bottom, right, top = raw_bounds.bounds
        path_pen = SVGPathPen(glyph_set)
        contour.replay(path_pen)
        contours.append(
            FontContour(
                path_pen.getCommands(),
                (
                    left * scale + x_offset,
                    -top * scale + y_offset,
                    right * scale + x_offset,
                    -bottom * scale + y_offset,
                ),
            )
        )
    return contours, (scale, x_offset, y_offset)


def babelstone_paths(contours, transform):
    scale, x_offset, y_offset = transform
    path = " ".join(contour.path for contour in contours)
    return (
        f'<path fill="#111" fill-rule="nonzero" d="{escape(path)}" '
        f'transform="matrix({scale:.8f} 0 0 {-scale:.8f} '
        f'{x_offset:.8f} {y_offset:.8f})"/>'
    )


def main():
    print(f"Writing {OUTPUT}", flush=True)
    ids_data = load_cjkvi_ids()
    definitions = ids_definitions(ids_data)
    font = TTFont(FONT_PATH)
    cmap = font.getBestCmap()
    glyph_set = font.getGlyphSet()
    patterns = {
        ids: normalize_same_axis(parse_ids(ids), definitions)
        for ids in EXPRESSIONS
    }
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    templates = {
        serialize_ids(replace_lacuna(pattern, proxy))
        for pattern in patterns.values()
        for proxy in PROXIES
    }
    missing = sorted(
        template
        for template in templates
        if template not in cache
        or (
            cache[template] is not None
            and "kage" not in cache[template]
        )
    )

    def fetch_template(template):
        try:
            resolution = fetch_resolution(template)
        except (OSError, ValueError):
            return template, None
        return template, {
            "resolved_ids": resolution.resolved_ids,
            "view_box": resolution.view_box,
            "paths": list(resolution.paths),
            "kage": list(resolution.kage),
        }

    if missing:
        print(f"Fetching {len(missing)} Zi.tools templates concurrently", flush=True)
        completed = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(fetch_template, template): template
                for template in missing
            }
            for future in as_completed(futures):
                template, value = future.result()
                cache[template] = value
                completed += 1
                print(
                    f"\rZi.tools [{completed}/{len(missing)}]",
                    end="",
                    flush=True,
                )
        print(flush=True)
        CACHE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def babelstone_sample(pattern, path):
        samples = []
        for character in matching_characters(pattern, ids_data):
            if ord(character) not in cmap:
                continue
            try:
                contours, transform = font_contours(
                    font, glyph_set, cmap, character
                )
                surviving, region = extract_surviving_strokes(
                    contours,
                    pattern,
                    path,
                )
                surviving = retain_enclosed_contours(contours, surviving)
            except ValueError:
                continue
            if not valid_region(region):
                continue
            samples.append((character, region, surviving, transform))
            if len(samples) == 8:
                break
        if not samples:
            raise ValueError("No BabelStone examples.")
        region = median_region(samples)
        sample = closest(samples, region)
        return sample[0], region, sample[2], sample[3], len(samples)

    def zi_sample(pattern, path):
        resolutions = []
        for proxy in PROXIES:
            template = serialize_ids(replace_lacuna(pattern, proxy))
            value = cache.get(template)
            if value is None or not value.get("kage"):
                continue
            resolution = SvgResolution(
                requested_ids=template,
                resolved_ids=value["resolved_ids"],
                view_box=value["view_box"],
                paths=tuple(value["paths"]),
                kage=tuple(value["kage"]),
            )
            resolutions.append((template, proxy, resolution))
        samples = [
            (name, region, surviving)
            for name, surviving, region in align_proxy_resolutions(
                resolutions,
                pattern,
                path,
            )
            if valid_region(region)
        ]
        if not samples:
            raise ValueError("No Zi.tools examples.")
        region = median_region(samples)
        sample = closest(samples, region)
        return sample[0], region, sample[2], len(samples)

    row_height = 111
    header = 32
    width = 330
    height = header + row_height * len(EXPRESSIONS) + 8
    content = []
    for index, ids in enumerate(EXPRESSIONS):
        filled = "█" * index
        empty = "·" * (len(EXPRESSIONS) - index)
        print(
            f"\r[{filled}{empty}] {index}/{len(EXPRESSIONS)} {ids}",
            end="",
            flush=True,
        )
        pattern = patterns[ids]
        path = lacuna_path(pattern)
        override = BABELSTONE_OVERRIDES.get(ids)
        if override:
            bs_character = override["character"]
            all_contours, bs_transform = font_contours(
                font,
                glyph_set,
                cmap,
                bs_character,
                override.get("target", (4, 4, 91, 91)),
            )
            bs_contours = [
                all_contours[index]
                for index in override["contours"]
            ]
            bs_contours = retain_enclosed_contours(
                all_contours,
                bs_contours,
            )
            if "region" in override:
                bs_region = override["region"]
            else:
                _, bs_region = extract_surviving_strokes(
                    all_contours,
                    pattern,
                    path,
                )
            bs_count = 1
        else:
            (
                bs_character,
                bs_region,
                bs_contours,
                bs_transform,
                bs_count,
            ) = babelstone_sample(pattern, path)
        zi_name, zi_region, zi_strokes, zi_count = zi_sample(pattern, path)
        filled = "█" * (index + 1)
        empty = "·" * (len(EXPRESSIONS) - index - 1)
        print(
            f"\r[{filled}{empty}] {index + 1}/{len(EXPRESSIONS)} {ids} "
            f"(Zi: {zi_name}; BS: {bs_character})",
            flush=True,
        )
        y = header + index * row_height
        content.append(
            f'<text class="label" x="112" y="{y + 43}">{escape(ids)}</text>'
        )
        content.append(
            f'<text class="reference" x="112" y="{y + 53}">'
            f"Zi: {escape(zi_name)} ({zi_count}); "
            f"BS: {escape(bs_character)} ({bs_count})</text>"
        )
        content.append(
            f'<g transform="translate(120 {y})">'
            f'<g fill="#111">{dotted_box(zi_region)}</g>'
            f"{zi_paths(zi_strokes)}"
            '<rect class="box" width="95" height="95"/></g>'
        )
        content.append(
            f'<g transform="translate(225 {y})">'
            f'<g fill="#111">{dotted_box(bs_region)}</g>'
            f"{babelstone_paths(bs_contours, bs_transform)}"
            '<rect class="box" width="95" height="95"/></g>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
 viewBox="0 0 {width} {height}" width="1320" height="{height * 4}">
<rect width="{width}" height="{height}" fill="white"/>
<style>
.heading {{ font: 6px sans-serif; font-weight: bold; fill: #222;
  text-anchor: middle; }}
.label {{ font: 7px sans-serif; fill: #222; text-anchor: end;
  dominant-baseline: middle; }}
.reference {{ font: 3.1px sans-serif; fill: #777; text-anchor: end; }}
.box {{ fill: none; stroke: #d22; stroke-width: .7; }}
</style>
<text class="heading" x="167.5" y="17">Zi.tools/KAGE source</text>
<text class="heading" x="272.5" y="17">BabelStone Han source</text>
{''.join(content)}
</svg>
"""
    OUTPUT.write_text(svg, encoding="utf-8")
    font.close()
    print(f"Done: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
