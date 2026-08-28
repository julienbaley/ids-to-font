"""Load curated SVG outline replacements for exact IDS expressions."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from importlib.resources import files
from pathlib import Path

from .zi_tools import SvgResolution


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
POINTS = re.compile(rf"({NUMBER})[\s,]+({NUMBER})")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def polygon_path(points: str, source: str) -> str:
    coordinates = POINTS.findall(points)
    if len(coordinates) < 3:
        raise ValueError(f"Custom outline {source} contains an invalid polygon.")
    first, *remaining = coordinates
    return (
        f"M {first[0]},{first[1]} "
        + " ".join(f"L {x},{y}" for x, y in remaining)
        + " Z"
    )


def load_outline_text(
    ids: str,
    content: str,
    source: str,
) -> SvgResolution:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError(f"Could not read custom outline {source}: {error}") from error
    paths = []
    for element in root.iter():
        if element.get("transform"):
            raise ValueError(
                f"Custom outline {source} contains an unsupported transform."
            )
        tag = local_name(element.tag)
        if tag == "path":
            data = element.get("d", "").strip()
            if not data:
                raise ValueError(f"Custom outline {source} contains an empty path.")
        elif tag == "polygon":
            data = polygon_path(element.get("points", ""), source)
        else:
            continue
        path = {"d": data, "transform": "scale(0.462,0.462)"}
        paths.append(path)
    if not paths:
        raise ValueError(f"Custom outline {source} contains no paths or polygons.")
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=tuple(paths),
        metadata={
            "outline_provider": "custom",
            "outline_source": source,
        },
    )


def load_outline_file(ids: str, source: Path) -> SvgResolution:
    try:
        content = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"Could not read custom outline {source}: {error}") from error
    resolution = load_outline_text(ids, content, str(source))
    return SvgResolution(
        requested_ids=resolution.requested_ids,
        resolved_ids=resolution.resolved_ids,
        view_box=resolution.view_box,
        paths=resolution.paths,
        metadata={
            "outline_provider": "custom",
            "outline_source": source.name,
        },
    )


def resolve_manual_outline(ids: str) -> SvgResolution | None:
    directory = files("ids_to_font").joinpath("manual_outlines")
    filename = f"{ids}.svg"
    source = directory.joinpath(filename)
    if not source.is_file():
        return None
    with source.open("r", encoding="utf-8") as handle:
        content = handle.read()
    resolution = load_outline_text(ids, content, filename)
    return SvgResolution(
        requested_ids=resolution.requested_ids,
        resolved_ids=resolution.resolved_ids,
        view_box=resolution.view_box,
        paths=resolution.paths,
        metadata={
            "outline_provider": "manual",
            "outline_source": filename,
        },
    )
