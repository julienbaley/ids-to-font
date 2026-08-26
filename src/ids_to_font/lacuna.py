"""Synthesize IDS outlines containing a dotted lacuna component."""

from __future__ import annotations

import os

import re
import statistics
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .zi_tools import EncodedResolution, SvgResolution


LACUNA = "□"
IDS_ARITY = {
    "⿰": 2,
    "⿱": 2,
    "⿲": 3,
    "⿳": 3,
    "⿴": 2,
    "⿵": 2,
    "⿶": 2,
    "⿷": 2,
    "⿸": 2,
    "⿹": 2,
    "⿺": 2,
    "⿻": 2,
}
CJKVI_COMMIT = "86b4d16159f0079437870408f0ca186e529015db"
CJKVI_IDS_URL = (
    "https://raw.githubusercontent.com/cjkvi/cjkvi-ids/"
    f"{CJKVI_COMMIT}/ids.txt"
)
VARIANT_SUFFIX = re.compile(r"\[[A-Z]+\]$")
LAYOUT_PROXIES = ("丯", "巛", "巿", "爿", "山", "木", "石", "禾", "火", "心")


@dataclass(frozen=True)
class IdsNode:
    value: str
    children: tuple["IdsNode", ...] = ()


@dataclass(frozen=True)
class OutlineContour:
    points: tuple[tuple[float, float], ...]

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def center(self) -> tuple[float, float]:
        left, top, right, bottom = self.bounds
        return (left + right) / 2, (top + bottom) / 2


@dataclass(frozen=True)
class SvgStroke:
    path: dict[str, str]
    bounds: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        left, top, right, bottom = self.bounds
        return (left + right) / 2, (top + bottom) / 2


class FlatteningContourPen(BasePen):
    """Flatten font curves into polygonal contours."""

    def __init__(self, glyph_set=None, steps: int = 12) -> None:
        super().__init__(glyph_set)
        self.steps = steps
        self.contours: list[OutlineContour] = []
        self._points: list[tuple[float, float]] = []

    def _moveTo(self, point) -> None:
        self._points = [tuple(point)]

    def _lineTo(self, point) -> None:
        self._points.append(tuple(point))

    def _qCurveToOne(self, control, point) -> None:
        start = self._points[-1]
        for index in range(1, self.steps + 1):
            t = index / self.steps
            inverse = 1 - t
            self._points.append(
                (
                    inverse * inverse * start[0]
                    + 2 * inverse * t * control[0]
                    + t * t * point[0],
                    inverse * inverse * start[1]
                    + 2 * inverse * t * control[1]
                    + t * t * point[1],
                )
            )

    def _curveToOne(self, first, second, point) -> None:
        start = self._points[-1]
        for index in range(1, self.steps + 1):
            t = index / self.steps
            inverse = 1 - t
            self._points.append(
                (
                    inverse**3 * start[0]
                    + 3 * inverse * inverse * t * first[0]
                    + 3 * inverse * t * t * second[0]
                    + t**3 * point[0],
                    inverse**3 * start[1]
                    + 3 * inverse * inverse * t * first[1]
                    + 3 * inverse * t * t * second[1]
                    + t**3 * point[1],
                )
            )

    def _closePath(self) -> None:
        if len(self._points) >= 3:
            self.contours.append(OutlineContour(tuple(self._points)))
        self._points = []

    def _endPath(self) -> None:
        self._closePath()


def parse_ids(value: str) -> IdsNode:
    def parse_at(index: int) -> tuple[IdsNode, int]:
        if index >= len(value):
            raise ValueError(f"Incomplete IDS expression {value!r}.")
        character = value[index]
        arity = IDS_ARITY.get(character)
        if arity is None:
            return IdsNode(character), index + 1
        children = []
        next_index = index + 1
        for _ in range(arity):
            child, next_index = parse_at(next_index)
            children.append(child)
        return IdsNode(character, tuple(children)), next_index

    node, end = parse_at(0)
    if end != len(value):
        raise ValueError(f"Unexpected trailing content in IDS expression {value!r}.")
    return node


def matches_pattern(pattern: IdsNode, candidate: IdsNode) -> bool:
    if pattern.value == LACUNA:
        return True
    return (
        pattern.value == candidate.value
        and len(pattern.children) == len(candidate.children)
        and all(
            matches_pattern(pattern_child, candidate_child)
            for pattern_child, candidate_child in zip(
                pattern.children, candidate.children
            )
        )
    )


