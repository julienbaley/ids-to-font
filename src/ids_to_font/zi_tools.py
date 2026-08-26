"""Resolve IDS expressions through the Zi.tools API."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote
from urllib.request import urlopen

from .input import normalize_ids


PROVIDER = "https://zi.tools/"
LOOKUP_URL = "https://zi.tools/api/ids/lookupids/"


@dataclass(frozen=True)
class SvgResolution:
    requested_ids: str
    resolved_ids: str
    view_box: str
    paths: tuple[dict[str, str], ...]
    metadata: dict[str, object] = field(default_factory=dict)
    kage: tuple[str, ...] = ()


@dataclass(frozen=True)
class EncodedResolution:
    character: str
    decompositions: tuple[str, ...]
    view_box: str
    paths: tuple[dict[str, str], ...]

    @property
    def requested_ids(self) -> str:
        return self.character


def lookup(value: str, opener: Callable) -> tuple[dict, dict]:
    url = f"{LOOKUP_URL}{quote(value, safe='')}?replace_token"
    with opener(url, timeout=30) as response:  # nosec B310: fixed HTTPS endpoint
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get(value, payload)
    if not isinstance(result, dict):
        raise ValueError(f"Zi.tools returned no result for {value}.")
    return payload, result


def fetch_resolution(
    ids: str,
    opener: Callable = urlopen,
) -> SvgResolution:
    payload, result = lookup(ids, opener)
    unicode_matches = result.get("lv1", {}).get("match_u_list", [])
    if len(unicode_matches) == 1:
        raise ValueError(
            f"{ids} resolves directly to Unicode {unicode_matches[0]}; "
            "use Unicode supplement mode for this character."
        )
    paths = [path for path in result.get("svg", "").split("|") if path]
    resolved_ids = ids
    if not paths:
        paths = [
            path
            for path in payload.get("font", {}).get(ids, "").split("|")
            if path
        ]
    if not paths:
        candidates = list(
            dict.fromkeys(
                candidate
                for candidate in result.get("lv1", {}).get(
                    "external_match_list", []
                )
                if candidate != ids
            )
        )
        if len(candidates) == 1:
            resolved_ids = candidates[0]
            paths = [
                path
                for path in payload.get("font", {}).get(resolved_ids, "").split("|")
                if path
            ]
    if not paths:
        raise ValueError(f"Zi.tools returned no SVG outline for {ids}.")
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=resolved_ids,
        view_box="0 0 95 95",
        paths=tuple(
            {"d": path, "transform": "scale(0.462,0.462)"}
            for path in paths
        ),
        kage=tuple(
            stroke
            for stroke in result.get("kage", "").split("$")
            if stroke
        ),
    )


def fetch_encoded_resolution(
    character: str,
    opener: Callable = urlopen,
) -> EncodedResolution:
    payload, result = lookup(character, opener)
    paths = [
        path
        for path in payload.get("font", {}).get(character, "").split("|")
        if path
    ]
    if not paths:
        paths = [path for path in result.get("svg", "").split("|") if path]
    if not paths:
        raise ValueError(
            f"Zi.tools returned no SVG outline for {character} "
            f"(U+{ord(character):04X})."
        )
    decompositions = []
    for value in result.get("lv1", {}).get("ids_list", []):
        if not isinstance(value, str):
            continue
        try:
            ids = normalize_ids(value)
        except ValueError:
            continue
        if ids not in decompositions:
            decompositions.append(ids)
    return EncodedResolution(
        character=character,
        decompositions=tuple(decompositions),
        view_box="0 0 95 95",
        paths=tuple(
            {"d": path, "transform": "scale(0.462,0.462)"}
            for path in paths
        ),
    )
