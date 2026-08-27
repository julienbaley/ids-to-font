"""Command-line interface for ids-to-font."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import build, build_encoded
from .input import read_characters, read_ids


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Build a required-ligature IDS font or an encoded Unicode supplement "
            "from newline-delimited input."
        )
    )
    result.add_argument(
        "input",
        type=Path,
        help="UTF-8 file with one IDS or Unicode scalar per line",
    )
    result.add_argument(
        "--mode",
        choices=("ligature", "unicode"),
        default="ligature",
        help="Input and cmap mode (default: ligature)",
    )
    result.add_argument(
        "--output-directory",
        type=Path,
        required=True,
        help="Directory for the generated font and mapping",
    )
    result.add_argument("--family-name")
    result.add_argument("--basename")
    result.add_argument(
        "--output-format",
        choices=("woff2", "ttf"),
        default="woff2",
        help="Generated font format (default: woff2)",
    )
    result.add_argument(
        "--font-date",
        default="1970-01-01",
        help="Date embedded in the font in YYYY-MM-DD format",
    )
    result.add_argument(
        "--copyright",
        default="KAGE-generated outlines preserved from Zi.tools.",
        help="Copyright text embedded in the font",
    )
    result.add_argument(
        "--match-font",
        type=Path,
        help=(
            "Reference TTF/OTF whose full-width Han glyph size, baseline, "
            "and line metrics should be matched; also supplies surviving "
            "outlines for IDS lacunae"
        ),
    )
    result.add_argument(
        "--latex-primary-font",
        type=Path,
        help=(
            "Primary TTF/OTF to pair with a Unicode supplement in the "
            "generated XeLaTeX/LuaLaTeX package"
        ),
    )
    result.add_argument(
        "--delay",
        type=float,
        default=10,
        help="Seconds between uncached Zi.tools requests (default: 10)",
    )
    result.add_argument(
        "--cache-directory",
        type=Path,
        help=(
            "Zi.tools cache directory (default: "
            "$XDG_CACHE_HOME/ids-to-font/zi-tools)"
        ),
    )
    result.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Bypass and replace existing Zi.tools cache entries",
    )
    result.add_argument(
        "--lacuna-style",
        choices=("dots", "dashes"),
        default="dots",
        help="Border style for □ lacunae in ligature mode (default: dots)",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.mode == "unicode":
            if args.lacuna_style != "dots":
                raise ValueError(
                    "--lacuna-style is only valid in ligature mode."
                )
            result = build_encoded(
                read_characters(args.input),
                args.output_directory,
                family_name=args.family_name or "Unicode Supplement",
                basename=args.basename or "unicode-supplement",
                output_format=args.output_format,
                font_date=args.font_date,
                copyright_notice=args.copyright,
                match_font=args.match_font,
                latex_primary_font=args.latex_primary_font,
                delay=args.delay,
                cache_directory=args.cache_directory,
                refresh_cache=args.refresh_cache,
            )
        else:
            if args.latex_primary_font is not None:
                raise ValueError(
                    "--latex-primary-font is only valid in Unicode mode."
                )
            result = build(
                read_ids(args.input),
                args.output_directory,
                family_name=args.family_name or "IDS Glyphs",
                basename=args.basename or "ids-glyphs",
                output_format=args.output_format,
                font_date=args.font_date,
                copyright_notice=args.copyright,
                match_font=args.match_font,
                delay=args.delay,
                cache_directory=args.cache_directory,
                refresh_cache=args.refresh_cache,
                lacuna_style=args.lacuna_style,
            )
    except (OSError, ValueError) as error:
        print(f"ids-to-font: {error}", file=sys.stderr)
        return 1
    print(
        "Built "
        + ", ".join(
            str(path)
            for path in (
                result.font_path,
                result.mapping_path,
                result.style_path,
            )
            if path is not None
        )
        + f" ({result.glyph_count} active glyphs)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