def serialize_ids(node: IdsNode) -> str:
    return node.value + "".join(serialize_ids(child) for child in node.children)


def replace_lacuna(node: IdsNode, replacement: str) -> IdsNode:
    if node.value == LACUNA:
        return IdsNode(replacement)
    return IdsNode(
        node.value,
        tuple(replace_lacuna(child, replacement) for child in node.children),
    )


def lacuna_path(node: IdsNode) -> tuple[int, ...]:
    paths = []

    def visit(current: IdsNode, path: tuple[int, ...]) -> None:
        if current.value == LACUNA:
            paths.append(path)
        for index, child in enumerate(current.children):
            visit(child, (*path, index))

    visit(node, ())
    if len(paths) != 1:
        raise ValueError("Synthetic IDS support requires exactly one □ component.")
    return paths[0]


def load_cjkvi_ids(
    opener: Callable = urlopen,
    cache_directory: Path | None = None,
) -> str:
    if cache_directory is None:
        cache_root = Path(
            os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
        )
        cache_directory = cache_root / "ids-to-font"
    cache_path = cache_directory / f"cjkvi-ids-{CJKVI_COMMIT}.txt"
    if cache_path.is_file():
        return cache_path.read_text(encoding="utf-8")
    with opener(CJKVI_IDS_URL, timeout=30) as response:  # nosec B310: pinned URL
        content = response.read().decode("utf-8")
    cache_directory.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(content, encoding="utf-8")
    return content


def matching_characters(pattern: IdsNode, ids_data: str) -> list[str]:
    definitions = ids_definitions(ids_data)
    pattern = normalize_same_axis(pattern, definitions)
    matches = []
    for line in ids_data.splitlines():
        if not line or line.startswith(("#", ";")):
            continue
        fields = line.split("\t")
        if len(fields) < 3 or len(fields[1]) != 1:
            continue
        for raw_ids in fields[2:]:
            value = VARIANT_SUFFIX.sub("", raw_ids)
            try:
                candidate = normalize_same_axis(parse_ids(value), definitions)
            except ValueError:
                continue
            if matches_pattern(pattern, candidate):
                matches.append(fields[1])
                break
    return matches


@lru_cache(maxsize=2)
def ids_definitions(ids_data: str) -> dict[str, IdsNode]:
    definitions = {}
    for line in ids_data.splitlines():
        if not line or line.startswith(("#", ";")):
            continue
        fields = line.split("\t")
        if len(fields) < 3 or len(fields[1]) != 1:
            continue
        value = VARIANT_SUFFIX.sub("", fields[2])
        try:
            node = parse_ids(value)
        except ValueError:
            continue
        if node.children:
            definitions[fields[1]] = node
    return definitions


def normalize_same_axis(
    node: IdsNode,
    definitions: dict[str, IdsNode],
) -> IdsNode:
    if not node.children:
        return node
    axis = (
        "horizontal"
        if node.value in {"⿰", "⿲"}
        else "vertical"
        if node.value in {"⿱", "⿳"}
        else None
    )
    children = []
    for child in node.children:
        normalized = normalize_same_axis(child, definitions)
        if axis is not None and not normalized.children:
            definition = definitions.get(normalized.value)
            if definition is not None:
                definition_axis = (
                    "horizontal"
                    if definition.value in {"⿰", "⿲"}
                    else "vertical"
                    if definition.value in {"⿱", "⿳"}
                    else None
                )
                if definition_axis == axis:
                    normalized = normalize_same_axis(definition, definitions)
        children.append(normalized)
    current = IdsNode(node.value, tuple(children))
    if axis is None:
        return current
    flattened = []
    for child in current.children:
        child_axis = (
            "horizontal"
            if child.value in {"⿰", "⿲"}
            else "vertical"
            if child.value in {"⿱", "⿳"}
            else None
        )
        if child_axis == axis:
            flattened.extend(child.children)
        else:
            flattened.append(child)
    if len(flattened) == 2:
        operator = "⿰" if axis == "horizontal" else "⿱"
    elif len(flattened) == 3:
        operator = "⿲" if axis == "horizontal" else "⿳"
    else:
        return current
    return IdsNode(operator, tuple(flattened))


