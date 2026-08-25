import pytest

from ids_to_font.cli import parser


def test_output_format_defaults_to_woff2() -> None:
    args = parser().parse_args(["ids.txt", "--output-directory", "build"])
    assert args.output_format == "woff2"


def test_output_format_accepts_ttf() -> None:
    args = parser().parse_args(
        ["ids.txt", "--output-directory", "build", "--output-format", "ttf"]
    )
    assert args.output_format == "ttf"


def test_output_format_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(
            ["ids.txt", "--output-directory", "build", "--output-format", "otf"]
        )
