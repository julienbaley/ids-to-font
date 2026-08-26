import hashlib
import json
import statistics
from pathlib import Path

from ids_to_font.lacuna import (
    LAYOUT_PROXIES,
    align_proxy_resolutions,
    ids_definitions,
    lacuna_path,
    normalize_same_axis,
    parse_ids,
    replace_lacuna,
    serialize_ids,
    synthesize_from_zi_tools,
)
from ids_to_font.zi_tools import SvgResolution


FIXTURE = Path(__file__).parent / "fixtures" / "lacuna-kage-responses.json"
DEFINITIONS = ids_definitions("U+753E\t甾\t⿱巛田\n")
EXPECTED = {
    "⿰□區": ("⿰丯區", 20, "cb463b0409f4b943"),
    "⿰□古": ("⿰巛古", 9, "45fde1b49e010df0"),
    "⿰□台": ("⿰巿台", 13, "49d8ed983967959e"),
    "⿰□它": ("⿰𡵂它", 18, "56b067a62d513d2c"),
    "⿰□居": ("⿰丯居", 16, "117c9580e4e3fc04"),
    "⿰□昜": ("⿰丯昜", 22, "417d46f45179ba00"),
    "⿰□暴": ("⿰𡵂暴", 34, "0097457f304db820"),
    "⿰□灰": ("⿰𡵂灰", 16, "2bff3d57b5fde822"),
    "⿰□白": ("⿰巿白", 9, "4aee8e59c8deb92a"),
    "⿰□睪": ("⿰丯睪", 26, "079d437fefafb1cf"),
    "⿰□胃": ("⿰巛胃", 17, "39604772099acfad"),
    "⿰氵⿱□口": ("⿰氵⿱巿口", 14, "637104c4fd90de4c"),
    "⿰爿□": ("⿰爿巛", 10, "31137ef8e3a58dfc"),
    "⿱□心": ("⿱巿心", 14, "e72d83fa1a8aea1f"),
    "⿱□木": ("⿱𡵂木", 9, "fb3f375195a09666"),
    "⿱□皿": ("⿱巿皿", 10, "9e74187a9247bb44"),
    "⿱甾□": ("⿳巛田巿", 23, "1f759216f48137d2"),
}


def resolution(name, value):
    return SvgResolution(
        requested_ids=name,
        resolved_ids=value["resolved_ids"],
        view_box=value["view_box"],
        paths=tuple(value["paths"]),
        kage=tuple(value["kage"]),
    )


def test_real_kage_responses_preserve_expected_components() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for ids, expected in EXPECTED.items():
        pattern = normalize_same_axis(parse_ids(ids), DEFINITIONS)
        samples = []
        for proxy in LAYOUT_PROXIES:
            name = serialize_ids(replace_lacuna(pattern, proxy))
            value = fixture.get(name)
            if value is not None:
                samples.append((name, proxy, resolution(name, value)))
        aligned = align_proxy_resolutions(
            samples,
            pattern,
            lacuna_path(pattern),
        )
        median_region = tuple(
            statistics.median(sample[2][index] for sample in aligned)
            for index in range(4)
        )
        chosen = min(
            aligned,
            key=lambda sample: sum(
                (sample[2][index] - median_region[index]) ** 2
                for index in range(4)
            ),
        )
        digest = hashlib.sha256(
            "|".join(
                stroke.path["d"]
                + "@"
                + stroke.path.get("transform", "")
                for stroke in chosen[1]
            ).encode()
        ).hexdigest()[:16]

        assert (chosen[0], len(chosen[1]), digest) == expected


def test_real_kage_responses_work_through_production_synthesis() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def resolver(name):
        value = fixture.get(name)
        if value is None:
            raise ValueError(name)
        return resolution(name, value)

    for ids, expected in EXPECTED.items():
        result = synthesize_from_zi_tools(
            ids,
            "U+753E\t甾\t⿱巛田\n",
            resolver,
            delay=0,
        )
        digest = hashlib.sha256(
            "|".join(
                path["d"] + "@" + path.get("transform", "")
                for path in result.paths[:-1]
            ).encode()
        ).hexdigest()[:16]

        assert (
            result.metadata["outline_example"],
            len(result.paths) - 1,
            digest,
        ) == expected