def normalize_contours(
    contours: list[OutlineContour],
    flip_vertical: bool,
) -> list[OutlineContour]:
    points = [
        (x, -y if flip_vertical else y)
        for contour in contours
        for x, y in contour.points
    ]
    left = min(point[0] for point in points)
    top = min(point[1] for point in points)
    right = max(point[0] for point in points)
    bottom = max(point[1] for point in points)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise ValueError("A reference outline has degenerate bounds.")
    scale = min(87 / width, 87 / height)
    x_offset = 4 + (87 - (right - left) * scale) / 2 - left * scale
    y_offset = 4 + (87 - (bottom - top) * scale) / 2 - top * scale
    return [
        OutlineContour(
            tuple(
                (
                    x * scale + x_offset,
                    (-y if flip_vertical else y) * scale + y_offset,
                )
                for x, y in contour.points
            )
        )
        for contour in contours
    ]


def contours_to_geometry(contours: list[OutlineContour]):
    records = [
        (
            make_valid(Polygon(contour.points)),
            sum(
                contour.points[index][0]
                * contour.points[(index + 1) % len(contour.points)][1]
                - contour.points[(index + 1) % len(contour.points)][0]
                * contour.points[index][1]
                for index in range(len(contour.points))
            ),
        )
        for contour in contours
        if len(contour.points) >= 3
    ]
    records = sorted(
        (
            (polygon, signed_area)
            for polygon, signed_area in records
            if not polygon.is_empty
        ),
        key=lambda record: record[0].area,
        reverse=True,
    )
    if not records:
        return GeometryCollection()
    outer_sign = 1 if records[0][1] >= 0 else -1
    geometry = GeometryCollection()
    for polygon, signed_area in records:
        sign = 1 if signed_area >= 0 else -1
        geometry = (
            geometry.difference(polygon)
            if sign != outer_sign
            else geometry.union(polygon)
        )
    return make_valid(geometry)


def font_geometry(font: TTFont, character: str):
    glyph_name = font.getBestCmap().get(ord(character))
    if glyph_name is None:
        raise ValueError(f"Reference font does not contain {character}.")
    glyph_set = font.getGlyphSet()
    pen = FlatteningContourPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    if not pen.contours:
        raise ValueError(f"Reference font glyph {character} has no outline.")
    return contours_to_geometry(
        normalize_contours(pen.contours, flip_vertical=True)
    )


def svg_geometry(
    resolution: EncodedResolution | SvgResolution,
) :
    contour_groups = []
    for path in resolution.paths:
        pen = FlatteningContourPen()
        transform = path.get("transform", "")
        if not transform:
            matrix = (1, 0, 0, 1, 0, 0)
        elif transform.startswith("scale(") and transform.endswith(")"):
            x_scale, y_scale = (
                float(value) for value in transform[6:-1].split(",")
            )
            matrix = (x_scale, 0, 0, y_scale, 0, 0)
        else:
            raise ValueError(f"Unsupported SVG transform: {transform}.")
        data = path["d"]
        data = data if data.rstrip().upper().endswith("Z") else data + " Z"
        parse_path(data, TransformPen(pen, matrix))
        if pen.contours:
            contour_groups.append(pen.contours)
    if not contour_groups:
        raise ValueError("Zi.tools returned no usable contours.")
    counts = [len(group) for group in contour_groups]
    normalized = normalize_contours(
        [
            contour
            for group in contour_groups
            for contour in group
        ],
        flip_vertical=False,
    )
    geometries = []
    start = 0
    for count in counts:
        geometries.append(
            contours_to_geometry(normalized[start : start + count])
        )
        start += count
    return make_valid(unary_union(geometries))


def svg_strokes(
    resolution: EncodedResolution | SvgResolution,
) -> list[SvgStroke]:
    strokes = []
    for path in resolution.paths:
        pen = BoundsPen(None)
        transform = path.get("transform", "")
        if not transform:
            matrix = (1, 0, 0, 1, 0, 0)
        elif transform.startswith("scale(") and transform.endswith(")"):
            x_scale, y_scale = (
                float(value) for value in transform[6:-1].split(",")
            )
            matrix = (x_scale, 0, 0, y_scale, 0, 0)
        else:
            raise ValueError(f"Unsupported SVG transform: {transform}.")
        data = path["d"]
        data = data if data.rstrip().upper().endswith("Z") else data + " Z"
        parse_path(data, TransformPen(pen, matrix))
        if pen.bounds is not None:
            strokes.append(SvgStroke(dict(path), pen.bounds))
    if not strokes:
        raise ValueError("Zi.tools returned no usable strokes.")
    return strokes


