"""Synthesize IDS outlines containing a dotted lacuna component."""

from __future__ import annotations

import os
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont

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
LAYOUT_PROXIES = ("丯", "巛", "巿", "爿", "𡵂")
PROXY_STROKE_COUNTS = {
    "丯": 4,
    "巛": 6,
    "巿": 5,
    "爿": 6,
    "𡵂": 9,
}


@dataclass(frozen=True)
class IdsNode:
    value: str
    children: tuple["IdsNode", ...] = ()


@dataclass(frozen=True)
class SvgStroke:
    path: dict[str, str] | None
    bounds: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        left, top, right, bottom = self.bounds
        return (left + right) / 2, (top + bottom) / 2


@dataclass(frozen=True)
class ReferenceContour:
    path: str
    bounds: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        left, top, right, bottom = self.bounds
        return (left + right) / 2, (top + bottom) / 2


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


def normalization_transform(
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise ValueError("A reference outline has degenerate bounds.")
    scale = min(87 / width, 87 / height)
    x_offset = 4 + (87 - (right - left) * scale) / 2 - left * scale
    y_offset = 4 + (87 - (bottom - top) * scale) / 2 - top * scale
    return scale, x_offset, y_offset


def font_contours(font: TTFont, character: str) -> list[ReferenceContour]:
    glyph_name = font.getBestCmap().get(ord(character))
    if glyph_name is None:
        raise ValueError(f"Reference font does not contain {character}.")
    glyph_set = font.getGlyphSet()
    recording = RecordingPen()
    glyph_set[glyph_name].draw(recording)
    contour_records = []
    current = []
    for record in recording.value:
        current.append(record)
        if record[0] in {"closePath", "endPath"}:
            contour_records.append(current)
            current = []
    raw_contours = []
    for records in contour_records:
        contour = RecordingPen()
        contour.value = records
        bounds_pen = BoundsPen(glyph_set)
        contour.replay(bounds_pen)
        if bounds_pen.bounds is not None:
            raw_contours.append((contour, bounds_pen.bounds))
    if not raw_contours:
        raise ValueError(f"Reference font glyph {character} has no outline.")
    full_bounds = (
        min(bounds[0] for _, bounds in raw_contours),
        -max(bounds[3] for _, bounds in raw_contours),
        max(bounds[2] for _, bounds in raw_contours),
        -min(bounds[1] for _, bounds in raw_contours),
    )
    scale, x_offset, y_offset = normalization_transform(full_bounds)
    contours = []
    for contour, (left, bottom, right, top) in raw_contours:
        path_pen = SVGPathPen(glyph_set)
        contour.replay(
            TransformPen(
                path_pen,
                (scale, 0, 0, -scale, x_offset, y_offset),
            )
        )
        contours.append(
            ReferenceContour(
                path_pen.getCommands(),
                (
                    left * scale + x_offset,
                    -top * scale + y_offset,
                    right * scale + x_offset,
                    -bottom * scale + y_offset,
                ),
            )
        )
    return contours


def region_for_path(
    node: IdsNode,
    path: tuple[int, ...],
    region: tuple[float, float, float, float] = (0, 0, 95, 95),
) -> tuple[float, float, float, float]:
    if not path:
        return region
    if node.value not in {"⿰", "⿱", "⿲", "⿳"}:
        raise ValueError(f"Cannot allocate a structural region under {node.value}.")
    index = path[0]
    count = len(node.children)
    left, top, right, bottom = region
    if node.value in {"⿰", "⿲"}:
        width = (right - left) / count
        child_region = (
            left + index * width,
            top,
            left + (index + 1) * width,
            bottom,
        )
    else:
        height = (bottom - top) / count
        child_region = (
            left,
            top + index * height,
            right,
            top + (index + 1) * height,
        )
    return region_for_path(node.children[index], path[1:], child_region)


def transform_reference_contours(
    contours: list[ReferenceContour],
    region: tuple[float, float, float, float],
) -> list[ReferenceContour]:
    left, top, right, bottom = region
    x_scale = (right - left) / 95
    y_scale = (bottom - top) / 95
    transformed = []
    for contour in contours:
        path_pen = SVGPathPen(None)
        parse_path(
            contour.path,
            TransformPen(
                path_pen,
                (x_scale, 0, 0, y_scale, left, top),
            ),
        )
        contour_left, contour_top, contour_right, contour_bottom = contour.bounds
        transformed.append(
            ReferenceContour(
                path_pen.getCommands(),
                (
                    contour_left * x_scale + left,
                    contour_top * y_scale + top,
                    contour_right * x_scale + left,
                    contour_bottom * y_scale + top,
                ),
            )
        )
    return transformed


def synthesize_structural_reference(
    ids: str,
    pattern: IdsNode,
    normalized: IdsNode,
    reference_font: Path,
    font: TTFont,
) -> SvgResolution:
    path = lacuna_path(pattern)
    if (
        len(path) != 1
        or pattern.value not in {"⿰", "⿱"}
        or len(pattern.children) != 2
    ):
        raise ValueError(
            f"{reference_font.name} supplied no usable examples for {ids}."
        )
    lacuna_index = path[0]
    known = pattern.children[1 - lacuna_index]
    if known.children or known.value == LACUNA:
        raise ValueError(
            f"{reference_font.name} supplied no usable examples for {ids}."
        )
    normalized_lacuna = region_for_path(normalized, lacuna_path(normalized))
    left, top, right, bottom = normalized_lacuna
    if pattern.value == "⿱":
        known_region = (
            0,
            bottom if lacuna_index == 0 else 0,
            95,
            95 if lacuna_index == 0 else top,
        )
    else:
        known_region = (
            right if lacuna_index == 0 else 0,
            0,
            95 if lacuna_index == 0 else left,
            95,
        )
    contours = transform_reference_contours(
        font_contours(font, known.value),
        known_region,
    )
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=(
            {"d": " ".join(contour.path for contour in contours)},
            {"d": dotted_path(normalized_lacuna)},
        ),
        metadata={
            "synthetic_lacuna": True,
            "structural_fallback": True,
            "layout_provider": "IDS structure",
            "layout_example": serialize_ids(normalized),
            "layout_sample_size": 0,
            "outline_provider": reference_font.name,
            "outline_example": known.value,
            "ids_index": CJKVI_IDS_URL,
        },
    )


