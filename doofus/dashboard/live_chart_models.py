"""Chart payload models."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class LineSeries:
    title: str
    xs: list
    ys: list
    empty_label: str = "No data yet"

@dataclass
class BarSeries:
    title: str
    labels: list
    values: list
    empty_label: str = "No data yet"

@dataclass
class ChartBundle:
    classification: str = "DOOFUS_LIVE_CHART_BUNDLE"
    lines: list[LineSeries] = field(default_factory=list)
    bars: list[BarSeries] = field(default_factory=list)

def empty_line(title: str) -> LineSeries:
    return LineSeries(title=title, xs=[], ys=[])

def empty_bar(title: str) -> BarSeries:
    return BarSeries(title=title, labels=[], values=[])
