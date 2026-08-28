"""Resolve IDS expressions and write the paired font and mapping artifacts."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .font import build_font, build_ligature_font
from .manual_outline import resolve_manual_outline
from .lacuna import (
    TOFU_QUESTION,
    load_cjkvi_ids,
    synthesize_question_tofu,
    synthesize_from_reference,
    synthesize_from_zi_tools,
)
from .zi_tools import (
    PROVIDER,
    EncodedResolution,
    SvgResolution,
    ZiToolsClient,
)


@dataclass(frozen=True)
class BuildResult:
    font_paths: dict[str, Path]
    mapping_path: Path
    style_path: Path | None
    glyph_count: int

    @property
    def font_path(self) -> Path:
        return self.font_paths.get("woff2") or self.font_paths["ttf"]


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

    \cs_new_protected:Npn \__ids_to_font_typeset_literal:n #1
      {
        \group_begin:
        \sys_if_engine_xetex:T
          {
            \cs_if_exist:NT \tex_XeTeXgenerateactualtext:D
              { \tex_XeTeXgenerateactualtext:D = 1 \scan_stop: }
            \tl_map_inline:nn { #1 }
              { \tex_XeTeXcharclass:D `##1 = 0 \scan_stop: }
          }
        __IDS_TO_FONT_COMMAND__
        \__ids_to_font_literal:n { #1 }
        \group_end:
      }
""".replace("__IDS_TO_FONT_COMMAND__", font_command)
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
        r"{ \__ids_to_font_typeset_literal:n { #1 } }"
        if literal_ids
        else r"{ \__ids_to_font_lookup:n { #1 } }"
    )
    idschar_command = (
        r"\__ids_to_font_typeset_literal:n { #1 }"
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
\newfontfamily{font_command}[
  Path=./,
  Script=CJK,
  Ligatures=Required
]{{{font_path.name}}}
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


def output_formats(output_format: str) -> tuple[str, ...]:
    if output_format == "both":
        return "woff2", "ttf"
    if output_format in {"woff2", "ttf"}:
        return (output_format,)
    raise ValueError("Output format must be 'woff2', 'ttf', or 'both'.")


def save_fonts(
    font,
    output_directory: Path,
    basename: str,
    formats: tuple[str, ...],
) -> dict[str, Path]:
    paths = {}
    for output_format in formats:
        font.flavor = "woff2" if output_format == "woff2" else None
        paths[output_format] = save_font(
            font,
            output_directory,
            basename,
            output_format,
        )
    return paths


def font_manifest(font_paths: dict[str, Path]) -> dict:
    if len(font_paths) == 1:
        output_format, font_path = next(iter(font_paths.items()))
        return {
            "font": font_path.name,
            "font_format": output_format,
        }
    return {
        "fonts": {
            output_format: font_path.name
            for output_format, font_path in font_paths.items()
        },
        "font_formats": list(font_paths),
    }


def build(
    expressions: list[str],
    output_directory: Path,
    family_name: str = "IDS Glyphs",
    basename: str = "ids-glyphs",
    output_format: str = "both",
    font_date: str = "1970-01-01",
    copyright_notice: str = "KAGE-generated outlines preserved from Zi.tools.",
    match_font: Path | None = None,
    delay: float = 10,
    resolver: Callable[[str], SvgResolution] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    cache_directory: Path | None = None,
    refresh_cache: bool = False,
    lacuna_style: str = "dots",
) -> BuildResult:
    if delay < 0:
        raise ValueError("Request delay must not be negative.")
    formats = output_formats(output_format)
    if lacuna_style not in {"dots", "dashes"}:
        raise ValueError("Lacuna style must be 'dots' or 'dashes'.")
    active_ids = sorted(set(expressions))
    if not active_ids:
        raise ValueError("At least one IDS expression is required.")
    ids_data = None
    resolver_owns_delay = resolver is None
    if resolver is None:
        resolver = ZiToolsClient(
            cache_directory=cache_directory,
            refresh_cache=refresh_cache,
            delay=delay,
            sleeper=sleeper,
        ).fetch_resolution

    def resolve(ids: str) -> SvgResolution:
        nonlocal ids_data
        if ids == TOFU_QUESTION:
            return synthesize_question_tofu(lacuna_style)
        custom = resolve_manual_outline(ids)
        if custom is not None:
            return custom
        try:
            return resolver(ids)
        except ValueError:
            if "□" not in ids:
                raise
            if ids_data is None:
                ids_data = load_cjkvi_ids()
            reference_error = None
            if match_font is not None:
                try:
                    return synthesize_from_reference(
                        ids,
                        match_font,
                        ids_data,
                        lacuna_style=lacuna_style,
                    )
                except ValueError as error:
                    reference_error = error
            try:
                return synthesize_from_zi_tools(
                    ids,
                    ids_data,
                    resolver,
                    delay=0 if resolver_owns_delay else delay,
                    sleeper=sleeper,
                    lacuna_style=lacuna_style,
                )
            except ValueError as error:
                if reference_error is not None:
                    raise ValueError(
                        "Reference-font lacuna synthesis failed: "
                        f"{reference_error}; Zi.tools fallback failed: {error}"
                    ) from error
                raise

    resolutions = resolve_all(
        active_ids,
        resolve,
        0 if resolver_owns_delay else delay,
        sleeper,
    )
    font, calibration, output_names = build_ligature_font(
        resolutions,
        family_name,
        font_date,
        copyright_notice,
        "ttf" if "ttf" in formats else "woff2",
        match_font,
    )
    font_paths = save_fonts(font, output_directory, basename, formats)

    style_path = None
    if "ttf" in formats:
        style_path = output_directory / f"{basename}.sty"
        write_latex_package(
            style_path,
            basename,
            font_paths["ttf"],
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
            **font_manifest(font_paths),
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
        font_paths=font_paths,
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
    resolver: Callable[[str], EncodedResolution] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    cache_directory: Path | None = None,
    refresh_cache: bool = False,
) -> BuildResult:
    if delay < 0:
        raise ValueError("Request delay must not be negative.")
    formats = output_formats(output_format)
    if latex_primary_font is not None:
        if "ttf" not in formats:
            raise ValueError("--latex-primary-font requires TTF output.")
        if not latex_primary_font.is_file():
            raise FileNotFoundError(latex_primary_font)
    active_characters = sorted(set(characters), key=ord)
    if not active_characters:
        raise ValueError("At least one Unicode character is required.")
    resolver_owns_delay = resolver is None
    if resolver is None:
        resolver = ZiToolsClient(
            cache_directory=cache_directory,
            refresh_cache=refresh_cache,
            delay=delay,
            sleeper=sleeper,
        ).fetch_encoded_resolution
    resolutions = resolve_all(
        active_characters,
        resolver,
        0 if resolver_owns_delay else delay,
        sleeper,
    )
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
        "ttf" if "ttf" in formats else "woff2",
        match_font,
    )
    font_paths = save_fonts(font, output_directory, basename, formats)

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
    if "ttf" in formats:
        style_path = output_directory / f"{basename}.sty"
        write_latex_package(
            style_path,
            basename,
            font_paths["ttf"],
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
            **font_manifest(font_paths),
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
        font_paths=font_paths,
        mapping_path=mapping_path,
        style_path=style_path,
        glyph_count=len(active_characters),
    )