def retain_enclosed_contours(
    contours: list[ReferenceContour],
    retained: list[ReferenceContour],
) -> list[ReferenceContour]:
    retained_ids = {id(contour) for contour in retained}
    for contour in contours:
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
        for contour in contours
        if id(contour) in retained_ids
    ]


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


def kage_strokes(resolution: SvgResolution) -> list[SvgStroke]:
    if not resolution.kage:
        raise ValueError("Zi.tools returned no KAGE stroke program.")
    transform = resolution.paths[0].get("transform", "")
    if not transform.startswith("scale(") or not transform.endswith(")"):
        raise ValueError("Zi.tools returned an unsupported KAGE transform.")
    x_scale, y_scale = (
        float(value) for value in transform[6:-1].split(",")
    )
    strokes = []
    for index, stroke in enumerate(resolution.kage):
        fields = stroke.split(":")
        coordinates = [float(value) for value in fields[3:]]
        if len(coordinates) < 4 or len(coordinates) % 2:
            raise ValueError("Zi.tools returned an invalid KAGE stroke.")
        xs = coordinates[0::2]
        ys = coordinates[1::2]
        strokes.append(
            SvgStroke(
                {"index": str(index)},
                (
                    min(xs) * x_scale,
                    min(ys) * y_scale,
                    max(xs) * x_scale,
                    max(ys) * y_scale,
                ),
            )
        )
    return strokes


def bounds_distance(first, second) -> float:
    first_center = (
        (first[0] + first[2]) / 2,
        (first[1] + first[3]) / 2,
    )
    second_center = (
        (second[0] + second[2]) / 2,
        (second[1] + second[3]) / 2,
    )
    first_size = (first[2] - first[0], first[3] - first[1])
    second_size = (second[2] - second[0], second[3] - second[1])
    return sum(
        (left - right) ** 2
        for left, right in zip(first_center, second_center)
    ) + 0.15 * sum(
        (left - right) ** 2
        for left, right in zip(first_size, second_size)
    )


