import pytest

from ids_to_font.cli import parser


def test_output_format_defaults_to_woff2() -> None:
    args = parser().parse_args(["ids.txt", "--output-directory", "build"])
    assert args.output_format == "woff2"
    assert args.mode == "ligature"


def test_output_format_accepts_ttf() -> None:
    args = parser().parse_args(
        ["ids.txt", "--output-directory", "build", "--output-format", "ttf"]
    )
    assert args.output_format == "ttf"
    assert args.match_font is None


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
