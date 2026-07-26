"""Plotly chart builders — readable dark-theme line charts."""
from __future__ import annotations

import plotly.graph_objects as go

# High-contrast dark dashboard palette
_DARK = dict(
    paper="#161b26",
    plot="#111620",
    grid="#3a4556",
    text="#f1f5f9",
    muted="#94a3b8",
    accent="#60a5fa",
    accent_soft="rgba(96, 165, 250, 0.28)",
)

_PALETTE = [
    "#60a5fa",  # blue
    "#34d399",  # emerald
    "#fbbf24",  # amber
    "#c084fc",  # violet
    "#fb7185",  # rose
    "#22d3ee",  # cyan
]

_MAX_DISPLAY = 120
_MARKER_MAX = 40
_ROLLING_WINDOW = 12

_BASE_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor=_DARK["paper"],
    plot_bgcolor=_DARK["plot"],
    font=dict(color=_DARK["text"], size=13, family="Inter, Segoe UI, sans-serif"),
    margin=dict(l=56, r=20, t=56, b=56),
    height=400,
    hovermode="x unified",
    hoverlabel=dict(bgcolor="#1e293b", font_size=13, font_color=_DARK["text"], bordercolor="#475569"),
)

_AXIS = dict(
    showgrid=True,
    gridwidth=1,
    gridcolor=_DARK["grid"],
    zeroline=False,
    tickfont=dict(size=11, color=_DARK["muted"]),
    linecolor="#475569",
    mirror=False,
)


def _downsample(xs: list, ys: list, max_pts: int = _MAX_DISPLAY) -> tuple[list, list]:
    n = len(xs)
    if n <= max_pts:
        return xs, ys
    step = max(1, n // max_pts)
    return xs[::step], ys[::step]


def _rolling_mean(values: list[float], window: int = _ROLLING_WINDOW) -> list[float]:
    if len(values) <= 1:
        return values
    w = max(2, min(window, len(values) // 4 or 2))
    out: list[float] = []
    for i in range(len(values)):
        chunk = values[max(0, i - w + 1) : i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def _line_trace(
    xs: list,
    ys: list,
    *,
    name: str,
    color: str,
    n: int,
    emphasis: bool = False,
    faint: bool = False,
) -> go.Scatter:
    if faint:
        return go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            name=name,
            line=dict(width=1.2, color=color, shape="linear"),
            connectgaps=True,
            opacity=0.45,
        )
    use_markers = n <= _MARKER_MAX and not emphasis
    mode = "lines+markers" if use_markers else "lines"
    line_shape = "spline" if n <= 24 and not emphasis else "linear"
    width = 3.4 if emphasis else (2.8 if n <= _MARKER_MAX else 2.4)
    marker = None
    if use_markers:
        marker = dict(size=8, color=color, line=dict(width=1.5, color=_DARK["plot"]))
    return go.Scatter(
        x=xs,
        y=ys,
        mode=mode,
        name=name,
        line=dict(width=width, color=color, shape=line_shape),
        marker=marker,
        connectgaps=True,
    )


def _apply_axes(fig: go.Figure, *, x_title: str | None, y_title: str | None, n: int, xs: list) -> None:
    xaxis = {**_AXIS}
    yaxis = {**_AXIS}
    if x_title:
        xaxis["title"] = dict(text=x_title, font=dict(size=12, color=_DARK["muted"]))
    if y_title:
        yaxis["title"] = dict(text=y_title, font=dict(size=12, color=_DARK["muted"]))
        yaxis["tickformat"] = ".3f"
    if xs and isinstance(xs[0], (int, float)) and not isinstance(xs[0], bool):
        tick = max(1, len(xs) // 8)
        xaxis["tickmode"] = "linear"
        xaxis["dtick"] = tick
    fig.update_xaxes(**xaxis)
    fig.update_yaxes(**yaxis)


def _title_block(title: str, n: int) -> dict:
    subtitle = f"{n} points" if n else "no data yet"
    return dict(
        text=f"{title}<br><sup style='color:#94a3b8;font-size:11px'>{subtitle}</sup>",
        font=dict(size=15, color=_DARK["text"]),
        x=0,
        xanchor="left",
    )


def plot_chart(
    title: str,
    xs: list,
    ys: list,
    *,
    name: str | None = None,
    x_title: str | None = None,
    y_title: str | None = None,
    trajectory: bool = False,
) -> go.Figure:
    n = len(xs)
    fig = go.Figure()
    label = name or title

    if not xs or not ys:
        fig.update_layout(title=_title_block(title, 0), **_BASE_LAYOUT)
        fig.add_annotation(
            text="No data yet — run a cycle to populate",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=13, color=_DARK["muted"]),
        )
        return fig

    if trajectory and n > _MARKER_MAX:
        dx, dy = _downsample(xs, ys)
        fig.add_trace(
            _line_trace(dx, dy, name="raw scores", color=_DARK["accent"], n=len(dx), faint=True)
        )
        trend_y = _rolling_mean([float(y) for y in dy])
        fig.add_trace(
            _line_trace(
                dx, trend_y,
                name=f"trend ({min(_ROLLING_WINDOW, len(dy))}-pt avg)",
                color="#fbbf24",
                n=len(dx),
                emphasis=True,
            )
        )
        display_n = len(dx)
    else:
        dx, dy = _downsample(xs, ys) if n > _MAX_DISPLAY else (xs, ys)
        fig.add_trace(_line_trace(dx, dy, name=label, color=_DARK["accent"], n=len(dx)))
        display_n = len(dx)

    fig.update_layout(title=_title_block(title, display_n), **_BASE_LAYOUT)
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    _apply_axes(fig, x_title=x_title, y_title=y_title, n=display_n, xs=dx)

    unique_y = {round(float(y), 5) for y in ys if y is not None}
    if len(unique_y) <= 1 and len(ys) > 1:
        fig.add_annotation(
            text="Flat series — waiting for more variation",
            xref="paper", yref="paper", x=0.5, y=0.85, showarrow=False,
            font=dict(size=11, color=_DARK["muted"]),
        )
    return fig


def multi_plot_chart(
    title: str,
    series: list[tuple[str, list, list]],
    *,
    x_title: str | None = None,
    y_title: str | None = None,
) -> go.Figure:
    fig = go.Figure()
    if not series or not series[0][1]:
        fig.update_layout(title=_title_block(title, 0), **_BASE_LAYOUT)
        fig.add_annotation(
            text="No data yet — run a cycle to populate",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=13, color=_DARK["muted"]),
        )
        return fig

    n_raw = len(series[0][1])
    if n_raw > _MAX_DISPLAY:
        step = max(1, n_raw // _MAX_DISPLAY)
        idx = list(range(0, n_raw, step))
        series = [
            (name, [xs[i] for i in idx], [ys[i] for i in idx])
            for name, xs, ys in series
        ]
    for i, (name, xs, ys) in enumerate(series):
        color = _PALETTE[i % len(_PALETTE)]
        fig.add_trace(_line_trace(xs, ys, name=name, color=color, n=len(xs)))

    fig.update_layout(title=_title_block(title, n_raw), **_BASE_LAYOUT)
    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.04,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11, color=_DARK["text"]),
        ),
    )
    _apply_axes(fig, x_title=x_title, y_title=y_title, n=n_raw, xs=series[0][1])
    return fig


def line_chart(title: str, xs: list, ys: list) -> go.Figure:
    return plot_chart(title, xs, ys)


def bar_chart(title: str, labels: list, values: list) -> go.Figure:
    return plot_chart(title, labels, values)
