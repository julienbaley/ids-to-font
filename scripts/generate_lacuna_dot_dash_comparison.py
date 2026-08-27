from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from ids_to_font.lacuna import load_cjkvi_ids, synthesize_from_reference


HERE = Path(__file__).parent
OUTPUT = HERE / (
    "lacuna-17-babelstone-dot-dash-"
    f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.svg"
)
FONT_PATH = Path(
    "/home/julien/projets/spelling/vendor/babelstone-han/BabelStoneHan.ttf"
)
EXPRESSIONS = [
    "⿰□區",
    "⿰□古",
    "⿰□台",
    "⿰□它",
    "⿰□居",
    "⿰□昜",
    "⿰□暴",
    "⿰□灰",
    "⿰□白",
    "⿰□睪",
    "⿰□胃",
    "⿰氵⿱□口",
    "⿰爿□",
    "⿱□心",
    "⿱□木",
    "⿱□皿",
    "⿱甾□",
]


def svg_paths(paths: tuple[dict[str, str], ...]) -> str:
    return "".join(
        f'<path d="{escape(path["d"])}" '
        f'transform="{escape(path.get("transform", ""))}"/>'
        for path in paths
    )


def main() -> None:
    print(f"Writing {OUTPUT}", flush=True)
    ids_data = load_cjkvi_ids()
    row_height = 111
    header = 32
    width = 330
    height = header + row_height * len(EXPRESSIONS) + 8
    content = []
    for index, ids in enumerate(EXPRESSIONS):
        print(
            f"\r[{'█' * index}{'·' * (len(EXPRESSIONS) - index)}] "
            f"{index}/{len(EXPRESSIONS)} {ids}",
            end="",
            flush=True,
        )
        dotted = synthesize_from_reference(
            ids,
            FONT_PATH,
            ids_data,
            lacuna_style="dots",
        )
        dashed = synthesize_from_reference(
            ids,
            FONT_PATH,
            ids_data,
            lacuna_style="dashes",
        )
        y = header + index * row_height
        content.extend(
            (
                f'<text class="label" x="112" y="{y + 43}">'
                f"{escape(ids)}</text>",
                f'<text class="reference" x="112" y="{y + 53}">'
                f"{escape(str(dotted.metadata['outline_example']))}</text>",
                f'<g transform="translate(120 {y})">'
                f'<g fill="#111" fill-rule="nonzero">'
                f"{svg_paths(dotted.paths)}</g>"
                '<rect class="box" width="95" height="95"/></g>',
                f'<g transform="translate(225 {y})">'
                f'<g fill="#111" fill-rule="nonzero">'
                f"{svg_paths(dashed.paths)}</g>"
                '<rect class="box" width="95" height="95"/></g>',
            )
        )
        print(
            f"\r[{'█' * (index + 1)}"
            f"{'·' * (len(EXPRESSIONS) - index - 1)}] "
            f"{index + 1}/{len(EXPRESSIONS)} {ids}",
            flush=True,
        )
    OUTPUT.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg"
 viewBox="0 0 {width} {height}" width="1320" height="{height * 4}">
<rect width="{width}" height="{height}" fill="white"/>
<style>
.heading {{ font: 6px sans-serif; font-weight: bold; fill: #222;
  text-anchor: middle; }}
.label {{ font: 7px sans-serif; fill: #222; text-anchor: end;
  dominant-baseline: middle; }}
.reference {{ font: 3.1px sans-serif; fill: #777; text-anchor: end; }}
.box {{ fill: none; stroke: #d22; stroke-width: .7; }}
</style>
<text class="heading" x="167.5" y="17">BabelStone with dots</text>
<text class="heading" x="272.5" y="17">BabelStone with dashes</text>
{''.join(content)}
</svg>
""",
        encoding="utf-8",
    )
    print(f"Done: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
