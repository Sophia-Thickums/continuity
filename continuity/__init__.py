"""
continuity — does your agent stay itself?

A small, dependency-free test suite for the layer almost nobody instruments:
continuity of a long-running agent across sessions, windows, restarts and gaps.

Every check here came out of a real failure that shipped silently:

  * a two-second window boundary that read as a night, because nothing measured the gap
  * a memory file carrying a whole duplicated block while every check read green
  * an agenda pointing at a path that had not existed for weeks
  * a registry row contradicting the file next to it, for a month
  * a monitor reporting "quiet" because it could not see the thing it monitored

The checks are deliberately boring. That is the point: the interesting failures are
the ones that look like nothing happened.

Quick start:
    python3 -m continuity demo      # run against generated fixtures, zero setup
    python3 -m continuity check continuity.toml
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
