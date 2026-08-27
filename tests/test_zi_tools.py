import json
from pathlib import Path

import pytest

from ids_to_font import zi_tools
from ids_to_font.zi_tools import (
    SvgResolution,
    ZiToolsClient,
    fetch_encoded_resolution,
    fetch_resolution,
)


class Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RawResponse(Response):
    def read(self) -> bytes:
        return self.payload


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


def test_fetches_kage_stroke_program() -> None:
    resolution = fetch_resolution(
        "⿰丯戈",
        opener(
            {
                "⿰丯戈": {
                    "lv1": {"match_u_list": []},
                    "svg": "M 0,0",
                    "kage": "1:0:0:10:10:20:20$1:0:0:30:30:40:40",
                }
            }
        ),
    )

    assert resolution.kage == (
        "1:0:0:10:10:20:20",
        "1:0:0:30:30:40:40",
    )


def test_preserves_positional_metadata_argument() -> None:
    resolution = SvgResolution(
        "ids",
        "ids",
        "0 0 95 95",
        (),
        {"source": "custom"},
    )

    assert resolution.metadata == {"source": "custom"}
    assert resolution.kage == ()


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


def cached_payload(value: str) -> dict:
    return {
        "font": {value: "M 0,0"},
        value: {
            "lv1": {"match_u_list": [], "ids_list": ["⿱一一"]},
            "svg": "M 0,0",
            "kage": "1:0:0:0:0:10:10",
        },
    }


def test_client_caches_successful_lookup(tmp_path: Path) -> None:
    calls = []

    def counting_opener(*args, **kwargs):
        calls.append(args[0])
        return Response(cached_payload("⿰丯戈"))

    client = ZiToolsClient(tmp_path, delay=0, opener=counting_opener)
    first = client.fetch_resolution("⿰丯戈")
    second = client.fetch_resolution("⿰丯戈")

    assert first == second
    assert len(calls) == 1
    record = json.loads(client.cache_path("⿰丯戈").read_text(encoding="utf-8"))
    assert record["lookup_value"] == "⿰丯戈"
    assert record["endpoint"] == zi_tools.LOOKUP_URL
    assert record["retrieved_at"]


def test_ids_and_encoded_requests_share_cache(tmp_path: Path) -> None:
    payloads = {
        "⿰丯戈": cached_payload("⿰丯戈"),
        "𬘄": cached_payload("𬘄"),
    }
    calls = []

    def routed_opener(url, **kwargs):
        value = "𬘄" if "%F0%AC%98%84" in url else "⿰丯戈"
        calls.append(value)
        return Response(payloads[value])

    first = ZiToolsClient(tmp_path, delay=0, opener=routed_opener)
    first.fetch_resolution("⿰丯戈")
    first.fetch_encoded_resolution("𬘄")
    second = ZiToolsClient(
        tmp_path,
        delay=0,
        opener=lambda *args, **kwargs: pytest.fail("cache miss"),
    )

    second.fetch_resolution("⿰丯戈")
    second.fetch_encoded_resolution("𬘄")
    assert calls == ["⿰丯戈", "𬘄"]


def test_lacuna_proxy_lookup_uses_same_cache(tmp_path: Path) -> None:
    client = ZiToolsClient(
        tmp_path,
        delay=0,
        opener=opener(cached_payload("⿳巛田巿")),
    )
    client.fetch_resolution("⿳巛田巿")

    cached = ZiToolsClient(
        tmp_path,
        delay=0,
        opener=lambda *args, **kwargs: pytest.fail("cache miss"),
    )
    assert cached.fetch_resolution("⿳巛田巿").kage


def test_corrupt_cache_entry_fails_clearly(tmp_path: Path) -> None:
    client = ZiToolsClient(tmp_path, delay=0, opener=opener({}))
    client.cache_path("⿰丯戈").parent.mkdir(parents=True, exist_ok=True)
    client.cache_path("⿰丯戈").write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt Zi.tools cache entry"):
        client.fetch_resolution("⿰丯戈")


def test_failed_request_is_not_cached(tmp_path: Path) -> None:
    def failing_opener(*args, **kwargs):
        raise OSError("offline")

    client = ZiToolsClient(tmp_path, delay=0, opener=failing_opener)
    with pytest.raises(OSError, match="offline"):
        client.fetch_resolution("⿰丯戈")
    assert not client.cache_path("⿰丯戈").exists()


@pytest.mark.parametrize(
    "response",
    [
        RawResponse(b"{broken"),
        Response({"⿰丯戈": []}),
    ],
)
def test_malformed_or_unsuccessful_response_is_not_cached(
    tmp_path: Path,
    response,
) -> None:
    client = ZiToolsClient(
        tmp_path,
        delay=0,
        opener=lambda *args, **kwargs: response,
    )

    with pytest.raises(ValueError):
        client.fetch_resolution("⿰丯戈")
    assert not client.cache_path("⿰丯戈").exists()


def test_interrupted_atomic_write_leaves_no_entry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = ZiToolsClient(
        tmp_path,
        delay=0,
        opener=opener(cached_payload("⿰丯戈")),
    )
    monkeypatch.setattr(
        zi_tools.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("interrupted")),
    )

    with pytest.raises(OSError, match="interrupted"):
        client.fetch_resolution("⿰丯戈")
    assert list(tmp_path.iterdir()) == []


def test_delay_applies_only_between_network_requests(tmp_path: Path) -> None:
    sleeps = []
    client = ZiToolsClient(
        tmp_path,
        delay=3,
        opener=lambda url, **kwargs: Response(
            cached_payload("乙" if "%E4%B9%99" in url else "甲")
        ),
        sleeper=sleeps.append,
    )

    client.fetch_resolution("甲")
    client.fetch_resolution("甲")
    client.fetch_resolution("乙")
    assert sleeps == [3]


def test_refresh_replaces_cache_entry(tmp_path: Path) -> None:
    initial = ZiToolsClient(
        tmp_path,
        delay=0,
        opener=opener(cached_payload("甲")),
    )
    initial.fetch_resolution("甲")
    refreshed_payload = cached_payload("甲")
    refreshed_payload["甲"]["svg"] = "M 9,9"
    refreshed = ZiToolsClient(
        tmp_path,
        refresh_cache=True,
        delay=0,
        opener=opener(refreshed_payload),
    )

    assert refreshed.fetch_resolution("甲").paths[0]["d"] == "M 9,9"
    assert (
        ZiToolsClient(
            tmp_path,
            delay=0,
            opener=lambda *args, **kwargs: pytest.fail("cache miss"),
        )
        .fetch_resolution("甲")
        .paths[0]["d"]
        == "M 9,9"
    )


def test_cache_keys_distinguish_exact_values(tmp_path: Path) -> None:
    client = ZiToolsClient(tmp_path, delay=0, opener=opener({}))

    assert client.cache_path("甲") != client.cache_path("乙")
    assert client.cache_path("⿰甲乙") != client.cache_path("⿰乙甲")
