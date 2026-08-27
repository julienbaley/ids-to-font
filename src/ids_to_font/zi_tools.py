"""Resolve IDS expressions through the Zi.tools API."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from urllib.request import urlopen

from .input import normalize_ids


PROVIDER = "https://zi.tools/"
LOOKUP_URL = "https://zi.tools/api/ids/lookupids/"
CACHE_SCHEMA_VERSION = "1"


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
        try:
            payload = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Zi.tools returned malformed JSON for {value}.") from error
    return validate_lookup_payload(value, payload)


def validate_lookup_payload(value: str, payload: object) -> tuple[dict, dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"Zi.tools returned malformed JSON for {value}.")
    result = payload.get(value, payload)
    if not isinstance(result, dict):
        raise ValueError(f"Zi.tools returned no result for {value}.")
    return payload, result


def default_cache_directory() -> Path:
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "ids-to-font" / "zi-tools"


@dataclass
class ZiToolsClient:
    cache_directory: Path | None = None
    refresh_cache: bool = False
    delay: float = 10
    opener: Callable = urlopen
    sleeper: Callable[[float], None] = time.sleep
    _network_requests: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.delay < 0:
            raise ValueError("Request delay must not be negative.")
        if self.cache_directory is None:
            self.cache_directory = default_cache_directory()

    def cache_path(self, value: str) -> Path:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return self.cache_directory / f"{digest}.json"

    def read_cache(self, value: str) -> tuple[dict, dict] | None:
        path = self.cache_path(value)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Corrupt Zi.tools cache entry {path}: {error}") from error
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != CACHE_SCHEMA_VERSION
            or record.get("lookup_value") != value
            or record.get("endpoint") != LOOKUP_URL
            or not isinstance(record.get("retrieved_at"), str)
            or "payload" not in record
        ):
            raise ValueError(f"Corrupt Zi.tools cache entry {path}: invalid metadata.")
        try:
            return validate_lookup_payload(value, record["payload"])
        except ValueError as error:
            raise ValueError(f"Corrupt Zi.tools cache entry {path}: {error}") from error

    def write_cache(self, value: str, payload: dict) -> None:
        path = self.cache_path(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "lookup_value": value,
            "endpoint": LOOKUP_URL,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
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
                json.dump(record, temporary, ensure_ascii=False, separators=(",", ":"))
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def lookup(self, value: str) -> tuple[dict, dict]:
        if not self.refresh_cache:
            cached = self.read_cache(value)
            if cached is not None:
                return cached
        if self._network_requests and self.delay:
            self.sleeper(self.delay)
        try:
            payload, result = lookup(value, self.opener)
        finally:
            self._network_requests += 1
        self.write_cache(value, payload)
        return payload, result

    def fetch_resolution(self, ids: str) -> SvgResolution:
        return resolution_from_lookup(ids, *self.lookup(ids))

    def fetch_encoded_resolution(self, character: str) -> EncodedResolution:
        return encoded_resolution_from_lookup(character, *self.lookup(character))


def fetch_resolution(
    ids: str,
    opener: Callable = urlopen,
) -> SvgResolution:
    return resolution_from_lookup(ids, *lookup(ids, opener))


def resolution_from_lookup(ids: str, payload: dict, result: dict) -> SvgResolution:
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
    return encoded_resolution_from_lookup(character, *lookup(character, opener))


def encoded_resolution_from_lookup(
    character: str,
    payload: dict,
    result: dict,
) -> EncodedResolution:
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
