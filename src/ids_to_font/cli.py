"""Command-line interface for ids-to-font."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import build
from .input import read_ids


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Build a font and IDS-to-PUA JSON mapping from "
            "newline-delimited IDS expressions."
        )
    )
    result.add_argument("input", type=Path, help="UTF-8 file with one IDS per line")
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
    result.add_argument("--family-name", default="IDS Glyphs")
    result.add_argument("--basename", default="ids-glyphs")
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
        "--delay",
        type=float,
        default=10,
        help="Seconds between Zi.tools requests (default: 10)",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = build(
            read_ids(args.input),
            args.output_directory,
            previous_mapping=args.previous_mapping,
            family_name=args.family_name,
            basename=args.basename,
            output_format=args.output_format,
            font_date=args.font_date,
            copyright_notice=args.copyright,
            delay=args.delay,
        )
    except (OSError, ValueError) as error:
        print(f"ids-to-font: {error}", file=sys.stderr)
        return 1
    print(
        f"Built {result.font_path} and {result.mapping_path} "
        f"({result.glyph_count} active glyphs; "
        f"{result.reserved_assignment_count} reserved assignments)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
