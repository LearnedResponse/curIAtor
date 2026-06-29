"""cohort_explorer.py — a third demo app with an interactive control.

A small interactive Dash app (a slider that changes the view) so the gallery shows that
CurIAtor mounts stateful, callback-driven apps — not just static figures.
"""
from __future__ import annotations

import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go

WEEKS = list(range(1, 13))


def _retention(start: int) -> list[float]:
    # toy decay curve; `start` shifts the initial cohort size
    return [round(start * (0.82 ** w), 1) for w in WEEKS]


def build_app() -> dash.Dash:
    app = dash.Dash(__name__)
    app.title = "Cohort explorer"
    app.layout = html.Div(
        style={"fontFamily": "system-ui, sans-serif", "margin": "12px 20px"},
        children=[
            html.H3("Cohort explorer"),
            html.Label("starting cohort size", style={"fontSize": "13px", "color": "#555"}),
            dcc.Slider(id="start", min=100, max=1000, step=100, value=500,
                       marks={i: str(i) for i in range(100, 1001, 300)}),
            dcc.Graph(id="curve", config={"displayModeBar": False}),
        ],
    )

    @app.callback(Output("curve", "figure"), Input("start", "value"))
    def _update(start):
        fig = go.Figure(go.Scatter(x=WEEKS, y=_retention(start), mode="lines+markers",
                                   line=dict(color="#177755")))
        fig.update_layout(title=f"Weekly retention (start = {start})",
                          xaxis_title="week", yaxis_title="active users",
                          margin=dict(l=60, r=20, t=40, b=40), plot_bgcolor="white", height=420)
        return fig

    return app


app = build_app()

if __name__ == "__main__":
    app.run(debug=False, port=8203)
