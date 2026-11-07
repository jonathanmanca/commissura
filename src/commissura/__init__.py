"""Build standardised, de-identified, research-ready clinical datasets.

The package is both a command-line tool and an importable library. Public entry
points live in the submodules; this module exposes only the version.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("commissura")
except PackageNotFoundError:  # pragma: no cover - only hit when running from a bare checkout
    # The distribution is not installed (e.g. the source tree is on sys.path
    # directly). Reporting a sentinel is better than crashing on import.
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