def cluster_items(items: list, axis: int, count: int) -> list[list]:
    values = [item.center[axis] for item in items]
    centers = [
        min(values) + (max(values) - min(values)) * index / (count - 1)
        for index in range(count)
    ]
    groups = []
    for _ in range(30):
        groups = [[] for _ in centers]
        for item in items:
            value = item.center[axis]
            target = min(
                range(len(centers)),
                key=lambda index: abs(value - centers[index]),
            )
            groups[target].append(item)
        if any(not group for group in groups):
            ordered = sorted(items, key=lambda item: item.center[axis])
            return [
                ordered[
                    round(len(ordered) * index / count) :
                    round(len(ordered) * (index + 1) / count)
                ]
                for index in range(count)
            ]
        new_centers = [
            statistics.mean(item.center[axis] for item in group)
            for group in groups
        ]
        if all(
            abs(old - new) < 0.001
            for old, new in zip(centers, new_centers)
        ):
            break
        centers = new_centers
    return [
        group
        for _, group in sorted(zip(centers, groups), key=lambda pair: pair[0])
    ]


def item_bounds(items: list) -> tuple[float, float, float, float]:
    return (
        min(item.bounds[0] for item in items),
        min(item.bounds[1] for item in items),
        max(item.bounds[2] for item in items),
        max(item.bounds[3] for item in items),
    )


def extract_surviving_strokes(
    strokes: list[SvgStroke],
    node: IdsNode,
    path: tuple[int, ...],
    region: tuple[float, float, float, float] = (0, 0, 95, 95),
) -> tuple[list[SvgStroke], tuple[float, float, float, float]]:
    if not path:
        return [], region
    if node.value not in {"⿰", "⿱", "⿲", "⿳"}:
        raise ValueError(
            f"Lacuna synthesis does not yet support operator {node.value}."
        )
    horizontal = node.value in {"⿰", "⿲"}
    groups = cluster_items(
        strokes,
        axis=0 if horizontal else 1,
        count=len(node.children),
    )
    boxes = [item_bounds(group) for group in groups]
    left, top, right, bottom = region
    boundaries = [
        (
            (first[2] + second[0]) / 2
            if horizontal
            else (first[3] + second[1]) / 2
        )
        for first, second in zip(boxes, boxes[1:])
    ]
    child_regions = []
    for index in range(len(groups)):
        if horizontal:
            child_regions.append(
                (
                    left if index == 0 else boundaries[index - 1],
                    top,
                    right if index == len(groups) - 1 else boundaries[index],
                    bottom,
                )
            )
        else:
            child_regions.append(
                (
                    left,
                    top if index == 0 else boundaries[index - 1],
                    right,
                    bottom if index == len(groups) - 1 else boundaries[index],
                )
            )
    target = path[0]
    retained = [
        stroke
        for index, group in enumerate(groups)
        if index != target
        for stroke in group
    ]
    nested, target_region = extract_surviving_strokes(
        groups[target],
        node.children[target],
        path[1:],
        child_regions[target],
    )
    return retained + nested, target_region


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


def cluster_geometry(
    geometry,
    axis: int,
    count: int,
) -> list:
    parts = polygon_parts(geometry)
    values = [
        (part.centroid.x, part.centroid.y)[axis]
        for part in parts
    ]
    centers = [
        min(values) + (max(values) - min(values)) * index / (count - 1)
        for index in range(count)
    ]
    groups: list[list[Polygon]] = []
    for _ in range(30):
        groups = [[] for _ in centers]
        for part in parts:
            value = (part.centroid.x, part.centroid.y)[axis]
            target = min(
                range(len(centers)),
                key=lambda index: abs(value - centers[index]),
            )
            groups[target].append(part)
        if any(not group for group in groups):
            ordered = sorted(
                parts,
                key=lambda part: (part.centroid.x, part.centroid.y)[axis],
            )
            return [
                make_valid(
                    unary_union(
                        ordered[
                            round(len(ordered) * index / count) :
                            round(len(ordered) * (index + 1) / count)
                        ]
                    )
                )
                for index in range(count)
            ]
        new_centers = [
            statistics.mean(
                (part.centroid.x, part.centroid.y)[axis]
                for part in group
            )
            for group in groups
        ]
        if all(
            abs(old - new) < 0.001
            for old, new in zip(centers, new_centers)
        ):
            break
        centers = new_centers
    return [
        make_valid(unary_union(group))
        for _, group in sorted(
            zip(centers, groups),
            key=lambda item: item[0],
        )
    ]


