from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from ids_to_font.lacuna import (
    PROXY_STROKE_COUNTS,
    align_proxy_resolutions,
    dotted_path,
    extract_proxy_strokes,
    ids_definitions,
    matching_characters,
    normalize_same_axis,
    parse_ids,
    segment_kage_paths,
    serialize_ids,
    synthesize_from_reference,
    synthesize_from_zi_tools,
)
from ids_to_font.zi_tools import SvgResolution


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
        generated_proxy_resolution,
        delay=0,
    )
    assert resolution.metadata == {
        "synthetic_lacuna": True,
        "layout_provider": "reference.ttf",
        "layout_example": "\uE101",
        "layout_sample_size": 3,
        "outline_provider": "Zi.tools",
        "outline_example": "⿰巛古",
        "ids_index": (
            "https://raw.githubusercontent.com/cjkvi/cjkvi-ids/"
            "86b4d16159f0079437870408f0ca186e529015db/ids.txt"
        ),
    }
    assert len(resolution.paths) == 2
    assert resolution.paths[0]["d"] == "M 100,10H190V190H100Z"
    assert resolution.paths[1]["d"].count("M ") > 10
    with TTFont(reference) as font:
        assert set(font.getBestCmap()) == {0xE100, 0xE101, 0xE102}


def generated_proxy_resolution(ids: str) -> SvgResolution:
    proxy = (
        ids[-1]
        if ids.startswith("⿳")
        else ids[3]
        if ids.startswith("⿰氵⿱")
        else ids[1]
    )
    proxy_count = PROXY_STROKE_COUNTS[proxy]
    if ids.startswith("⿳"):
        semantic_bounds = [
            (10, 10, 190, 50),
            (10, 70, 190, 120),
            *[
                (10 + index * 10, 140, 18 + index * 10, 190)
                for index in range(proxy_count)
            ],
        ]
    elif ids.startswith("⿰氵⿱"):
        semantic_bounds = [
            (10, 10, 30, 30),
            (10, 45, 30, 65),
            (10, 80, 30, 100),
            (15, 20, 25, 90),
            *[
                (80 + index * 10, 10, 88 + index * 10, 80)
                for index in range(proxy_count)
            ],
            (80, 110, 80, 180),
            (80, 110, 180, 110),
            (180, 110, 180, 180),
            (80, 180, 180, 180),
        ]
    else:
        semantic_bounds = [
            *[
                (10 + index * 10, 10, 18 + index * 10, 190)
                for index in range(proxy_count)
            ],
            (100, 10, 190, 190),
        ]
    paths = []
    for index, (left, top, right, bottom) in enumerate(semantic_bounds):
        paths.append(
            {
                "d": f"M {left},{top}H{right}V{bottom}H{left}Z",
                "transform": "scale(0.462,0.462)",
            }
        )
        if index == 0:
            paths.append(
                {
                    "d": (
                        f"M {left + 1},{top + 1}H{left + 3}"
                        f"V{top + 3}H{left + 1}Z"
                    ),
                    "transform": "scale(0.462,0.462)",
                }
            )
    return SvgResolution(
        requested_ids=ids,
        resolved_ids=ids,
        view_box="0 0 95 95",
        paths=tuple(paths),
        kage=tuple(
            f"1:0:0:{left}:{top}:{right}:{bottom}"
            for left, top, right, bottom in semantic_bounds
        ),
    )


def test_uses_capped_delayed_zi_tools_proxy_samples() -> None:
    sleeps = []
    resolution = synthesize_from_zi_tools(
        "⿰□古",
        IDS_DATA,
        generated_proxy_resolution,
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

    def ids_resolver(ids: str) -> SvgResolution:
        calls.append(ids)
        return generated_proxy_resolution(ids)

    resolution = synthesize_from_zi_tools(
        "⿱甾□",
        ids_data,
        ids_resolver,
        sample_size=3,
        delay=0,
    )
    assert calls[:3] == ["⿳巛田丯", "⿳巛田巛", "⿳巛田巿"]
    assert resolution.metadata["layout_example"] == "⿳巛田丯"
    assert resolution.metadata["layout_sample_size"] == 3


def test_maps_one_kage_stroke_to_multiple_svg_paths() -> None:
    resolution = generated_proxy_resolution("⿰丯古")

    semantic, groups = segment_kage_paths(resolution)

    assert len(semantic) == 5
    assert [len(group) for group in groups] == [2, 1, 1, 1, 1]


def test_removes_semantic_proxy_strokes_not_fixed_svg_path_count() -> None:
    resolution = generated_proxy_resolution("⿰丯古")

    retained, _ = extract_proxy_strokes(
        resolution,
        parse_ids("⿰□古"),
        (0,),
        "丯",
    )

    assert [stroke.path["d"] for stroke in retained] == [
        "M 100,10H190V190H100Z"
    ]


def test_aligns_nested_proxy_block_across_kage_programs() -> None:
    samples = [
        (
            ids,
            proxy,
            generated_proxy_resolution(ids),
        )
        for proxy in ("丯", "巛", "巿")
        for ids in [f"⿰氵⿱{proxy}口"]
    ]

    aligned = align_proxy_resolutions(
        samples,
        parse_ids("⿰氵⿱□口"),
        (1, 0),
    )

    assert len(aligned) == 3
    assert all(len(strokes) == 9 for _, strokes, _ in aligned)
    assert all(
        all(
            not (37 <= stroke.bounds[0] and stroke.bounds[3] <= 37)
            for stroke in strokes
        )
        for _, strokes, _ in aligned
    )


def test_dotted_lacuna_uses_only_polygonal_outlines() -> None:
    path = dotted_path((5, 5, 40, 90))

    assert "A " not in path
    assert path.count(" L ") > 10
