import json

import pytest

from ids_to_font.zi_tools import fetch_encoded_resolution, fetch_resolution


class Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener(payload: dict):
    return lambda *args, **kwargs: Response(payload)


def test_fetches_standard_svg_paths() -> None:
    resolution = fetch_resolution(
        "⿰丯戈",
        opener(
            {
                "⿰丯戈": {
                    "lv1": {"match_u_list": []},
                    "svg": "M 0,0|M 1,1",
                }
            }
        ),
    )
    assert resolution.requested_ids == "⿰丯戈"
    assert resolution.resolved_ids == "⿰丯戈"
    assert [path["d"] for path in resolution.paths] == ["M 0,0", "M 1,1"]


def test_uses_single_substitution_returned_by_zi_tools() -> None:
    resolution = fetch_resolution(
        "⿰鼠⿱八呂",
        opener(
            {
                "font": {"⿰鼠⿱㕣口": "M 0,0"},
                "⿰鼠⿱八呂": {
                    "lv1": {
                        "match_u_list": [],
                        "external_match_list": ["⿰鼠⿱㕣口"],
                    }
                },
            }
        ),
    )
    assert resolution.resolved_ids == "⿰鼠⿱㕣口"


def test_rejects_ids_that_resolve_directly_to_unicode() -> None:
    with pytest.raises(ValueError, match="Unicode supplement mode"):
        fetch_resolution(
            "⿰兌攵",
            opener(
                {
                    "⿰兌攵": {
                        "lv1": {"match_u_list": ["敚"]},
                    }
                }
            ),
        )


def test_fetches_encoded_character_and_decompositions() -> None:
    resolution = fetch_encoded_resolution(
        "𬘄",
        opener(
            {
                "font": {"𬘄": "M 0,0|M 1,1"},
                "𬘄": {
                    "lv1": {
                        "ids_list": ["⿲糹叀糹", "⿰𦁆糸"],
                    }
                },
            }
        ),
    )
    assert resolution.character == "𬘄"
    assert resolution.decompositions == ("⿲糹叀糹", "⿰𦁆糸")
    assert [path["d"] for path in resolution.paths] == ["M 0,0", "M 1,1"]


def test_encoded_character_requires_its_own_outline() -> None:
    with pytest.raises(ValueError, match="no SVG outline"):
        fetch_encoded_resolution(
            "𬘄",
            opener({"font": {"𦁆": "M 0,0"}, "𬘄": {"lv1": {}}}),
        )


def test_encoded_character_ignores_non_ids_zi_tools_labels() -> None:
    resolution = fetch_encoded_resolution(
        "一",
        opener(
            {
                "font": {"一": "M 0,0"},
                "一": {
                    "lv1": {
                        "ids_list": ["#(H)", "⿱一一", "⿱一一"],
                    }
                },
            }
        ),
    )
    assert resolution.decompositions == ("⿱一一",)
