"""Convert Zi.tools SVG path data into a TrueType or WOFF2 font."""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import tempfile
import warnings
from math import acos, ceil, hypot, pi
from datetime import UTC, datetime
from pathlib import Path

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import flagOnCurve, flagOverlapSimple
from shapely import make_valid
from shapely.affinity import scale as scale_geometry
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .zi_tools import SvgResolution


REFERENCE_METRICS_CACHE_VERSION = "1"


def empty_glyph():
    return TTGlyphPen(None).glyph()


def unicode_glyph_name(codepoint: int) -> str:
    return f"uni{codepoint:04X}" if codepoint <= 0xFFFF else f"u{codepoint:X}"


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


def reference_metrics_cache_directory() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "ids-to-font" / "reference-metrics"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_reference_metrics_cache(path: Path, font_digest: str) -> dict | None:
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Corrupt reference metrics cache entry {path}: {error}") from error
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != REFERENCE_METRICS_CACHE_VERSION
        or record.get("font_sha256") != font_digest
        or not isinstance(record.get("metrics"), dict)
    ):
        raise ValueError(
            f"Corrupt reference metrics cache entry {path}: invalid metadata."
        )
    return record["metrics"]


def write_reference_metrics_cache(
    path: Path,
    font_digest: str,
    metrics: dict,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(
                {
                    "schema_version": REFERENCE_METRICS_CACHE_VERSION,
                    "font_sha256": font_digest,
                    "metrics": metrics,
                },
                temporary,
                separators=(",", ":"),
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def measure_reference_han_metrics(path: Path) -> dict:
    """Measure full-width Han glyphs and line metrics in a reference font."""
    with TTFont(path) as font:
        upm = font["head"].unitsPerEm
        cmap = font.getBestCmap()
        glyph_set = font.getGlyphSet()
        records = []
        for codepoint, glyph_name in cmap.items():
            if not 0x4E00 <= codepoint <= 0x9FFF:
                continue
            advance = font["hmtx"][glyph_name][0] * 1024 / upm
            if not 900 <= advance <= 1150:
                continue
            bounds_pen = BoundsPen(glyph_set)
            glyph_set[glyph_name].draw(bounds_pen)
            if bounds_pen.bounds is None:
                continue
            records.append(
                (
                    glyph_name,
                    tuple(
                    value * 1024 / upm
                    for value in bounds_pen.bounds
                    ),
                )
            )
        boxes = [bounds for _, bounds in records]
        height, center = median_vertical_bounds(boxes)
        density_records = records
        if len(density_records) > 2048:
            step = len(density_records) / 2048
            density_records = [
                density_records[int(index * step)]
                for index in range(2048)
            ]
        densities = []
        for glyph_name, bounds in density_records:
            area_pen = AreaPen(glyph_set)
            glyph_set[glyph_name].draw(area_pen)
            left, bottom, right, top = bounds
            box_area = (right - left) * (top - bottom)
            if box_area > 0:
                densities.append(abs(area_pen.value) * (1024 / upm) ** 2 / box_area)

        def normalized(value: int) -> int:
            return round(value * 1024 / upm)

        return {
            "sample_size": len(boxes),
            "density_sample_size": len(densities),
            "density": statistics.median(densities),
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


def reference_han_metrics(
    path: Path,
    cache_directory: Path | None = None,
) -> dict:
    font_sha256 = file_digest(path)
    directory = cache_directory or reference_metrics_cache_directory()
    cache_path = directory / (
        f"{REFERENCE_METRICS_CACHE_VERSION}-{font_sha256}.json"
    )
    cached = read_reference_metrics_cache(cache_path, font_sha256)
    if cached is not None:
        return cached
    metrics = measure_reference_han_metrics(path)
    write_reference_metrics_cache(cache_path, font_sha256, metrics)
    return metrics


def flatten_contour(coordinates, flags, start: int, end: int) -> list[tuple[float, float]]:
    points = [
        (tuple(coordinates[index]), bool(flags[index] & flagOnCurve))
        for index in range(start, end + 1)
    ]
    if points[0][1]:
        first = points[0][0]
        remaining = points[1:]
    elif points[-1][1]:
        first = points[-1][0]
        remaining = points[:-1]
    else:
        first = (
            (points[-1][0][0] + points[0][0][0]) / 2,
            (points[-1][0][1] + points[0][0][1]) / 2,
        )
        remaining = points
    flattened = [first]
    current = first
    index = 0
    while index < len(remaining):
        point, on_curve = remaining[index]
        if on_curve:
            flattened.append(point)
            current = point
            index += 1
            continue
        if index + 1 < len(remaining):
            following, following_on_curve = remaining[index + 1]
        else:
            following, following_on_curve = first, True
        target = (
            following
            if following_on_curve
            else (
                (point[0] + following[0]) / 2,
                (point[1] + following[1]) / 2,
            )
        )
        steps = min(
            32,
            max(
                4,
                ceil(
                    (
                        hypot(point[0] - current[0], point[1] - current[1])
                        + hypot(target[0] - point[0], target[1] - point[1])
                    )
                    / 16
                ),
            ),
        )
        for step in range(1, steps + 1):
            ratio = step / steps
            inverse = 1 - ratio
            flattened.append(
                (
                    inverse * inverse * current[0]
                    + 2 * inverse * ratio * point[0]
                    + ratio * ratio * target[0],
                    inverse * inverse * current[1]
                    + 2 * inverse * ratio * point[1]
                    + ratio * ratio * target[1],
                )
            )
        current = target
        index += 2 if following_on_curve else 1
    return flattened


def signed_area(points: list[tuple[float, float]]) -> float:
    return sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, [*points[1:], points[0]])
    ) / 2


def glyph_contour_geometries(glyph):
    coordinates, end_points, flags = glyph.getCoordinates(None)
    contours = []
    start = 0
    for end in end_points:
        points = flatten_contour(coordinates, flags, start, end)
        geometry = make_valid(Polygon(points))
        if not geometry.is_empty:
            contours.append((signed_area(points), geometry))
        start = end + 1
    if not contours:
        raise ValueError("A generated glyph has no fillable outline.")
    outer_sign = -1 if max(contours, key=lambda item: abs(item[0]))[0] < 0 else 1
    holes = unary_union(
        [geometry for area, geometry in contours if area * outer_sign < 0]
    )
    return [
        polygon
        for area, geometry in contours
        if area * outer_sign > 0
        for polygon in polygon_parts(
            make_valid(geometry.difference(holes))
        )
        if not polygon.is_empty
    ], holes


def glyph_geometry(glyph):
    """Return the filled geometry of a generated glyph."""
    filled_contours, holes = glyph_contour_geometries(glyph)
    outers = unary_union(filled_contours)
    return make_valid(outers.difference(holes))


def polygon_parts(geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [
        polygon
        for part in getattr(geometry, "geoms", ())
        for polygon in polygon_parts(part)
    ]


def geometry_to_glyph(geometry):
    pen = TTGlyphPen(None)

    def draw_ring(coordinates) -> None:
        points = [(round(x), round(y)) for x, y in list(coordinates)[:-1]]
        if len(points) < 3:
            return
        pen.moveTo(points[0])
        for point in points[1:]:
            pen.lineTo(point)
        pen.closePath()

    for polygon in polygon_parts(geometry):
        polygon = orient(polygon, sign=-1.0)
        draw_ring(polygon.exterior.coords)
        for interior in polygon.interiors:
            draw_ring(interior.coords)
    glyph = pen.glyph()
    if glyph.numberOfContours <= 0:
        raise ValueError("Density matching removed an entire glyph.")
    return glyph


def geometry_density(geometry) -> float:
    left, bottom, right, top = geometry.bounds
    box_area = (right - left) * (top - bottom)
    return geometry.area / box_area if box_area > 0 else 0


def fit_protected_geometry(geometry):
    """Keep synthetic markers within the font's horizontal safe area."""
    left, _, right, _ = geometry.bounds
    factors = [1.0]
    if left < 512:
        factors.append(488 / (512 - left))
    if right > 512:
        factors.append(488 / (right - 512))
    horizontal_scale = min(factors)
    if horizontal_scale >= 1:
        return geometry
    return make_valid(
        scale_geometry(
            geometry,
            xfact=horizontal_scale,
            yfact=1,
            origin=(512, 0),
        )
    )


def adaptive_thinning_inset(radius: float) -> float:
    """Return the local inset for a stroke with the given half-width."""
    if radius <= 2:
        return 0
    if radius < 6:
        return (radius - 2) / 4
    if radius < 14:
        return 1 + 3 * (radius - 6) / 8
    return 4


def adaptive_ring_coordinates(coordinates, geometry):
    points = list(coordinates)[:-1]
    adjusted = []
    for index, (x, y) in enumerate(points):
        previous_x, previous_y = points[index - 1]
        next_x, next_y = points[(index + 1) % len(points)]
        tangent_x = next_x - previous_x
        tangent_y = next_y - previous_y
        tangent_length = hypot(tangent_x, tangent_y)
        if tangent_length == 0:
            adjusted.append((x, y))
            continue
        inward_x = -tangent_y / tangent_length
        inward_y = tangent_x / tangent_length
        if not geometry.covers(
            Point(x + inward_x * 0.1, y + inward_y * 0.1)
        ):
            inward_x = -inward_x
            inward_y = -inward_y
        if not geometry.covers(
            Point(x + inward_x * 0.1, y + inward_y * 0.1)
        ):
            adjusted.append((x, y))
            continue

        inside = 0.1
        outside = 1.0
        while outside < 128 and geometry.covers(
            Point(x + inward_x * outside, y + inward_y * outside)
        ):
            inside = outside
            outside *= 2
        if outside >= 128 and geometry.covers(
            Point(x + inward_x * outside, y + inward_y * outside)
        ):
            width = 128
        else:
            for _ in range(8):
                middle = (inside + outside) / 2
                if geometry.covers(
                    Point(x + inward_x * middle, y + inward_y * middle)
                ):
                    inside = middle
                else:
                    outside = middle
            width = inside

        previous_length = hypot(previous_x - x, previous_y - y)
        next_length = hypot(next_x - x, next_y - y)
        if previous_length == 0 or next_length == 0:
            corner_factor = 0
        else:
            cosine = (
                (previous_x - x) * (next_x - x)
                + (previous_y - y) * (next_y - y)
            ) / (previous_length * next_length)
            angle = acos(max(-1, min(1, cosine)))
            corner_factor = max(
                0,
                min(1, (angle - pi / 4) / (pi / 2)),
            )
        inset = adaptive_thinning_inset(width / 2) * corner_factor
        adjusted.append((x + inward_x * inset, y + inward_y * inset))
    return adjusted


def adaptive_thin_polygon(source: Polygon):
    source = orient(source.segmentize(4), sign=1.0)
    candidate = make_valid(
        Polygon(
            adaptive_ring_coordinates(source.exterior.coords, source),
            [
                adaptive_ring_coordinates(interior.coords, source)
                for interior in source.interiors
            ],
        )
    )
    candidate = make_valid(candidate.intersection(source))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        core = make_valid(source.buffer(-4, join_style="mitre"))
        reopened = (
            make_valid(core.buffer(4, join_style="mitre"))
            if not core.is_empty
            else core
        )
    protected = make_valid(source.difference(reopened))
    candidate = make_valid(
        unary_union([candidate, protected]).intersection(source)
    )
    candidate = unary_union(polygon_parts(candidate))
    if (
        candidate.is_empty
        or len(polygon_parts(candidate)) != 1
    ):
        return source
    return candidate


def adaptive_thin_geometry(geometry):
    """Smoothly thin broad regions while retaining narrow joins and terminals."""
    geometry = make_valid(geometry)
    candidate = make_valid(
        unary_union([
            adaptive_thin_polygon(polygon)
            for polygon in polygon_parts(geometry)
        ])
    )
    candidate = unary_union(polygon_parts(candidate))
    if candidate.is_empty or not polygon_parts(candidate):
        raise ValueError("Adaptive outline thinning removed an entire glyph.")
    return candidate


def match_glyph_density(
    glyphs: dict,
    target_density: float,
    protected_glyphs: dict | None = None,
) -> dict:
    """Match density without uniformly eroding narrow strokes and terminals."""
    protected_glyphs = protected_glyphs or {}
    protected_geometries = {
        name: glyph_geometry(glyph)
        for name, glyph in protected_glyphs.items()
        if glyph.numberOfContours > 0
    }
    fitted_protected_geometries = {
        name: fit_protected_geometry(geometry)
        for name, geometry in protected_geometries.items()
    }
    geometries = {
        name: glyph_geometry(glyph)
        for name, glyph in glyphs.items()
        if name != ".notdef" and glyph.numberOfContours > 0
    }
    candidates = [value / 2 for value in range(-6, 1)]
    results = []
    for inset in candidates:
        adjusted = {}
        safe = True
        for name, geometry in geometries.items():
            protected = protected_geometries.get(name)
            fitted_protected = fitted_protected_geometries.get(name)
            adjustable = (
                make_valid(geometry.difference(protected))
                if protected is not None
                else geometry
            )
            if inset == 0:
                candidate = adjustable
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    candidate = adjustable.buffer(
                        -inset,
                        join_style="mitre",
                    )
            if fitted_protected is not None:
                candidate = unary_union([candidate, fitted_protected])
            candidate = make_valid(candidate)
            if candidate.is_empty or not polygon_parts(candidate):
                safe = False
                break
            adjusted[name] = candidate
        if not safe:
            continue
        density = statistics.median(
            geometry_density(geometry) for geometry in adjusted.values()
        )
        results.append(
            (
                abs(density - target_density),
                abs(inset),
                inset,
                density,
                adjusted,
                "uniform",
            )
        )
    source_density = statistics.median(
        geometry_density(geometry) for geometry in geometries.values()
    )
    if source_density > target_density:
        adjusted = {}
        for name, geometry in geometries.items():
            protected = protected_geometries.get(name)
            fitted_protected = fitted_protected_geometries.get(name)
            adjustable = (
                make_valid(geometry.difference(protected))
                if protected is not None
                else geometry
            )
            candidate = adaptive_thin_geometry(adjustable)
            if fitted_protected is not None:
                candidate = make_valid(
                    unary_union([candidate, fitted_protected])
                )
            adjusted[name] = candidate
        density = statistics.median(
            geometry_density(geometry) for geometry in adjusted.values()
        )
        results.append(
            (
                abs(density - target_density),
                4.0,
                4.0,
                density,
                adjusted,
                "adaptive",
            )
        )
    if not results:
        raise ValueError("No safe outline-weight adjustment could be found.")
    _, _, inset, density, adjusted, mode = min(
        results,
        key=lambda result: result[:3],
    )
    if inset:
        for name, geometry in adjusted.items():
            glyphs[name] = geometry_to_glyph(geometry)
    return {
        "target_density": target_density,
        "matched_density": density,
        "inset": inset,
        "outline_adjustment": mode,
    }


def calibrate_glyphs(
    glyphs: dict,
    match_font: Path | None,
    protected_glyphs: dict | None = None,
) -> dict | None:
    """Scale and shift generated glyphs to match a reference Han font."""
    if match_font is None:
        return None
    protected_glyphs = protected_glyphs or {}
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
    for glyph_set in (glyphs, protected_glyphs):
        for glyph_name, glyph in glyph_set.items():
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
    density = match_glyph_density(
        glyphs,
        target["density"],
        protected_glyphs,
    )
    return {
        **target,
        "source_height": source_height,
        "source_center": source_center,
        "scale": scale,
        "vertical_shift": vertical_shift,
        **density,
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
        ids: (
            f"uni{codepoint:04X}"
            if codepoint <= 0xFFFF
            else f"u{codepoint:X}"
        )
        for ids, codepoint in active.items()
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


def build_ligature_font(
    resolutions: dict[str, SvgResolution],
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

    expressions = sorted(resolutions)
    output_names = {
        expression: f"ids{index:05d}"
        for index, expression in enumerate(expressions)
    }
    component_codepoints = sorted(
        {ord(character) for expression in expressions for character in expression}
    )
    component_names = {
        codepoint: unicode_glyph_name(codepoint)
        for codepoint in component_codepoints
    }
    glyph_order = [
        ".notdef",
        *[component_names[codepoint] for codepoint in component_codepoints],
        *[output_names[expression] for expression in expressions],
    ]
    glyphs = {".notdef": empty_glyph()}
    glyphs.update(
        {
            component_names[codepoint]: empty_glyph()
            for codepoint in component_codepoints
        }
    )
    glyphs.update(
        {
            output_names[expression]: resolution_to_glyph(resolutions[expression])
            for expression in expressions
        }
    )
    protected_glyphs = {
        output_names[expression]: resolution_to_glyph(
            SvgResolution(
                requested_ids=expression,
                resolved_ids=expression,
                view_box=resolutions[expression].view_box,
                paths=(resolutions[expression].paths[-1],),
            )
        )
        for expression in expressions
        if (
            resolutions[expression].metadata.get("synthetic_lacuna")
            or resolutions[expression].metadata.get("synthetic_tofu")
        )
    }
    calibration = calibrate_glyphs(
        glyphs,
        match_font,
        protected_glyphs,
    )
    metrics = {
        ".notdef": (0, 0),
        **{
            component_names[codepoint]: (0, 0)
            for codepoint in component_codepoints
        },
        **{
            output_names[expression]: (1024, 24)
            for expression in expressions
        },
    }

    builder = FontBuilder(1024, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(
        {codepoint: component_names[codepoint] for codepoint in component_codepoints}
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
    feature_lines = [
        "languagesystem DFLT dflt;",
        "languagesystem hani dflt;",
        "feature rlig {",
        *[
            "  sub "
            + " ".join(component_names[ord(character)] for character in expression)
            + f" by {output_names[expression]};"
            for expression in sorted(expressions, key=lambda value: (-len(value), value))
        ],
        "} rlig;",
        "",
    ]
    addOpenTypeFeaturesFromString(builder.font, "\n".join(feature_lines))
    epoch = int(metadata_date.timestamp()) + 2082844800
    builder.font["head"].created = epoch
    builder.font["head"].modified = epoch
    builder.font.recalcTimestamp = False
    builder.font.flavor = "woff2" if output_format == "woff2" else None
    return builder.font, calibration, output_names
