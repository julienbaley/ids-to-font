"""Resolve IDS expressions and write the paired font and mapping artifacts."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .font import build_font, build_ligature_font
from .lacuna import (
    load_cjkvi_ids,
    synthesize_from_reference,
    synthesize_from_zi_tools,
)
from .zi_tools import (
    PROVIDER,
    EncodedResolution,
    SvgResolution,
    fetch_encoded_resolution,
    fetch_resolution,
)


@dataclass(frozen=True)
class BuildResult:
    font_path: Path
    mapping_path: Path
    style_path: Path | None
    glyph_count: int


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
    aliases: dict[str, int],
    latex_primary_font: Path | None = None,
    literal_ids: bool = False,
) -> None:
    suffix = hashlib.sha256(package_name.encode("utf-8")).hexdigest()[:10].translate(
        str.maketrans("0123456789", "abcdefghij")
    )
    font_command = f"\\idstofontfont{suffix}"
    han_command = f"\\idstofonthanfamily{suffix}"
    mappings = "\n".join(
        "\n".join(
            (
                (
                    r"\prop_gput:Nnn \g__ids_to_font_supported_prop"
                    f" {{ {ids} }} {{ }}"
                )
                if literal_ids
                else (
                    r"\prop_gput:Nnn \g__ids_to_font_character_prop"
                    f" {{ {ids} }} {{ \\char_generate:nn {{ \"{codepoint:X} }} {{ 12 }} }}"
                ),
                r"\prop_gput:Nnn \g__ids_to_font_font_prop"
                f" {{ {ids} }} {{ {font_command} }}",
            )
        )
        for ids, codepoint in sorted(aliases.items())
    )
    character_definition = (
        r"""
    \cs_new_protected:Npn \__ids_to_font_literal:n #1
      {
        \prop_if_in:NnTF \g__ids_to_font_supported_prop { #1 }
          { #1 }
          { \msg_error:nnn { ids-to-font } { unknown-expression } { #1 } }
      }
"""
        if literal_ids
        else r"""
    \cs_new_protected:Npn \__ids_to_font_character:n #1
      {
    \prop_get:NnNTF
      \g__ids_to_font_character_prop { #1 } \l_tmpa_tl
      { \tl_use:N \l_tmpa_tl }
      { \msg_error:nnn { ids-to-font } { unknown-expression } { #1 } }
      }
"""
    )
    lookup_definition = (
        ""
        if literal_ids
        else r"""
    \cs_new_protected:Npn \__ids_to_font_lookup:n #1
      {
    \prop_get:NnNTF \g__ids_to_font_font_prop { #1 } \l_tmpa_tl
      {
        \group_begin:
        \tl_use:N \l_tmpa_tl
        \__ids_to_font_character:n { #1 }
        \group_end:
      }
      { \msg_error:nnn { ids-to-font } { unknown-expression } { #1 } }
      }
"""
    )
    character_props = (
        r"\prop_new:N \g__ids_to_font_supported_prop"
        if literal_ids
        else r"\prop_new:N \g__ids_to_font_character_prop"
    )
    ids_command = (
        rf"{{ \group_begin: {font_command} \__ids_to_font_literal:n {{ #1 }} \group_end: }}"
        if literal_ids
        else r"{ \__ids_to_font_lookup:n { #1 } }"
    )
    idschar_command = (
        rf"\group_begin: {font_command} \__ids_to_font_literal:n {{ #1 }} \group_end:"
        if literal_ids
        else r"\__ids_to_font_character:n { #1 }"
    )
    fallback = ""
    if latex_primary_font is not None:
        fallback = rf"""
\RequirePackage{{iftex}}
\ifXeTeX
  \RequirePackage{{xeCJK}}
  \newCJKfontfamily[ids-to-font-{suffix}]{han_command}[Path=./]{{{latex_primary_font.name}}}
  \setCJKfallbackfamilyfont{{ids-to-font-{suffix}}}[Path=./]{{{font_path.name}}}
  \xeCJKsetup{{AutoFallBack=true}}
\else
  \ifLuaTeX
    \directlua{{luaotfload.add_fallback("idstofont{suffix}", {{"file:{font_path.name}:mode=node"}})}}
    \newfontfamily{han_command}[
      Path=./,
      RawFeature={{fallback=idstofont{suffix}}}
    ]{{{latex_primary_font.name}}}
  \else
    \PackageError{{{package_name}}}
      {{A Unicode TeX engine is required}}
      {{Compile with XeLaTeX or LuaLaTeX.}}
  \fi
\fi
\ExplSyntaxOn
\cs_if_exist:NF \idshanfamily
  {{ \cs_new_eq:NN \idshanfamily {han_command} }}
\ExplSyntaxOff
"""
    path.write_text(
        rf"""\NeedsTeXFormat{{LaTeX2e}}
\ProvidesPackage{{{package_name}}}[{font_date.replace("-", "/")} Generated IDS font lookup]
\RequirePackage{{fontspec}}

\ExplSyntaxOn
\newfontfamily{font_command}[Path=./]{{{font_path.name}}}
\prop_if_exist:NF \g__ids_to_font_font_prop
  {{
{character_props}
    \prop_new:N \g__ids_to_font_font_prop

    \msg_new:nnn {{ ids-to-font }} {{ unknown-expression }}
      {{ Unknown~IDS~expression~'#1'. }}

{character_definition}
{lookup_definition}

    \NewDocumentCommand \idschar {{ m }}
  {{ {idschar_command} }}
    \NewDocumentCommand \ids {{ m }}
      {ids_command}
  }}
{mappings}
\cs_if_exist:NF \idsfont
  {{ \cs_new_eq:NN \idsfont {font_command} }}
\ExplSyntaxOff
{fallback}""",
        encoding="utf-8",
    )


def resolve_all(
    values: list[str],
    resolver: Callable,
    delay: float,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    resolutions = {}
    for index, value in enumerate(values):
        if index and delay:
            sleeper(delay)
        resolutions[value] = resolver(value)
    return resolutions


def calibration_metadata(calibration: dict | None, match_font: Path | None) -> dict:
    if calibration is None or match_font is None:
        return {}
    return {
        "calibration": {
            "reference_font": match_font.name,
            "reference_sample_size": calibration["sample_size"],
            "reference_density_sample_size": calibration["density_sample_size"],
            "scale": round(calibration["scale"], 8),
            "vertical_shift": round(calibration["vertical_shift"], 8),
            "target_density": round(calibration["target_density"], 8),
            "matched_density": round(calibration["matched_density"], 8),
            "outline_inset": calibration["inset"],
        }
    }


def save_font(
    font,
    output_directory: Path,
    basename: str,
    output_format: str,
) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    temporary_font = output_directory / f"{basename}.{output_format}"
    font.save(temporary_font)
    digest = hashlib.sha256(temporary_font.read_bytes()).hexdigest()
    font_path = output_directory / f"{basename}-{digest[:12]}.{output_format}"
    temporary_font.replace(font_path)
    for previous_font in output_directory.glob(f"{basename}-*.{output_format}"):
        if previous_font != font_path:
            previous_font.unlink()
    return font_path


def build(
    expressions: list[str],
    output_directory: Path,
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
    ids_data = None

    def resolve(ids: str) -> SvgResolution:
        nonlocal ids_data
        try:
            return resolver(ids)
        except ValueError:
            if "□" not in ids:
                raise
            if ids_data is None:
                ids_data = load_cjkvi_ids()
            if match_font is not None:
                try:
                    return synthesize_from_reference(
                        ids,
                        match_font,
                        ids_data,
                        resolver,
                        delay=delay,
                        sleeper=sleeper,
                    )
                except ValueError:
                    pass
            return synthesize_from_zi_tools(
                ids,
                ids_data,
                resolver,
                delay=delay,
                sleeper=sleeper,
            )

    resolutions = resolve_all(active_ids, resolve, delay, sleeper)
    font, calibration, output_names = build_ligature_font(
        resolutions,
        family_name,
        font_date,
        copyright_notice,
        output_format,
        match_font,
    )
    font_path = save_font(font, output_directory, basename, output_format)

    style_path = None
    if output_format == "ttf":
        style_path = output_directory / f"{basename}.sty"
        write_latex_package(
            style_path,
            basename,
            font_path,
            font_date,
            {ids: 0 for ids in active_ids},
            literal_ids=True,
        )

    mapping_path = output_directory / f"{basename}.json"
    write_json(
        mapping_path,
        {
            "schema_version": "1.0",
            "font_family": family_name,
            "font": font_path.name,
            "font_format": output_format,
            "mode": "ligature",
            **({"latex_package": style_path.name} if style_path is not None else {}),
            "provider": PROVIDER,
            "glyph_license": "GPL-3.0-only",
            **calibration_metadata(calibration, match_font),
            "glyphs": {
                ids: {
                    "glyph": output_names[ids],
                    **resolutions[ids].metadata,
                    **(
                        {"resolved_ids": resolutions[ids].resolved_ids}
                        if resolutions[ids].resolved_ids != ids
                        else {}
                    ),
                }
                for ids in active_ids
            },
        },
    )
    return BuildResult(
        font_path=font_path,
        mapping_path=mapping_path,
        style_path=style_path,
        glyph_count=len(active_ids),
    )


def build_encoded(
    characters: list[str],
    output_directory: Path,
    family_name: str = "Unicode Supplement",
    basename: str = "unicode-supplement",
    output_format: str = "woff2",
    font_date: str = "1970-01-01",
    copyright_notice: str = "KAGE-generated outlines preserved from Zi.tools.",
    match_font: Path | None = None,
    latex_primary_font: Path | None = None,
    delay: float = 10,
    resolver: Callable[[str], EncodedResolution] = fetch_encoded_resolution,
    sleeper: Callable[[float], None] = time.sleep,
) -> BuildResult:
    if delay < 0:
        raise ValueError("Request delay must not be negative.")
    if output_format not in {"woff2", "ttf"}:
        raise ValueError("Output format must be 'woff2' or 'ttf'.")
    if latex_primary_font is not None:
        if output_format != "ttf":
            raise ValueError("--latex-primary-font requires TTF output.")
        if not latex_primary_font.is_file():
            raise FileNotFoundError(latex_primary_font)
    active_characters = sorted(set(characters), key=ord)
    if not active_characters:
        raise ValueError("At least one Unicode character is required.")
    resolutions = resolve_all(active_characters, resolver, delay, sleeper)
    assignments = {
        character: ord(character)
        for character in active_characters
    }
    font, calibration = build_font(
        resolutions,
        assignments,
        family_name,
        font_date,
        copyright_notice,
        output_format,
        match_font,
    )
    font_path = save_font(font, output_directory, basename, output_format)

    aliases = {}
    for character in active_characters:
        for ids in resolutions[character].decompositions:
            existing = aliases.get(ids)
            if existing is not None and existing != ord(character):
                raise ValueError(
                    f"Zi.tools decomposition {ids} is ambiguous between "
                    f"U+{existing:04X} and U+{ord(character):04X}."
                )
            aliases[ids] = ord(character)

    style_path = None
    if output_format == "ttf":
        style_path = output_directory / f"{basename}.sty"
        write_latex_package(
            style_path,
            basename,
            font_path,
            font_date,
            aliases,
            latex_primary_font,
        )

    mapping_path = output_directory / f"{basename}.json"
    write_json(
        mapping_path,
        {
            "schema_version": "1.0",
            "font_family": family_name,
            "font": font_path.name,
            "font_format": output_format,
            "mode": "unicode",
            **(
                {"latex_package": style_path.name}
                if style_path is not None
                else {}
            ),
            **(
                {"latex_primary_font": latex_primary_font.name}
                if latex_primary_font is not None
                else {}
            ),
            "provider": PROVIDER,
            "glyph_license": "GPL-3.0-only",
            **calibration_metadata(calibration, match_font),
            "glyphs": {
                character: {
                    "character": character,
                    "codepoint": f"U+{ord(character):04X}",
                    "decompositions": list(
                        resolutions[character].decompositions
                    ),
                    **(
                        {
                            "preferred_decomposition": resolutions[
                                character
                            ].decompositions[0]
                        }
                        if resolutions[character].decompositions
                        else {}
                    ),
                }
                for character in active_characters
            },
        },
    )
    return BuildResult(
        font_path=font_path,
        mapping_path=mapping_path,
        style_path=style_path,
        glyph_count=len(active_characters),
    )
