#!/usr/bin/env python3
"""Render the paper figure for the curIAtor shell feedback panel."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_OUTPUT = Path(__file__).resolve().with_name("shell-feedback-panel.png")
W, H = 1680, 940

BG = "#f7f8fb"
INK = "#20242a"
MUTED = "#6b7280"
LINE = "#d9dee8"
PURPLE = "#8e44ad"
BLUE = "#2980b9"
GREEN = "#1f9d55"
ORANGE = "#db8a00"


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
    "tiny": font(12),
    "small": font(14),
    "body": font(16),
    "body_b": font(16, True),
    "h": font(20, True),
    "title": font(28, True),
    "metric": font(32, True),
}


def text_size(draw: ImageDraw.ImageDraw, value: str, style: str = "body") -> tuple[int, int]:
    box = draw.textbbox((0, 0), value, font=F[style])
    return box[2] - box[0], box[3] - box[1]


def rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    fill: str,
    outline: str = LINE,
    width: int = 1,
    radius: int = 8,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def txt(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fill: str = INK, style: str = "body") -> None:
    draw.text(xy, value, fill=fill, font=F[style])


def wordmark(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.polygon([(x, y + 10), (x + 12, y), (x + 24, y + 10), (x + 12, y + 22)], fill=PURPLE)
    txt(draw, (x + 32, y - 1), "cur", INK, "h")
    txt(draw, (x + 66, y - 1), "IA", PURPLE, "h")
    txt(draw, (x + 91, y - 1), "tor", INK, "h")
    txt(draw, (x + 136, y + 2), "gallery", MUTED, "body")


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, value: str, fill: str, fg: str = "#ffffff") -> int:
    tw, _ = text_size(draw, value, "tiny")
    w = tw + 18
    draw.rounded_rectangle((x, y, x + w, y + 22), radius=11, fill=fill)
    txt(draw, (x + 9, y + 3), value, fg, "tiny")
    return w


def wrap(draw: ImageDraw.ImageDraw, value: str, max_width: int, style: str = "body") -> list[str]:
    lines: list[str] = []
    for raw in value.splitlines() or [""]:
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


def paragraph(draw: ImageDraw.ImageDraw, x: int, y: int, value: str, width: int, fill: str = INK, style: str = "body", leading: int = 22) -> int:
    for line in wrap(draw, value, width, style):
        txt(draw, (x, y), line, fill, style)
        y += leading
    return y


def draw_chart(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    rect(draw, (x, y, x + w, y + h), "#ffffff", "#dfe4ee", radius=8)
    txt(draw, (x + 26, y + 22), "Aviato monthly revenue", INK, "h")
    txt(draw, (x + 26, y + 50), "Live app mounted under /app/aviato", MUTED, "small")
    px, py = x + 70, y + 105
    pw, ph = w - 130, h - 190
    draw.rectangle((px, py, px + pw, py + ph), fill="#ffffff", outline="#edf0f5")
    for frac in (0.25, 0.5, 0.75):
        gy = py + round(ph * frac)
        draw.line((px, gy, px + pw, gy), fill="#edf0f5")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    rev = [42, 62, 49, 72, 82, 92, 84, 108]
    cost = [35, 48, 44, 55, 60, 67, 72, 78]
    maxv = 120
    group = pw / len(months)
    for idx, month in enumerate(months):
        gx = px + idx * group + 18
        rh = rev[idx] / maxv * (ph - 24)
        ch = cost[idx] / maxv * (ph - 24)
        draw.rectangle((gx, py + ph - rh, gx + 20, py + ph), fill="#e07b2a")
        draw.rectangle((gx + 25, py + ph - ch, gx + 45, py + ph), fill="#b8d40a")
        txt(draw, (int(gx) - 2, py + ph + 14), month, MUTED, "tiny")
    draw.line((px, py + ph, px + pw, py + ph), fill="#9aa3b2", width=2)
    draw.line((px, py, px, py + ph), fill="#9aa3b2", width=2)
    txt(draw, (x + w // 2 - 30, y + h - 42), "Month", MUTED, "small")
    txt(draw, (x + 26, y + h // 2), "$k", MUTED, "small")
    lx, ly = px + pw - 220, y + 36
    rect(draw, (lx, ly, lx + 190, ly + 42), "#ffffff", "#dfe4ee", radius=16)
    draw.rectangle((lx + 16, ly + 14, lx + 30, ly + 28), fill="#e07b2a")
    txt(draw, (lx + 38, ly + 10), "revenue", INK, "tiny")
    draw.rectangle((lx + 105, ly + 14, lx + 119, ly + 28), fill="#b8d40a")
    txt(draw, (lx + 127, ly + 10), "costs", INK, "tiny")


def draw_thumbnail(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    rect(draw, (x, y, x + w, y + h), "#ffffff", "#dfe4ee", radius=6)
    px, py = x + 16, y + 24
    pw, ph = w - 32, h - 50
    draw.rectangle((px, py, px + pw, py + ph), fill="#fdfdfd", outline="#edf0f5")
    vals = [42, 62, 49, 72, 82, 92, 84, 108]
    group = pw / len(vals)
    for idx, value in enumerate(vals):
        gx = px + idx * group + 7
        rh = value / 120 * (ph - 12)
        draw.rectangle((gx, py + ph - rh, gx + 14, py + ph), fill="#e07b2a")
    draw.rounded_rectangle((px + 105, py + 25, px + 250, py + 70), radius=5, outline=PURPLE, width=4)
    draw.line((px + 72, py + ph + 14, px + 190, py + ph + 14), fill=BLUE, width=4)
    draw.ellipse((px + 184, py + ph + 8, px + 204, py + ph + 28), fill=ORANGE, outline="#ffffff", width=2)
    txt(draw, (px + 191, py + ph + 9), "1", "#ffffff", "tiny")


def draw_thread_entry(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    *,
    status: str,
    status_color: str,
    author: str,
    comment: str,
    bg: str = "#ffffff",
    accent: str = BLUE,
    indent: int = 0,
) -> int:
    left = x + indent
    rect(draw, (left, y, x + w, y + 110), bg, bg, radius=4)
    draw.rectangle((left, y, left + 4, y + 110), fill=accent)
    badge_w = pill(draw, left + 14, y + 14, status, status_color)
    txt(draw, (left + 24 + badge_w, y + 15), "Jun 30, 12:21 PM", "#9ca3af", "tiny")
    txt(draw, (left + 150 + badge_w, y + 15), author, PURPLE if author.startswith("adam") else BLUE, "tiny")
    paragraph(draw, left + 14, y + 45, comment, w - indent - 32, INK if bg == "#ffffff" else "#34515f", "small", 20)
    return y + 122


def draw_left_rail(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, 290, H), fill="#fcfcfd", outline=LINE)
    wordmark(draw, 18, 26)
    rect(draw, (16, 84, 270, 118), "#ffffff", "#d7dce7", radius=6)
    txt(draw, (30, 92), "search...", "#a4abb8", "small")
    rect(draw, (16, 132, 210, 166), "#ffffff", "#d7dce7", radius=6)
    txt(draw, (30, 140), "sort: activity", INK, "small")
    txt(draw, (226, 139), "on", BLUE, "small")
    rect(draw, (0, 182, 290, 256), "#f6f1fb", "#e0d4ee", radius=0)
    txt(draw, (20, 198), "General", INK, "body_b")
    txt(draw, (20, 224), "gallery feedback - 1 open", MUTED, "tiny")
    pill(draw, 20, 238, "meta", PURPLE)
    txt(draw, (18, 276), "7 apps", MUTED, "small")
    rows = [
        ("8213 - Aviato revenue", "demo - 2 open", ["demo", "broken"], "#f3f0fb"),
        ("8721 - React SSR overview", "proxy", ["react", "node"], "#ffffff"),
        ("8731 - Rust status server", "proxy", ["rust"], "#ffffff"),
        ("8201 - Dash cohorts", "dynamic", ["dash"], "#ffffff"),
    ]
    y = 304
    for title, meta, tags, fill in rows:
        rect(draw, (0, y, 290, y + 82), fill, "#eceff5", radius=0)
        txt(draw, (20, y + 12), title, INK, "body_b" if fill != "#ffffff" else "body")
        txt(draw, (20, y + 38), meta, MUTED, "tiny")
        tx = 20
        for tag in tags:
            tx += pill(draw, tx, y + 56, tag, PURPLE if tag != "broken" else "#e07b2a") + 5
        y += 82


def draw_feedback_panel(draw: ImageDraw.ImageDraw) -> None:
    x = 1320
    draw.rectangle((x, 0, W, H), fill="#fcfcfd", outline=LINE)
    txt(draw, (x + 120, 20), "adam@local", MUTED, "small")
    rect(draw, (x + 248, 14, x + 340, 42), "#ffffff", "#d7dce7", radius=6)
    txt(draw, (x + 264, 20), "Account", INK, "tiny")
    txt(draw, (x + 24, 62), "Feedback", INK, "h")
    txt(draw, (x + 24, 91), "Aviato revenue", MUTED, "small")
    txt(draw, (x + 24, 126), "rating: 5 / 5", ORANGE, "body_b")
    rect(draw, (x + 24, 162, x + 340, 268), "#ffffff", "#d7dce7", radius=6)
    paragraph(draw, x + 40, 182, "axis labels missing, legend covers the chart, clean up the layout", 284, "#5c6470", "small", 21)
    rect(draw, (x + 24, 286, x + 156, 324), "#ffffff", "#d7dce7", radius=6)
    txt(draw, (x + 42, 296), "Capture view", INK, "tiny")
    rect(draw, (x + 170, 286, x + 260, 324), "#ffffff", "#d7dce7", radius=6)
    txt(draw, (x + 192, 296), "upload", INK, "tiny")
    rect(draw, (x + 24, 340, x + 340, 380), GREEN, GREEN, radius=6)
    txt(draw, (x + 118, 350), "Save feedback", "#ffffff", "small")
    txt(draw, (x + 24, 402), "prior feedback", INK, "body_b")
    y = draw_thread_entry(
        draw,
        x + 18,
        430,
        326,
        status="new",
        status_color=ORANGE,
        author="adam@local",
        comment="axis labels missing, legend covers the chart, clean up the layout",
        accent=ORANGE,
    )
    draw_thumbnail(draw, x + 52, y - 10, 254, 120)
    y += 126
    y = draw_thread_entry(
        draw,
        x + 18,
        y,
        326,
        status="working",
        status_color=PURPLE,
        author="Codex",
        comment="Editing examples/dash/aviato.py with screenshot context and the prior thread attached.",
        bg="#eaf5ff",
        accent=BLUE,
        indent=28,
    )
    draw_thread_entry(
        draw,
        x + 18,
        y,
        326,
        status="done",
        status_color=GREEN,
        author="Codex",
        comment="Added axis titles, moved the legend above the chart, widened margins, and smoke-tested.",
        bg="#eaf5ff",
        accent=GREEN,
        indent=28,
    )


def draw_center(draw: ImageDraw.ImageDraw) -> None:
    x0 = 290
    draw.rectangle((x0, 0, 1320, H), fill=BG)
    txt(draw, (x0 + 44, 36), "curIAtor / Aviato", INK, "title")
    txt(draw, (x0 + 44, 76), "same-origin app shell with contextual feedback", MUTED, "body")
    rect(draw, (x0 + 44, 112, 1284, 824), "#ffffff", "#dfe4ee", radius=8)
    draw_chart(draw, x0 + 78, 150, 884, 520)
    rect(draw, (x0 + 78, 700, 962, 780), "#f8fafc", "#dfe4ee", radius=8)
    txt(draw, (x0 + 100, 720), "Thread context sent to the agent", INK, "body_b")
    txt(draw, (x0 + 100, 748), "feedback id, screenshot path, app source, smoke command, prior replies", MUTED, "small")
    rect(draw, (x0 + 704, 700, x0 + 970, 780), "#f8fafc", "#dfe4ee", radius=8)
    txt(draw, (x0 + 726, 720), "Task trace", INK, "body_b")
    txt(draw, (x0 + 726, 748), "capture -> bundle -> edit -> reply", MUTED, "tiny")


def render(output: Path) -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw_left_rail(draw)
    draw_center(draw)
    draw_feedback_panel(draw)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"wrote {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
