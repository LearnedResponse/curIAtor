#!/usr/bin/env python3
"""Render the paper's feedback-loop figure from the repo-native Mermaid source."""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "feedback-loop.mmd"
DEFAULT_OUTPUT = HERE / "feedback-loop.png"
W, H = 2600, 980

BG = "#f8fafc"
INK = "#111827"
MUTED = "#64748b"
LINE = "#94a3b8"
PURPLE = "#8e44ad"
BLUE = "#2563eb"
GREEN = "#1f9d55"
ORANGE = "#db8a00"


@dataclass(frozen=True)
class Node:
    key: str
    label: str
    database: bool = False


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/liberation-fonts/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/liberation-fonts/LiberationSans-Regular.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


F = {
    "title": font(40, True),
    "label": font(24, True),
    "small": font(22),
}


def parse_mermaid(source: Path) -> tuple[dict[str, Node], list[tuple[str, str]]]:
    nodes: dict[str, Node] = {}
    edges: list[tuple[str, str]] = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("flowchart"):
            continue
        if "-->" in line:
            left, right = [part.strip() for part in line.split("-->", 1)]
            edges.append((left, right))
            continue
        db = re.match(r'^(\w+)\[\("(.+)"\)\]$', line)
        box = re.match(r'^(\w+)\["(.+)"\]$', line)
        if db:
            key, label = db.groups()
            nodes[key] = Node(key, _clean_label(label), database=True)
        elif box:
            key, label = box.groups()
            nodes[key] = Node(key, _clean_label(label))
    return nodes, edges


def _clean_label(value: str) -> str:
    return value.replace("<br/>", "\n").replace("<br>", "\n")


def text_size(draw: ImageDraw.ImageDraw, value: str, style: str = "label") -> tuple[int, int]:
    box = draw.textbbox((0, 0), value, font=F[style])
    return box[2] - box[0], box[3] - box[1]


