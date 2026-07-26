"""Shared live chart helpers — plot/line only, never bar."""
from __future__ import annotations

from doofus.dashboard.dashboard_charts import plot_chart, multi_plot_chart

_X_LABELS = {
    "generation": "Generation",
    "created_at": "Time (recent →)",
    "candidate_id": "Candidate",
    "id": "Event #",
    "rowid": "Candidate #",
    "reason": "Reason",
    "mutation_type": "Mutation type",
    "status": "Status",
    "provider": "Provider",
    "model": "Model",
}

_Y_LABELS = {
    "score_total": "Score",
    "avg_total": "Average score",
    "best_total": "Best score",
    "avg_safety": "Safety",
    "avg_replay": "Replay",
    "avg_generalization": "Generalization",
    "avg_compounding": "Compounding",
    "avg_recursive": "Recursive",
    "score_compounding": "Compounding",
    "score_recursive_learning": "Recursive",
    "score_generalization": "Generalization",
    "score_replay": "Replay",
    "score_safety": "Safety",
    "cumulative": "Cumulative count",
    "count": "Count",
    "cost_est": "Cost (USD)",
    "tokens_est": "Tokens",
    "cumulative_cost": "Cumulative cost",
}


def _x_label(key: str) -> str:
    return _X_LABELS.get(key, key.replace("_", " ").title())


def _y_label(key: str) -> str:
    return _Y_LABELS.get(key, key.replace("_", " ").title())


def _is_trajectory(x_key: str) -> bool:
    return x_key in {"created_at", "rowid"}


def plot_from_rows(
    title: str,
    rows: list,
    x_key: str,
    y_key: str,
    *,
    name: str | None = None,
    trajectory: bool | None = None,
):
    if not rows:
        return plot_chart(title, [], [], name=name, x_title=_x_label(x_key), y_title=_y_label(y_key))
    xs = [r.get(x_key) for r in rows]
    if x_key == "candidate_id":
        xs = [str(x)[:10] for x in xs]
    ys = [float(r.get(y_key) or 0) for r in rows]
    traj = trajectory if trajectory is not None else _is_trajectory(x_key)
    return plot_chart(
        title, xs, ys,
        name=name,
        x_title=_x_label(x_key),
        y_title=_y_label(y_key),
        trajectory=traj,
    )


def plot_multi_from_rows(
    title: str,
    rows: list,
    x_key: str,
    y_keys: list[tuple[str, str]],
    *,
    trajectory: bool | None = None,
):
    if not rows:
        return plot_chart(title, [], [], x_title=_x_label(x_key), y_title="Score")
    xs = [r.get(x_key) for r in rows]
    series = [(label, xs, [float(r.get(k) or 0) for r in rows]) for label, k in y_keys]
    traj = trajectory if trajectory is not None else _is_trajectory(x_key)
    if traj and len(xs) > 40:
        return multi_plot_chart(title, series, x_title=_x_label(x_key), y_title="Score")
    return multi_plot_chart(title, series, x_title=_x_label(x_key), y_title="Score")


line_from_rows = plot_from_rows
bar_from_rows = plot_from_rows


def assert_plot_chart(fig, name: str = "chart") -> None:
    import plotly.graph_objects as go
    for i, trace in enumerate(fig.data):
        if isinstance(trace, go.Bar):
            raise TypeError(f"{name} trace {i} is go.Bar — only plot/line charts allowed")
