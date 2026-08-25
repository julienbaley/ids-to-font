"""Resolve IDS expressions through the Zi.tools API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote
from urllib.request import urlopen


PROVIDER = "https://zi.tools/"
LOOKUP_URL = "https://zi.tools/api/ids/lookupids/"


@dataclass(frozen=True)
class SvgResolution:
    requested_ids: str
    resolved_ids: str
    view_box: str
    paths: tuple[dict[str, str], ...]


def fetch_resolution(
    ids: str,
    opener: Callable = urlopen,
) -> SvgResolution:
    url = f"{LOOKUP_URL}{quote(ids, safe='')}?replace_token"
    with opener(url, timeout=30) as response:  # nosec B310: fixed HTTPS endpoint
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get(ids, payload)
    if not isinstance(result, dict):
        raise ValueError(f"Zi.tools returned no result for {ids}.")
    unicode_matches = result.get("lv1", {}).get("match_u_list", [])
    if len(unicode_matches) == 1:
        raise ValueError(
            f"{ids} resolves directly to Unicode {unicode_matches[0]}; "
            "it does not require a PUA font glyph."
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
    )
