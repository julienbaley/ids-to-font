from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from ids_to_font.lacuna import (
    LAYOUT_PROXIES,
    ids_definitions,
    load_cjkvi_ids,
    normalize_same_axis,
    parse_ids,
    replace_lacuna,
    serialize_ids,
    synthesize_from_reference,
    synthesize_from_zi_tools,
)
from ids_to_font.zi_tools import SvgResolution, fetch_resolution


HERE = Path(__file__).parent
OUTPUT = HERE / (
    "lacuna-17-zitools-babelstone-"
    f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.svg"
)
CACHE = HERE / "lacuna-zitools-cache.json"
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


def cached_resolution(name: str, value: dict) -> SvgResolution:
    return SvgResolution(
        requested_ids=name,
        resolved_ids=value["resolved_ids"],
        view_box=value["view_box"],
        paths=tuple(value["paths"]),
        kage=tuple(value.get("kage", ())),
    )


def svg_paths(resolution: SvgResolution) -> str:
    return "".join(
        f'<path d="{escape(path["d"])}" '
        f'transform="{escape(path.get("transform", ""))}"/>'
        for path in resolution.paths
    )


def source_label(resolution: SvgResolution) -> str:
    provider = resolution.metadata["outline_provider"]
    example = resolution.metadata["outline_example"]
    count = resolution.metadata["layout_sample_size"]
    return f"{provider}: {example} ({count})"


def main() -> None:
    print(f"Writing {OUTPUT}", flush=True)
    ids_data = load_cjkvi_ids()
    definitions = ids_definitions(ids_data)
    patterns = {
        ids: normalize_same_axis(parse_ids(ids), definitions)
        for ids in EXPRESSIONS
    }
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    templates = {
        serialize_ids(replace_lacuna(pattern, proxy))
        for pattern in patterns.values()
        for proxy in LAYOUT_PROXIES
    }
    missing = sorted(
        template
        for template in templates
        if template not in cache
        or (
            cache[template] is not None
            and "kage" not in cache[template]
        )
    )

    def fetch_template(template: str):
        try:
            resolution = fetch_resolution(template)
        except (OSError, ValueError):
            return template, None
        return template, {
            "resolved_ids": resolution.resolved_ids,
            "view_box": resolution.view_box,
            "paths": list(resolution.paths),
            "kage": list(resolution.kage),
        }

    if missing:
        print(f"Fetching {len(missing)} Zi.tools templates concurrently", flush=True)
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(fetch_template, template): template
                for template in missing
            }
            for completed, future in enumerate(as_completed(futures), start=1):
                template, value = future.result()
                cache[template] = value
                print(
                    f"\rZi.tools [{completed}/{len(missing)}]",
                    end="",
                    flush=True,
                )
        print(flush=True)
        CACHE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def resolver(ids: str) -> SvgResolution:
        value = cache.get(ids)
        if value is None or not value.get("kage"):
            raise ValueError(f"No cached KAGE response for {ids}.")
        return cached_resolution(ids, value)

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
        zi_resolution = synthesize_from_zi_tools(
            ids,
            ids_data,
            resolver,
            delay=0,
        )
        try:
            reference_resolution = synthesize_from_reference(
                ids,
                FONT_PATH,
                ids_data,
            )
        except ValueError:
            reference_resolution = zi_resolution
        print(
            f"\r[{'█' * (index + 1)}"
            f"{'·' * (len(EXPRESSIONS) - index - 1)}] "
            f"{index + 1}/{len(EXPRESSIONS)} {ids}",
            flush=True,
        )
        y = header + index * row_height
        content.extend(
            (
                f'<text class="label" x="112" y="{y + 43}">'
                f"{escape(ids)}</text>",
                f'<text class="reference" x="112" y="{y + 53}">'
                f"Zi: {escape(source_label(zi_resolution))}; "
                f"Ref: {escape(source_label(reference_resolution))}</text>",
                f'<g transform="translate(120 {y})">'
                f'<g fill="#111" fill-rule="nonzero">'
                f"{svg_paths(zi_resolution)}</g>"
                '<rect class="box" width="95" height="95"/></g>',
                f'<g transform="translate(225 {y})">'
                f'<g fill="#111" fill-rule="nonzero">'
                f"{svg_paths(reference_resolution)}</g>"
                '<rect class="box" width="95" height="95"/></g>',
            )
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
<text class="heading" x="167.5" y="17">Production without --match-font</text>
<text class="heading" x="272.5" y="17">Production with --match-font</text>
{''.join(content)}
</svg>
""",
        encoding="utf-8",
    )
    print(f"Done: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
