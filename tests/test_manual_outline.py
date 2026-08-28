import json
from pathlib import Path

import pytest

from ids_to_font.builder import build
from ids_to_font.manual_outline import load_outline_file, resolve_manual_outline


IDS = "⿱田𫠠"
FRAGMENT = """\
<g fill="black">
  <polygon points="47,21 47,107 35,113 35,15"/>
  <polygon points="41,21 157,21 157,25 41,25"/>
  <path d="M 10,136 L 185,131 L 185,135 L 11,140 Z"/>
</g>
"""


def test_loads_paths_and_polygons_from_zi_tools_scale_fragment(
    tmp_path: Path,
) -> None:
    source = tmp_path / IDS
    source.write_text(FRAGMENT, encoding="utf-8")

    resolution = load_outline_file(IDS, source)

    assert resolution.requested_ids == IDS
    assert resolution.resolved_ids == IDS
    assert resolution.view_box == "0 0 95 95"
    assert len(resolution.paths) == 3
    assert all(
        path["transform"] == "scale(0.462,0.462)"
        for path in resolution.paths
    )
    assert resolution.metadata == {
        "outline_provider": "custom",
        "outline_source": IDS,
    }


def test_packaged_manual_outline_matches_supplied_repair() -> None:
    resolution = resolve_manual_outline(IDS)

    assert resolution is not None
    assert len(resolution.paths) == 15
    assert resolution.metadata == {
        "outline_provider": "manual",
        "outline_source": "⿱田𫠠.svg",
    }


def test_manual_outline_takes_precedence_over_zi_tools(tmp_path: Path) -> None:
    result = build(
        [IDS],
        tmp_path / "build",
        output_format="ttf",
        resolver=lambda value: pytest.fail(f"Unexpected lookup for {value}"),
        delay=0,
    )
    mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))

    assert mapping["glyphs"][IDS]["outline_provider"] == "manual"
    assert (
        mapping["glyphs"][IDS]["outline_source"]
        == "⿱田𫠠.svg"
    )


def test_rejects_custom_outline_transform(tmp_path: Path) -> None:
    source = tmp_path / IDS
    source.write_text(
        '<g transform="translate(1 2)"><polygon points="0,0 1,0 1,1"/></g>',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported transform"):
        load_outline_file(IDS, source)
