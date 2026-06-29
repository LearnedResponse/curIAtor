"""sales_overview.py — a second demo app (clean, so the gallery isn't all broken).

A simple, reasonably-polished Dash app — gives the gallery a "normal" entry alongside the
deliberately-broken `aviato`. Feel free to plant a subtle flaw here too if you want a second
demo beat.
"""
from __future__ import annotations

import dash
from dash import dcc, html
import plotly.graph_objects as go

REGIONS = ["North", "South", "East", "West"]
Q3 = [120, 98, 143, 87]


def _figure() -> go.Figure:
    fig = go.Figure(go.Bar(x=REGIONS, y=Q3, marker_color="#1f6fc0"))
    fig.update_layout(
        title="Q3 sales by region ($k)",
        xaxis_title="region",
        yaxis_title="sales ($k)",
        margin=dict(l=60, r=20, t=40, b=40),
        plot_bgcolor="white",
        height=420,
    )
    return fig


def build_app() -> dash.Dash:
    app = dash.Dash(__name__)
    app.title = "Sales overview"
    app.layout = html.Div(
        style={"fontFamily": "system-ui, sans-serif", "margin": "12px 20px"},
        children=[
            html.H3("Sales overview"),
            dcc.Graph(figure=_figure(), config={"displayModeBar": False}),
        ],
    )
    return app


app = build_app()

if __name__ == "__main__":
    app.run(debug=False, port=8202)
