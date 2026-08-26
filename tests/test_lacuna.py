from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from ids_to_font.lacuna import (
    ids_definitions,
    matching_characters,
    normalize_same_axis,
    parse_ids,
    serialize_ids,
    synthesize_from_reference,
    synthesize_from_zi_tools,
)
from ids_to_font.zi_tools import EncodedResolution, SvgResolution


IDS_DATA = """\
U+753E\t甾\t⿱巛田
U+E100\t\uE100\t⿰亻古
U+E101\t\uE101\t⿰木古
U+E102\t\uE102\t⿰石古
"""


def rectangle(
    pen: TTGlyphPen,
    left: int,
    bottom: int,
    right: int,
    top: int,
) -> None:
    pen.moveTo((left, bottom))
    pen.lineTo((right, bottom))
    pen.lineTo((right, top))
    pen.lineTo((left, top))
    pen.closePath()


def write_reference_font(path: Path) -> None:
    glyph_order = [".notdef", "sample1", "sample2", "sample3"]
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    for index, name in enumerate(glyph_order[1:]):
        pen = TTGlyphPen(None)
        rectangle(pen, 60 + index * 10, 100, 350 + index * 10, 900)
        rectangle(pen, 450 + index * 5, 100, 940, 900)
        glyphs[name] = pen.glyph()
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(
        {
            0xE100: "sample1",
            0xE101: "sample2",
            0xE102: "sample3",
        }
    )
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (1000, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=900, descent=-100)
    builder.setupOS2(
        sTypoAscender=900,
        sTypoDescender=-100,
        usWinAscent=900,
        usWinDescent=100,
    )
    builder.setupNameTable(
        {
            "familyName": "Lacuna Reference",
            "styleName": "Regular",
            "fullName": "Lacuna Reference",
            "psName": "LacunaReference",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.font.save(path)


def test_normalizes_same_axis_component_to_three_stack() -> None:
    definitions = ids_definitions(IDS_DATA)
    normalized = normalize_same_axis(parse_ids("⿱甾□"), definitions)
    assert serialize_ids(normalized) == "⿳巛田□"


def test_finds_encoded_examples_matching_lacuna_pattern() -> None:
    assert matching_characters(parse_ids("⿰□古"), IDS_DATA) == [
        "\uE100",
        "\uE101",
        "\uE102",
    ]


def test_synthesizes_dotted_lacuna_from_reference_examples(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.ttf"
    write_reference_font(reference)
    resolution = synthesize_from_reference(
        "⿰□古",
        reference,
        IDS_DATA,
        two_component_resolution,
        lambda ids: SvgResolution(
            requested_ids=ids,
            resolved_ids=ids,
            view_box="0 0 95 95",
            paths=two_component_resolution(ids).paths,
        ),
        delay=0,
    )
    assert resolution.metadata == {
        "synthetic_lacuna": True,
        "layout_provider": "reference.ttf",
        "layout_example": "\uE101",
        "layout_sample_size": 3,
        "outline_provider": "Zi.tools",
        "outline_example": "\uE102",
        "ids_index": (
            "https://raw.githubusercontent.com/cjkvi/cjkvi-ids/"
            "86b4d16159f0079437870408f0ca186e529015db/ids.txt"
        ),
    }
    assert len(resolution.paths) == 2
    assert resolution.paths[0]["d"] == "M 45,5 L 90,5 L 90,90 L 45,90 Z"
    assert resolution.paths[1]["d"].count("M ") > 10
    with TTFont(reference) as font:
        assert set(font.getBestCmap()) == {0xE100, 0xE101, 0xE102}


def two_component_resolution(character: str) -> EncodedResolution:
    return EncodedResolution(
        character=character,
        decompositions=(),
        view_box="0 0 95 95",
        paths=(
            {"d": "M 5,5 L 35,5 L 35,90 L 5,90 Z"},
            {"d": "M 45,5 L 90,5 L 90,90 L 45,90 Z"},
        ),
    )


def test_uses_capped_delayed_zi_tools_encoded_samples() -> None:
    sleeps = []
    resolution = synthesize_from_zi_tools(
        "⿰□古",
        IDS_DATA,
        two_component_resolution,
        lambda value: None,
        sample_size=3,
        delay=2,
        sleeper=sleeps.append,
    )
    assert resolution.metadata["layout_provider"] == "Zi.tools"
    assert resolution.metadata["layout_sample_size"] == 3
    assert sleeps == [2, 2]


def test_uses_generated_proxies_for_unattested_three_stack() -> None:
    ids_data = "U+753E\t甾\t⿱巛田\n"
    calls = []

    def encoded_resolver(character: str) -> EncodedResolution:
        raise ValueError(character)

    def ids_resolver(ids: str) -> SvgResolution:
        calls.append(ids)
        return SvgResolution(
            requested_ids=ids,
            resolved_ids=ids,
            view_box="0 0 95 95",
            paths=(
                {"d": "M 5,5 L 90,5 L 90,25 L 5,25 Z"},
                {"d": "M 5,35 L 90,35 L 90,60 L 5,60 Z"},
                {"d": "M 5,70 L 90,70 L 90,90 L 5,90 Z"},
            ),
        )

    resolution = synthesize_from_zi_tools(
        "⿱甾□",
        ids_data,
        encoded_resolver,
        ids_resolver,
        sample_size=3,
        delay=0,
    )
    assert calls[:3] == ["⿳巛田丯", "⿳巛田巛", "⿳巛田巿"]
    assert resolution.metadata["layout_example"] == "⿳巛田丯"
    assert resolution.metadata["layout_sample_size"] == 3