def extract_surviving_geometry(
    geometry,
    node: IdsNode,
    path: tuple[int, ...],
    region: tuple[float, float, float, float] = (0, 0, 95, 95),
) -> tuple[object, tuple[float, float, float, float]]:
    if not path:
        return GeometryCollection(), region
    if node.value not in {"⿰", "⿱", "⿲", "⿳"}:
        raise ValueError(
            f"Lacuna synthesis does not yet support operator {node.value}."
        )
    horizontal = node.value in {"⿰", "⿲"}
    groups = cluster_geometry(
        geometry,
        axis=0 if horizontal else 1,
        count=len(node.children),
    )
    group_boxes = [group.bounds for group in groups]
    left, top, right, bottom = region
    boundaries = []
    for first, second in zip(group_boxes, group_boxes[1:]):
        if horizontal:
            boundaries.append((first[2] + second[0]) / 2)
        else:
            boundaries.append((first[3] + second[1]) / 2)
    child_regions = []
    for index in range(len(groups)):
        if horizontal:
            child_regions.append(
                (
                    left if index == 0 else boundaries[index - 1],
                    top,
                    right if index == len(groups) - 1 else boundaries[index],
                    bottom,
                )
            )
        else:
            child_regions.append(
                (
                    left,
                    top if index == 0 else boundaries[index - 1],
                    right,
                    bottom if index == len(groups) - 1 else boundaries[index],
                )
            )
    target = path[0]
    retained = [
        group
        for index, group in enumerate(groups)
        if index != target
    ]
    nested_retained, target_region = extract_surviving_geometry(
        groups[target],
        node.children[target],
        path[1:],
        child_regions[target],
    )
    return make_valid(unary_union([*retained, nested_retained])), target_region


def inset_region(
    region: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    left, top, right, bottom = region
    inset = min(5, max(2.5, min(right - left, bottom - top) * 0.08))
    return left + inset, top + inset, right - inset, bottom - inset


def dotted_geometry(
    region: tuple[float, float, float, float],
):
    left, top, right, bottom = inset_region(region)
    width = right - left
    height = bottom - top
    step = max(3.8, min(width, height) / 7)
    radius = min(1.0, step * 0.22)
    horizontal_count = max(2, round(width / step))
    vertical_count = max(2, round(height / step))
    centers = []
    for index in range(horizontal_count + 1):
        x = left + width * index / horizontal_count
        centers.extend(((x, top), (x, bottom)))
    for index in range(1, vertical_count):
        y = top + height * index / vertical_count
        centers.extend(((left, y), (right, y)))
    circles = []
    for center_x, center_y in centers:
        circles.append(Point(center_x, center_y).buffer(radius, quad_segs=2))
    return unary_union(circles)


def geometry_to_path(geometry) -> str:
    commands = []
    for polygon in polygon_parts(geometry):
        polygon = orient(polygon, sign=1.0)
        for ring in (polygon.exterior, *polygon.interiors):
            points = list(ring.coords)[:-1]
            first, *remaining = points
            commands.append(f"M {first[0]:.4f},{first[1]:.4f}")
            commands.extend(f"L {x:.4f},{y:.4f}" for x, y in remaining)
            commands.append("Z")
    return " ".join(commands)


def synthesize_from_samples(
    ids: str,
    pattern: IdsNode,
    path: tuple[int, ...],
    layout_samples: list[
        tuple[
            str,
            object,
            tuple[float, float, float, float],
        ]
    ],
    layout_provider: str,
    ids_index: str,
    outline_samples: list[
        tuple[
            str,
            object,
            tuple[float, float, float, float],
        ]
    ] | None = None,
    outline_provider: str | None = None,
) -> SvgResolution:
    if len(layout_samples) < 2:
        raise ValueError(
            f"{layout_provider} supplied only "
            f"{len(layout_samples)} usable examples for {ids}."
        )
    median_region = tuple(
        statistics.median(sample[2][index] for sample in layout_samples)
        for index in range(4)
    )
    layout_example = min(
        layout_samples,
        key=lambda sample: sum(
            (sample[2][index] - median_region[index]) ** 2
            for index in range(4)
        ),
    )
    outline_samples = outline_samples or layout_samples
    if not outline_samples:
        raise ValueError(f"{outline_provider} supplied no outline examples for {ids}.")
    outline_example = min(
        outline_samples,
        key=lambda sample: sum(
            (sample[2][index] - median_region[index]) ** 2
            for index in range(4)
        ),
    )
    character, surviving, _ = outline_example
    if isinstance(surviving, list):
        output_paths = tuple(stroke.path for stroke in surviving) + (
            {"d": geometry_to_path(dotted_geometry(median_region))},
        )
    else:
        output_paths = (
            {
                "d": geometry_to_path(
                    make_valid(
                        unary_union(
                            [surviving, dotted_geometry(median_region)]
                        )
                    )
                )
            },
        )
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=output_paths,
        metadata={
            "synthetic_lacuna": True,
            "layout_provider": layout_provider,
            "layout_example": layout_example[0],
            "layout_sample_size": len(layout_samples),
            "outline_provider": outline_provider or layout_provider,
            "outline_example": character,
            "ids_index": ids_index,
        },
    )


