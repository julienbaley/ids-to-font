import importlib.util
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "generate_lacuna_comparison.py"
)
SPEC = importlib.util.spec_from_file_location("lacuna_comparison", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

BABELSTONE_OVERRIDES = MODULE.BABELSTONE_OVERRIDES
FontContour = MODULE.FontContour
babelstone_paths = MODULE.babelstone_paths
fit_transform = MODULE.fit_transform


def test_uses_all_four_contextual_ze_contours_from_ze() -> None:
    assert BABELSTONE_OVERRIDES["⿰□睪"] == {
        "character": "澤",
        "contours": (3, 4, 5, 6),
    }


def test_keeps_retained_contours_in_one_compound_path() -> None:
    contours = [
        FontContour(f"M{i} 0H10V10Z", (i, 0, 10, 10))
        for i in range(4)
    ]
    svg = babelstone_paths(contours, (1, 0, 0))

    assert svg.count("<path") == 1
    assert svg.count("M") == 4
    assert "mask" not in svg


def test_places_complete_zai_outline_in_upper_allocation() -> None:
    override = BABELSTONE_OVERRIDES["⿱甾□"]
    assert override == {
        "character": "甾",
        "contours": tuple(range(8)),
        "target": (4, 4, 91, 61),
        "region": (4, 64, 91, 91),
    }

    bounds = (127, -89, 896.0625, 859.1)
    scale, x_offset, y_offset = fit_transform(bounds, override["target"])
    left = bounds[0] * scale + x_offset
    top = -bounds[3] * scale + y_offset
    right = bounds[2] * scale + x_offset
    bottom = -bounds[1] * scale + y_offset

    assert 4 <= left < right <= 91
    assert 4 <= top < bottom <= 61
    assert bottom < override["region"][1]
