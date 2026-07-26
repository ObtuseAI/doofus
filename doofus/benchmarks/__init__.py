"""Held-out benchmark suite.

A fixed, versioned set of tasks the evolution loops never see during
optimization, so self-improvement claims carry verifiable evidence rather than
self-reported fitness. See docs/benchmarks/HELDOUT_BENCHMARKS.md.
"""
from doofus.benchmarks.report_schema import SUITE_VERSION
from doofus.benchmarks.runner import run_suite

__all__ = ["run_suite", "SUITE_VERSION"]
