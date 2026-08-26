"""Build presentation fonts for Ideographic Description Sequences."""

from .builder import BuildResult, build, build_ligature
from .input import read_ids
from .mapping import assign_pua, load_previous_assignments

__all__ = [
    "BuildResult",
    "assign_pua",
    "build",
    "build_ligature",
    "load_previous_assignments",
    "read_ids",
]

__version__ = "0.1.0"