def wrap_words(draw: ImageDraw.ImageDraw, value: str, max_width: int, style: str = "label") -> list[str]:
    lines: list[str] = []
    for raw in value.splitlines():
        words = raw.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if text_size(draw, candidate, style)[0] <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    value: str,
    *,
    width: int,
    fill: str,
    style: str = "label",
    leading: int = 34,
) -> None:
    for idx, line in enumerate(wrap_words(draw, value, width, style)):
        tw, _ = text_size(draw, line, style)
        draw.text((cx - tw // 2, y + idx * leading), line, fill=fill, font=F[style])


def node_box(center: tuple[int, int]) -> tuple[int, int, int, int]:
    cx, cy = center
    return cx - 135, cy - 82, cx + 135, cy + 82


def draw_node(draw: ImageDraw.ImageDraw, node: Node, center: tuple[int, int], fill: str) -> None:
    x0, y0, x1, y1 = node_box(center)
    if node.database:
        draw.rounded_rectangle((x0, y0 + 12, x1, y1 - 8), radius=20, fill=fill, outline=LINE, width=3)
        draw.ellipse((x0, y0, x1, y0 + 32), fill=fill, outline=LINE, width=3)
        draw.arc((x0, y1 - 34, x1, y1 - 2), 0, 180, fill=LINE, width=3)
    else:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=fill, outline=LINE, width=3)
    lines = wrap_words(draw, node.label, x1 - x0 - 32)
    line_height = text_size(draw, "Ag", "label")[1]
    leading = 31
    total_height = line_height + max(0, len(lines) - 1) * leading
    y = y0 + ((y1 - y0) - total_height) // 2
    for idx, line in enumerate(lines):
        tw, _ = text_size(draw, line, "label")
        draw.text((center[0] - tw // 2, y + idx * leading), line, fill=INK, font=F["label"])


def line_edge(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], color: str = "#475569") -> None:
    for p0, p1 in zip(points, points[1:]):
        draw.line((*p0, *p1), fill=color, width=5)
    draw_arrowhead(draw, points[-2], points[-1], color)


def draw_arrowhead(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str) -> None:
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 22
    spread = math.radians(28)
    p1 = (
        end[0] - length * math.cos(angle - spread),
        end[1] - length * math.sin(angle - spread),
    )
    p2 = (
        end[0] - length * math.cos(angle + spread),
        end[1] - length * math.sin(angle + spread),
    )
    draw.polygon([end, p1, p2], fill=color)


def anchor(center: tuple[int, int], side: str) -> tuple[int, int]:
    x0, y0, x1, y1 = node_box(center)
    if side == "left":
        return x0, (y0 + y1) // 2
    if side == "right":
        return x1, (y0 + y1) // 2
    if side == "top":
        return (x0 + x1) // 2, y0
    if side == "bottom":
        return (x0 + x1) // 2, y1
    raise ValueError(side)


LAYOUT = {
    "reviewer": (190, 275),
    "app": (510, 275),
    "feedback": (830, 275),
    "ledger": (1150, 275),
    "task": (1470, 275),
    "adapter": (1790, 275),
    "source": (2110, 275),
    "smoke": (2430, 275),
    "reload": (510, 700),
    "reply": (1150, 700),
    "git": (1470, 700),
}

FILLS = {
    "reviewer": "#f3e8ff",
    "app": "#dbeafe",
    "feedback": "#ffedd5",
    "ledger": "#dcfce7",
    "task": "#eef2ff",
    "adapter": "#e0f2fe",
    "source": "#fef9c3",
    "smoke": "#dcfce7",
    "reload": "#dbeafe",
    "reply": "#e0f2fe",
    "git": "#f3e8ff",
}

ROUTES = {
    ("reviewer", "app"): ("right", "left"),
    ("app", "feedback"): ("right", "left"),
    ("feedback", "ledger"): ("right", "left"),
    ("ledger", "task"): ("right", "left"),
    ("task", "adapter"): ("right", "left"),
    ("adapter", "source"): ("right", "left"),
    ("source", "smoke"): ("right", "left"),
    ("reload", "app"): ("top", "bottom"),
    ("reply", "ledger"): ("top", "bottom"),
    ("git", "task"): ("top", "bottom"),
}


def route_points(edge: tuple[str, str]) -> list[tuple[int, int]]:
    src, dst = edge
    if edge in ROUTES:
        src_side, dst_side = ROUTES[edge]
        return [anchor(LAYOUT[src], src_side), anchor(LAYOUT[dst], dst_side)]
    if edge == ("smoke", "reload"):
        start = anchor(LAYOUT[src], "bottom")
        end = anchor(LAYOUT[dst], "right")
        return [start, (start[0], 500), (end[0] + 42, 500), (end[0] + 42, end[1]), end]
    if edge == ("smoke", "reply"):
        start = anchor(LAYOUT[src], "bottom")
        end = anchor(LAYOUT[dst], "right")
        return [start, (start[0], 560), (end[0] + 42, 560), (end[0] + 42, end[1]), end]
    if edge == ("smoke", "git"):
        start = anchor(LAYOUT[src], "bottom")
        end = anchor(LAYOUT[dst], "right")
        return [start, (start[0], 620), (end[0] + 42, 620), (end[0] + 42, end[1]), end]
    return [anchor(LAYOUT[src], "right"), anchor(LAYOUT[dst], "left")]


def render(source: Path, output: Path) -> None:
    nodes, edges = parse_mermaid(source)
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.text((64, 54), "Feedback to fix loop", fill=INK, font=F["title"])
    draw.text(
        (64, 106),
        "Source: docs/paper/figures/feedback-loop.mmd",
        fill=MUTED,
        font=F["small"],
    )
    draw.rounded_rectangle((44, 154, W - 44, H - 54), radius=28, fill="#ffffff", outline="#dbe3ef", width=3)
    for edge in edges:
        if edge[0] in LAYOUT and edge[1] in LAYOUT:
            line_edge(draw, route_points(edge), BLUE if edge[0] == "smoke" else "#475569")
    for key, center in LAYOUT.items():
        node = nodes.get(key)
        if node:
            draw_node(draw, node, center, FILLS.get(key, "#ffffff"))
    draw.text((74, H - 116), "Main path", fill="#475569", font=F["small"])
    draw.line((190, H - 104, 275, H - 104), fill="#475569", width=5)
    draw_arrowhead(draw, (245, H - 104), (275, H - 104), "#475569")
    draw.text((330, H - 116), "Post-smoke side effects: reload, reply trace, git memory", fill=BLUE, font=F["small"])
    draw.line((925, H - 104, 1010, H - 104), fill=BLUE, width=5)
    draw_arrowhead(draw, (980, H - 104), (1010, H - 104), BLUE)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"wrote {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