def segment_kage_paths(
    resolution: SvgResolution,
) -> tuple[list[SvgStroke], list[list[SvgStroke]]]:
    semantic = kage_strokes(resolution)
    paths = svg_strokes(resolution)
    if len(paths) < len(semantic):
        raise ValueError("Zi.tools returned fewer paths than KAGE strokes.")
    stroke_count = len(semantic)
    path_count = len(paths)
    infinity = float("inf")
    costs = [
        [infinity] * (path_count + 1)
        for _ in range(stroke_count + 1)
    ]
    previous = [
        [None] * (path_count + 1)
        for _ in range(stroke_count + 1)
    ]
    costs[0][0] = 0.0
    for stroke_index in range(stroke_count):
        for start in range(path_count):
            if costs[stroke_index][start] == infinity:
                continue
            last_end = path_count - (stroke_count - stroke_index - 1)
            for end in range(start + 1, last_end + 1):
                cost = costs[stroke_index][start] + bounds_distance(
                    semantic[stroke_index].bounds,
                    item_bounds(paths[start:end]),
                )
                if cost < costs[stroke_index + 1][end]:
                    costs[stroke_index + 1][end] = cost
                    previous[stroke_index + 1][end] = start
    boundaries = []
    end = path_count
    for stroke_index in range(stroke_count, 0, -1):
        boundaries.append(end)
        start = previous[stroke_index][end]
        if start is None:
            raise ValueError("Could not align KAGE strokes with SVG paths.")
        end = start
    boundaries.reverse()
    starts = [0, *boundaries[:-1]]
    return semantic, [
        paths[start:end]
        for start, end in zip(starts, boundaries)
    ]


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


def extract_proxy_strokes(
    resolution: SvgResolution,
    node: IdsNode,
    path: tuple[int, ...],
    proxy: str,
) -> tuple[list[SvgStroke], tuple[float, float, float, float]]:
    semantic, path_groups = segment_kage_paths(resolution)
    clustered, region = extract_surviving_strokes(semantic, node, path)
    count = PROXY_STROKE_COUNTS[proxy]
    if len(path) == 1 and path[0] == 0:
        retained_indices = range(count, len(semantic))
    elif len(path) == 1 and path[0] == len(node.children) - 1:
        retained_indices = range(len(semantic) - count)
    else:
        retained_indices = sorted(
            int(stroke.path["index"])
            for stroke in clustered
            if stroke.path is not None
        )
    return (
        [
            stroke
            for index in retained_indices
            for stroke in path_groups[index]
        ],
        region,
    )


def align_proxy_resolutions(
    samples: list[tuple[str, str, SvgResolution]],
    node: IdsNode,
    path: tuple[int, ...],
) -> list[
    tuple[
        str,
        list[SvgStroke],
        tuple[float, float, float, float],
    ]
]:
    if not samples:
        return []
    records = []
    for name, proxy, resolution in samples:
        semantic, path_groups = segment_kage_paths(resolution)
        count = PROXY_STROKE_COUNTS[proxy]
        records.append(
            (
                name,
                proxy,
                semantic,
                path_groups,
                len(semantic) - count,
            )
        )
    retained_count, agreement = Counter(
        record[4] for record in records
    ).most_common(1)[0]
    if agreement > 1:
        records = [
            record
            for record in records
            if record[4] == retained_count
        ]
    elif len(records) == 1:
        name, proxy, _, _, _ = records[0]
        surviving, region = extract_proxy_strokes(
            samples[0][2],
            node,
            path,
            proxy,
        )
        return [(name, surviving, region)]
    elif len(path) == 1 and path[0] in {
        0,
        len(node.children) - 1,
    }:
        edge_scores = []
        for count in range(1, min(len(record[2]) for record in records)):
            retained = [
                (
                    record[2][-count:]
                    if path[0] == 0
                    else record[2][:count]
                )
                for record in records
            ]
            edge_scores.append(
                sum(
                    statistics.pvariance(
                        sample[index].bounds[dimension]
                        for sample in retained
                    )
                    for index in range(count)
                    for dimension in range(4)
                )
                / count
            )
        retained_count = max(
            range(1, len(edge_scores)),
            key=lambda index: edge_scores[index] / max(
                edge_scores[index - 1],
                0.001,
            ),
        )
    else:
        raise ValueError("Zi.tools proxy samples disagree on stroke count.")
    if len(path) == 1 and path[0] == 0:
        offset = 0
    elif len(path) == 1 and path[0] == len(node.children) - 1:
        offset = retained_count
    else:
        offset = min(
            range(retained_count + 1),
            key=lambda candidate: sum(
                statistics.pvariance(
                    (
                        (
                            record[2][index]
                            if index < candidate
                            else record[2][
                                index
                                + len(record[2])
                                - retained_count
                            ]
                        ).bounds[dimension]
                        for record in records
                    )
                )
                for index in range(retained_count)
                for dimension in range(4)
            ),
        )
    aligned = []
    for name, proxy, semantic, path_groups, _ in records:
        count = len(semantic) - retained_count
        _, region = extract_surviving_strokes(semantic, node, path)
        retained_indices = [
            *range(offset),
            *range(offset + count, len(semantic)),
        ]
        aligned.append(
            (
                name,
                [
                    stroke
                    for index in retained_indices
                    for stroke in path_groups[index]
                ],
                region,
            )
        )
    return aligned


