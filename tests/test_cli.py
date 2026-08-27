import pytest

from ids_to_font.cli import parser


def test_output_format_uses_mode_specific_default() -> None:
    args = parser().parse_args(["ids.txt", "--output-directory", "build"])
    assert args.output_format is None
    assert args.mode == "ligature"


def test_output_format_accepts_ttf() -> None:
    args = parser().parse_args(
        ["ids.txt", "--output-directory", "build", "--output-format", "ttf"]
    )
    assert args.output_format == "ttf"
    assert args.match_font is None


def test_output_format_accepts_both() -> None:
    args = parser().parse_args(
        ["ids.txt", "--output-directory", "build", "--output-format", "both"]
    )
    assert args.output_format == "both"


def test_accepts_reference_font() -> None:
    args = parser().parse_args(
        [
            "ids.txt",
            "--output-directory",
            "build",
            "--match-font",
            "reference.ttf",
        ]
    )
    assert str(args.match_font) == "reference.ttf"


def test_accepts_cache_controls() -> None:
    args = parser().parse_args(
        [
            "ids.txt",
            "--output-directory",
            "build",
            "--cache-directory",
            "cache",
            "--refresh-cache",
        ]
    )
    assert str(args.cache_directory) == "cache"
    assert args.refresh_cache is True


def test_accepts_dashed_lacuna_style() -> None:
    args = parser().parse_args(
        [
            "ids.txt",
            "--output-directory",
            "build",
            "--lacuna-style",
            "dashes",
        ]
    )
    assert args.lacuna_style == "dashes"


def test_accepts_unicode_mode_and_latex_primary_font() -> None:
    args = parser().parse_args(
        [
            "characters.txt",
            "--mode",
            "unicode",
            "--output-format",
            "ttf",
            "--output-directory",
            "build",
            "--latex-primary-font",
            "primary.ttf",
        ]
    )
    assert args.mode == "unicode"
    assert str(args.latex_primary_font) == "primary.ttf"


def test_accepts_explicit_ligature_mode() -> None:
    args = parser().parse_args(
        ["ids.txt", "--mode", "ligature", "--output-directory", "build"]
    )
    assert args.mode == "ligature"


def test_rejects_removed_pua_mode() -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(
            ["ids.txt", "--mode", "pua", "--output-directory", "build"]
        )


def test_rejects_removed_previous_mapping_option() -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(
            [
                "ids.txt",
                "--previous-mapping",
                "previous.json",
                "--output-directory",
                "build",
            ]
        )


def test_output_format_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(
            ["ids.txt", "--output-directory", "build", "--output-format", "otf"]
        )