def collect_zi_tools_samples(
    pattern: IdsNode,
    path: tuple[int, ...],
    ids_data: str,
    encoded_resolver: Callable[[str], EncodedResolution],
    ids_resolver: Callable[[str], SvgResolution],
    sample_size: int,
    max_attempts: int,
    delay: float,
    sleeper: Callable[[float], None],
) -> list[tuple[str, object, tuple[float, float, float, float]]]:
    candidates = sorted(
        matching_characters(pattern, ids_data),
        key=ord,
        reverse=True,
    )
    samples = []
    attempts = 0

    def attempt(callable_, value):
        nonlocal attempts
        if attempts >= max_attempts:
            raise StopIteration
        if attempts and delay:
            sleeper(delay)
        attempts += 1
        return callable_(value)

    for character in candidates:
        try:
            strokes = svg_strokes(attempt(encoded_resolver, character))
            surviving, region = extract_surviving_strokes(
                strokes,
                pattern,
                path,
            )
        except StopIteration:
            break
        except (OSError, ValueError):
            continue
        samples.append((character, surviving, region))
        if len(samples) == sample_size:
            return samples
    for proxy in LAYOUT_PROXIES:
        template = serialize_ids(replace_lacuna(pattern, proxy))
        try:
            strokes = svg_strokes(attempt(ids_resolver, template))
            surviving, region = extract_surviving_strokes(
                strokes,
                pattern,
                path,
            )
        except StopIteration:
            break
        except (OSError, ValueError):
            continue
        samples.append((template, surviving, region))
        if len(samples) == sample_size:
            break
    return samples


def synthesize_from_reference(
    ids: str,
    reference_font: Path,
    ids_data: str,
    encoded_resolver: Callable[[str], EncodedResolution],
    ids_resolver: Callable[[str], SvgResolution],
    sample_size: int = 8,
    max_attempts: int = 24,
    delay: float = 10,
    sleeper: Callable[[float], None] = time.sleep,
) -> SvgResolution:
    pattern = normalize_same_axis(parse_ids(ids), ids_definitions(ids_data))
    path = lacuna_path(pattern)
    with TTFont(reference_font) as font:
        cmap = font.getBestCmap()
        candidates = [
            character
            for character in matching_characters(pattern, ids_data)
            if ord(character) in cmap
        ][:sample_size]
        samples = []
        for character in candidates:
            geometry = font_geometry(font, character)
            surviving, region = extract_surviving_geometry(
                geometry,
                pattern,
                path,
            )
            samples.append((character, surviving, region))
    outline_samples = collect_zi_tools_samples(
        pattern,
        path,
        ids_data,
        encoded_resolver,
        ids_resolver,
        sample_size,
        max_attempts,
        delay,
        sleeper,
    )
    return synthesize_from_samples(
        ids,
        pattern,
        path,
        samples,
        reference_font.name,
        CJKVI_IDS_URL,
        outline_samples,
        "Zi.tools",
    )


def synthesize_from_zi_tools(
    ids: str,
    ids_data: str,
    encoded_resolver: Callable[[str], EncodedResolution],
    ids_resolver: Callable[[str], SvgResolution],
    sample_size: int = 8,
    max_attempts: int = 24,
    delay: float = 10,
    sleeper: Callable[[float], None] = time.sleep,
) -> SvgResolution:
    pattern = normalize_same_axis(parse_ids(ids), ids_definitions(ids_data))
    path = lacuna_path(pattern)
    samples = collect_zi_tools_samples(
        pattern,
        path,
        ids_data,
        encoded_resolver,
        ids_resolver,
        sample_size,
        max_attempts,
        delay,
        sleeper,
    )
    return synthesize_from_samples(
        ids,
        pattern,
        path,
        samples,
        "Zi.tools",
        CJKVI_IDS_URL,
    )
