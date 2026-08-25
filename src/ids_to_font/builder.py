"""Resolve IDS expressions and write the paired font and mapping artifacts."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .font import build_font
from .mapping import (
    assign_pua,
    load_previous_assignments,
    serialize_assignments,
)
from .zi_tools import PROVIDER, SvgResolution, fetch_resolution


@dataclass(frozen=True)
class BuildResult:
    font_path: Path
    mapping_path: Path
    style_path: Path | None
    glyph_count: int
    reserved_assignment_count: int


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_latex_package(
    path: Path,
    package_name: str,
    font_path: Path,
    font_date: str,
    active_ids: list[str],
    assignments: dict[str, int],
) -> None:
    mappings = "\n".join(
        (
            r"\prop_gput:Nnn \g__ids_to_font_mapping_prop"
            f" {{ {ids} }} {{ \\char_generate:nn {{ \"{assignments[ids]:X} }} {{ 12 }} }}"
        )
        for ids in active_ids
    )
    path.write_text(
        rf"""\NeedsTeXFormat{{LaTeX2e}}
\ProvidesPackage{{{package_name}}}[{font_date.replace("-", "/")} Generated IDS font lookup]
\RequirePackage{{fontspec}}

\ExplSyntaxOn
\newfontfamily\idsfont[Path=./]{{{font_path.name}}}
\prop_new:N \g__ids_to_font_mapping_prop
{mappings}

\msg_new:nnn {{ ids-to-font }} {{ unknown-expression }}
  {{ Unknown~IDS~expression~'#1'. }}

\cs_new_protected:Npn \__ids_to_font_lookup:n #1
  {{
    \prop_get:NnNTF \g__ids_to_font_mapping_prop {{ #1 }} \l_tmpa_tl
      {{ \tl_use:N \l_tmpa_tl }}
      {{ \msg_error:nnn {{ ids-to-font }} {{ unknown-expression }} {{ #1 }} }}
  }}

\NewDocumentCommand \idschar {{ m }}
  {{ \__ids_to_font_lookup:n {{ #1 }} }}
\NewDocumentCommand \ids {{ m }}
  {{ {{\idsfont\__ids_to_font_lookup:n {{ #1 }}}} }}
\ExplSyntaxOff
""",
        encoding="utf-8",
    )


def resolve_all(
    expressions: list[str],
    resolver: Callable[[str], SvgResolution],
    delay: float,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, SvgResolution]:
    resolutions = {}
    for index, ids in enumerate(expressions):
        if index and delay:
            sleeper(delay)
        resolutions[ids] = resolver(ids)
    return resolutions


def build(
    expressions: list[str],
    output_directory: Path,
    previous_mapping: Path | None = None,
    family_name: str = "IDS Glyphs",
    basename: str = "ids-glyphs",
    output_format: str = "woff2",
    font_date: str = "1970-01-01",
    copyright_notice: str = "KAGE-generated outlines preserved from Zi.tools.",
    match_font: Path | None = None,
    delay: float = 10,
    resolver: Callable[[str], SvgResolution] = fetch_resolution,
    sleeper: Callable[[float], None] = time.sleep,
) -> BuildResult:
    if delay < 0:
        raise ValueError("Request delay must not be negative.")
    if output_format not in {"woff2", "ttf"}:
        raise ValueError("Output format must be 'woff2' or 'ttf'.")
    active_ids = sorted(set(expressions))
    if not active_ids:
        raise ValueError("At least one IDS expression is required.")
    previous = load_previous_assignments(previous_mapping)
    assignments = assign_pua(active_ids, previous)
    resolutions = resolve_all(active_ids, resolver, delay, sleeper)
    font, calibration = build_font(
        resolutions,
        assignments,
        family_name,
        font_date,
        copyright_notice,
        output_format,
        match_font,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    temporary_font = output_directory / f"{basename}.{output_format}"
    font.save(temporary_font)
    digest = hashlib.sha256(temporary_font.read_bytes()).hexdigest()
    font_path = output_directory / f"{basename}-{digest[:12]}.{output_format}"
    temporary_font.replace(font_path)
    for previous_font in output_directory.glob(f"{basename}-*.{output_format}"):
        if previous_font != font_path:
            previous_font.unlink()

    style_path = None
    if output_format == "ttf":
        style_path = output_directory / f"{basename}.sty"
        write_latex_package(
            style_path,
            basename,
            font_path,
            font_date,
            active_ids,
            assignments,
        )

    mapping_path = output_directory / f"{basename}.json"
    write_json(
        mapping_path,
        {
            "schema_version": "1.0",
            "font_family": family_name,
            "font": font_path.name,
            "font_format": output_format,
            **(
                {"latex_package": style_path.name}
                if style_path is not None
                else {}
            ),
            "provider": PROVIDER,
            "glyph_license": "GPL-3.0-only",
            **(
                {
                    "calibration": {
                        "reference_font": match_font.name,
                        "reference_sample_size": calibration["sample_size"],
                        "reference_density_sample_size": calibration[
                            "density_sample_size"
                        ],
                        "scale": round(calibration["scale"], 8),
                        "vertical_shift": round(
                            calibration["vertical_shift"], 8
                        ),
                        "target_density": round(
                            calibration["target_density"], 8
                        ),
                        "matched_density": round(
                            calibration["matched_density"], 8
                        ),
                        "outline_inset": calibration["inset"],
                    }
                }
                if calibration is not None and match_font is not None
                else {}
            ),
            "glyphs": {
                ids: {
                    "character": chr(assignments[ids]),
                    "codepoint": f"U+{assignments[ids]:04X}",
                    **(
                        {"resolved_ids": resolutions[ids].resolved_ids}
                        if resolutions[ids].resolved_ids != ids
                        else {}
                    ),
                }
                for ids in active_ids
            },
            "assignments": serialize_assignments(assignments),
        },
    )
    return BuildResult(
        font_path=font_path,
        mapping_path=mapping_path,
        style_path=style_path,
        glyph_count=len(active_ids),
        reserved_assignment_count=len(assignments),
    )
