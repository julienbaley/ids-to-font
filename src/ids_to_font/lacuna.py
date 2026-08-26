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

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
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
LAYOUT_PROXIES = ("丯", "巛", "巿", "爿", "山", "木", "石", "禾", "火", "心")


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


def font_strokes(font: TTFont, character: str) -> list[SvgStroke]:
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
    raw_bounds = []
    for records in contour_records:
        contour = RecordingPen()
        contour.value = records
        bounds_pen = BoundsPen(glyph_set)
        contour.replay(bounds_pen)
        if bounds_pen.bounds is not None:
            raw_bounds.append(bounds_pen.bounds)
    if not raw_bounds:
        raise ValueError(f"Reference font glyph {character} has no outline.")
    full_bounds = (
        min(bounds[0] for bounds in raw_bounds),
        -max(bounds[3] for bounds in raw_bounds),
        max(bounds[2] for bounds in raw_bounds),
        -min(bounds[1] for bounds in raw_bounds),
    )
    scale, x_offset, y_offset = normalization_transform(full_bounds)
    return [
        SvgStroke(
            None,
            (
                left * scale + x_offset,
                -top * scale + y_offset,
                right * scale + x_offset,
                -bottom * scale + y_offset,
            ),
        )
        for left, bottom, right, top in raw_bounds
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
        commands.append(
            f"M {center_x - radius:.4f},{center_y:.4f} "
            f"A {radius:.4f},{radius:.4f} 0 1 0 "
            f"{center_x + radius:.4f},{center_y:.4f} "
            f"A {radius:.4f},{radius:.4f} 0 1 0 "
            f"{center_x - radius:.4f},{center_y:.4f} Z"
        )
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
            surviving, region = extract_surviving_strokes(
                font_strokes(font, character),
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