def inset_region(
    region: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    left, top, right, bottom = region
    inset = min(5, max(2.5, min(right - left, bottom - top) * 0.08))
    return left + inset, top + inset, right - inset, bottom - inset


def dotted_path(region: tuple[float, float, float, float]) -> str:
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
    commands = []
    for center_x, center_y in centers:
        diagonal = radius * 0.70710678
        points = (
            (center_x - radius, center_y),
            (center_x - diagonal, center_y - diagonal),
            (center_x, center_y - radius),
            (center_x + diagonal, center_y - diagonal),
            (center_x + radius, center_y),
            (center_x + diagonal, center_y + diagonal),
            (center_x, center_y + radius),
            (center_x - diagonal, center_y + diagonal),
        )
        commands.append(
            f"M {points[0][0]:.4f},{points[0][1]:.4f} "
            + " ".join(
                f"L {x:.4f},{y:.4f}"
                for x, y in points[1:]
            )
            + " Z"
        )
    return " ".join(commands)


def synthesize_from_samples(
    ids: str,
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
    if not layout_samples:
        raise ValueError(
            f"{layout_provider} supplied no usable examples for {ids}."
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
    if surviving and isinstance(surviving[0], ReferenceContour):
        output_paths = (
            {
                "d": " ".join(
                    contour.path
                    for contour in surviving
                )
            },
            {"d": dotted_path(median_region)},
        )
    else:
        output_paths = tuple(
            stroke.path
            for stroke in surviving
            if stroke.path is not None
        ) + ({"d": dotted_path(median_region)},)
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
    ids_resolver: Callable[[str], SvgResolution],
    sample_size: int,
    max_attempts: int,
    delay: float,
    sleeper: Callable[[float], None],
) -> list[tuple[str, object, tuple[float, float, float, float]]]:
    resolutions = []
    attempts = 0

    def attempt(callable_, value):
        nonlocal attempts
        if attempts >= max_attempts:
            raise StopIteration
        if attempts and delay:
            sleeper(delay)
        attempts += 1
        return callable_(value)

    for proxy in LAYOUT_PROXIES:
        template = serialize_ids(replace_lacuna(pattern, proxy))
        try:
            resolution = attempt(ids_resolver, template)
        except StopIteration:
            break
        except (OSError, ValueError):
            continue
        resolutions.append((template, proxy, resolution))
        if len(resolutions) == sample_size:
            break
    return align_proxy_resolutions(resolutions, pattern, path)


def synthesize_from_reference(
    ids: str,
    reference_font: Path,
    ids_data: str,
    sample_size: int = 8,
) -> SvgResolution:
    original_pattern = parse_ids(ids)
    pattern = normalize_same_axis(original_pattern, ids_definitions(ids_data))
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
            contours = font_contours(font, character)
            surviving, region = extract_surviving_strokes(
                contours,
                pattern,
                path,
            )
            surviving = retain_enclosed_contours(
                contours,
                surviving,
            )
            samples.append((character, surviving, region))
        if not samples:
            return synthesize_structural_reference(
                ids,
                original_pattern,
                pattern,
                reference_font,
                font,
            )
    return synthesize_from_samples(
        ids,
        samples,
        reference_font.name,
        CJKVI_IDS_URL,
    )


def synthesize_from_zi_tools(
    ids: str,
    ids_data: str,
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
        ids_resolver,
        sample_size,
        max_attempts,
        delay,
        sleeper,
    )
    return synthesize_from_samples(
        ids,
        samples,
        "Zi.tools",
        CJKVI_IDS_URL,
    )
