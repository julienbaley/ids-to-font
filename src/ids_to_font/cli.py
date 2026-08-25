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
            "Build a PUA IDS font or an encoded Unicode supplement "
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
        choices=("pua", "unicode"),
        default="pua",
        help="Input and cmap mode (default: pua)",
    )
    result.add_argument(
        "--output-directory",
        type=Path,
        required=True,
        help="Directory for the generated font and mapping",
    )
    result.add_argument(
        "--previous-mapping",
        type=Path,
        help="Earlier generated JSON mapping whose PUA assignments must be reused",
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
            "and line metrics should be matched"
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
        help="Seconds between Zi.tools requests (default: 10)",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.mode == "unicode":
            if args.previous_mapping is not None:
                raise ValueError("--previous-mapping is only valid in PUA mode.")
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
            )
        else:
            if args.latex_primary_font is not None:
                raise ValueError(
                    "--latex-primary-font is only valid in Unicode mode."
                )
            result = build(
                read_ids(args.input),
                args.output_directory,
                previous_mapping=args.previous_mapping,
                family_name=args.family_name or "IDS Glyphs",
                basename=args.basename or "ids-glyphs",
                output_format=args.output_format,
                font_date=args.font_date,
                copyright_notice=args.copyright,
                match_font=args.match_font,
                delay=args.delay,
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
        + " "
        f"({result.glyph_count} active glyphs; "
        f"{result.reserved_assignment_count} reserved assignments)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
