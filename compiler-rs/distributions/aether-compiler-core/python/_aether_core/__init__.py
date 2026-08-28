"""Compatibility import for the private native binding.

Productive callers should use :mod:`aether_compiler_core`.
"""

from aether_compiler_core._aether_core import *  # noqa: F403
from aether_compiler_core._aether_core import __version__
