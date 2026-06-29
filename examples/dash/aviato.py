"""aviato.py — the headline demo app for CurIAtor. DELIBERATELY BROKEN.

This is the curator's first patient. It has three planted, obvious flaws so the 30-second demo
(docs/DEMO_SCRIPT.md) has something real to fix:
  1. no axis titles (you can't tell what the numbers mean)
  2. the legend sits ON TOP of the data (x=0.4, y=0.9 — inside the plot area)
  3. cramped margins (everything jammed to the edges)

The demo: in the gallery, screenshot + comment "axis labels missing, legend covers the chart,
clean up the layout" → the curator edits THIS file (axis titles, legend outside, wider margins) →
restarts → replies. Don't pre-fix it; being broken is the point.

(Yes, it's named after Erlich Bachman's company. The joke is that this one actually gets fixed.)
"""
from __future__ import annotations

import dash
from dash import dcc, html
import plotly.graph_objects as go

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
REVENUE = [12, 19, 14, 23, 27, 31, 29, 36, 41, 38, 47, 52]   # $k
COSTS = [10, 14, 13, 16, 18, 20, 22, 25, 27, 30, 33, 35]


def _figure() -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=MONTHS, y=REVENUE, name="revenue", marker_color="#e07b2a"))
    fig.add_trace(go.Bar(x=MONTHS, y=COSTS, name="costs", marker_color="#b8d40a"))  # clashing color
    fig.update_layout(
        barmode="group",
        title="Aviato — monthly performance",
        # FLAW 1: no xaxis_title / yaxis_title
        # FLAW 2: legend dumped inside the plot, over the bars
        legend=dict(x=0.4, y=0.9, bgcolor="rgba(255,255,255,0.4)"),
        # FLAW 3: cramped margins
        margin=dict(l=8, r=8, t=30, b=8),
        plot_bgcolor="white",
        height=460,
    )
    return fig


def build_app() -> dash.Dash:
    app = dash.Dash(__name__)
    app.title = "Aviato"
    app.layout = html.Div(
        style={"fontFamily": "system-ui, sans-serif", "margin": "12px 20px"},
        children=[
            html.H3("Aviato — revenue dashboard"),
            html.P("Monthly revenue vs costs. (This app is intentionally rough — leave feedback in "
                   "the gallery and watch the curator fix it.)", style={"color": "#666"}),
            dcc.Graph(figure=_figure(), config={"displayModeBar": False}),
        ],
    )
    return app


# module-level `app` so the shell can mount via either entry pattern (build_app() or app)
app = build_app()

if __name__ == "__main__":
    app.run(debug=False, port=8201)
