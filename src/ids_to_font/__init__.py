"""Build presentation fonts for Ideographic Description Sequences."""

from .builder import BuildResult, build
from .input import read_ids

__all__ = [
    "BuildResult",
    "build",
    "read_ids",
]

__version__ = "0.1.0"
