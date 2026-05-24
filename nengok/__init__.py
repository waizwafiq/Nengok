"""
Nengok — the autonomous quality agent for Arize Phoenix.

Phoenix shows you what's wrong. Nengok fixes it.

Nengok is a pip-installable SDK that connects to your existing Phoenix
instance, samples production traces, clusters silent failure patterns,
generates regression tests from real failures, runs controlled
experiments, and presents verified fixes for human approval — all
without trace data ever leaving your infrastructure.
"""

from nengok.__version__ import __version__

__all__ = ["__version__"]
