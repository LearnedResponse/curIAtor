#!/usr/bin/env python3
"""Render the OT/HMI before-after paper figure from committed collection states."""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GALLERY = ROOT / "galleries" / "curiator-ot"
DEFAULT_OUTPUT = Path(__file__).resolve().with_name("ot-rainbow-before-after.png")
BEFORE_REF = "6c5e2d6"
AFTER_REF = "36e21cf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
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


FONTS = {
    "title": font(28, True),
    "subtitle": font(17),
    "h": font(18, True),
    "body": font(15),
    "small": font(12),
    "metric": font(26, True),
}


def extract_ref(gallery: Path, ref: str, dest: Path) -> None:
    archive = subprocess.run(
        ["git", "-C", str(gallery), "archive", ref],
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(["tar", "-x", "-C", str(dest)], check=True, input=archive.stdout)


def generate_rows(root: Path, samples: int) -> list[dict]:
    subprocess.run(["python", "sim/process.py", "--samples", str(samples)], cwd=root, check=True)
    db = root / "data" / "historian.sqlite"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("select * from samples order by t").fetchall()
    finally:
        con.close()
    return [dict(row) for row in rows]


def rect(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], fill: str, outline: str | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(xy, radius=8, fill=fill, outline=outline, width=width)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fill: str, style: str = "body") -> None:
    draw.text(xy, value, fill=fill, font=FONTS[style])


def draw_metric(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], label: str, value: str, detail: str, fill: str, fg: str, accent: str | None = None) -> None:
    rect(draw, xy, fill, outline="#cbd5e1" if fill == "#ffffff" else None)
    x0, y0, _x1, _y1 = xy
    if accent:
        draw.rounded_rectangle((x0, y0, x0 + 10, xy[3]), radius=8, fill=accent)
    text(draw, (x0 + 18, y0 + 12), label.upper(), fg, "small")
    text(draw, (x0 + 18, y0 + 32), value, fg, "metric")
    text(draw, (x0 + 18, y0 + 66), detail, fg, "small")


def scale_points(rows: list[dict], field: str, box: tuple[int, int, int, int], lo: float, hi: float) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = box
    span = max(1, len(rows) - 1)
    out = []
    for idx, row in enumerate(rows):
        x = x0 + round((x1 - x0) * idx / span)
        y = y1 - round((y1 - y0) * (float(row[field]) - lo) / max(1e-9, hi - lo))
        out.append((x, max(y0, min(y1, y))))
    return out


def draw_trend(draw: ImageDraw.ImageDraw, rows: list[dict], box: tuple[int, int, int, int], mode: str) -> None:
    x0, y0, x1, y1 = box
    fill = "#111827" if mode == "before" else "#ffffff"
    fg = "#ffffff" if mode == "before" else "#334155"
    rect(draw, (x0 - 10, y0 - 40, x1 + 10, y1 + 28), fill, outline="#334155" if mode == "before" else "#cbd5e1")
    text(draw, (x0, y0 - 30), "Trend", fg, "h")
    for frac in (0.25, 0.5, 0.75):
        y = y0 + round((y1 - y0) * frac)
        draw.line((x0, y, x1, y), fill="#334155" if mode == "before" else "#e2e8f0", width=1)
    colors = {
        "before": {"level": "#ff00f5", "setpoint": "#00ffff", "flow_in": "#00ff00", "flow_out": "#ffff00"},
        "after": {"level": "#111827", "setpoint": "#64748b", "flow_in": "#cbd5e1", "flow_out": "#94a3b8"},
    }[mode]
    widths = {"level": 4 if mode == "after" else 3, "setpoint": 2, "flow_in": 2 if mode == "before" else 1, "flow_out": 2 if mode == "before" else 1}
    for field, color in colors.items():
        pts = scale_points(rows, field, box, 20, 80)
        draw.line(pts, fill=color, width=widths[field], joint="curve")
    if mode == "after":
        setpoint = rows[-1]["setpoint"]
        for value, color in ((setpoint + 13, "#b91c1c"), (setpoint - 17, "#b45309")):
            y = scale_points([{"level": value}], "level", box, 20, 80)[0][1]
            draw.line((x0, y, x1, y), fill=color, width=2)


def draw_tank(draw: ImageDraw.ImageDraw, row: dict, box: tuple[int, int, int, int], mode: str) -> None:
    x0, y0, x1, y1 = box
    panel = "#7c3aed" if mode == "before" else "#f8fafc"
    rect(draw, (x0 - 10, y0 - 40, x1 + 10, y1 + 28), panel, outline="#cbd5e1" if mode == "after" else None)
    text(draw, (x0, y0 - 30), "Mimic" if mode == "before" else "Level constraints", "#ffffff" if mode == "before" else "#334155", "h")
    tank = (x0 + 90, y0 + 24, x1 - 90, y1 - 16)
    level = float(row["level"])
    fill_top = tank[3] - round((tank[3] - tank[1]) * level / 100)
    if mode == "before":
        draw.rectangle(tank, outline="#ffffff", width=4, fill="#1e40af")
        draw.rectangle((tank[0], fill_top, tank[2], tank[3]), fill="#00ffff")
        text(draw, (tank[0] - 58, tank[1] + 20), "IN", "#00ff00", "h")
        text(draw, (tank[2] + 20, tank[3] - 54), "OUT", "#ff00f5", "h")
        text(draw, (tank[0] + 24, max(tank[1], fill_top - 32)), f"{level:.1f}%", "#ffff00", "h")
    else:
        setpoint = float(row["setpoint"])
        low = setpoint - 8
        high = setpoint + 8
        low_y = tank[3] - round((tank[3] - tank[1]) * low / 100)
        high_y = tank[3] - round((tank[3] - tank[1]) * high / 100)
        sp_y = tank[3] - round((tank[3] - tank[1]) * setpoint / 100)
        draw.rectangle(tank, outline="#334155", width=3, fill="#f1f5f9")
        draw.rectangle((tank[0], high_y, tank[2], low_y), fill="#dbeafe")
        draw.rectangle((tank[0], fill_top, tank[2], tank[3]), fill="#94a3b8")
        draw.line((tank[0] - 12, sp_y, tank[2] + 12, sp_y), fill="#1f2937", width=3)
        text(draw, (tank[2] + 18, sp_y - 10), f"SP {setpoint:.0f}%", "#1f2937", "small")
        text(draw, (tank[0] + 22, max(tank[1], fill_top - 28)), f"{level:.1f}%", "#1f2937", "h")


def draw_alarms(draw: ImageDraw.ImageDraw, row: dict, xy: tuple[int, int], mode: str) -> None:
    x, y = xy
    if mode == "before":
        rect(draw, (x, y, x + 245, y + 300), "#2563eb")
        text(draw, (x + 14, y + 14), "Alarm List", "#ffffff", "h")
        items = [
            ("LOW LEVEL SWITCH CHATTER", bool(row["alarm_low"]), "#00e5ff"),
            ("HI LEVEL", bool(row["alarm_high"]), "#ff0000"),
            ("PUMP STATUS NORMAL", row["pump_status"] == "running", "#00ff00"),
            ("TEMP HIGH", bool(row["alarm_temp_high"]), "#ff7a00"),
        ]
        for idx, (label, active, color) in enumerate(items):
            yy = y + 52 + idx * 54
            rect(draw, (x + 14, yy, x + 230, yy + 42), color if active else "#3b82f6")
            text(draw, (x + 24, yy + 12), label, "#ffffff", "small")
    else:
        rect(draw, (x, y, x + 245, y + 300), "#f8fafc", outline="#cbd5e1")
        text(draw, (x + 14, y + 14), "Alarms / equipment", "#334155", "h")
        rect(draw, (x + 14, y + 52, x + 230, y + 96), "#e2e8f0", outline="#cbd5e1")
        text(draw, (x + 24, y + 66), "No active alarms", "#334155", "body")
        rect(draw, (x + 14, y + 126, x + 230, y + 218), "#ffffff", outline="#cbd5e1")
        text(draw, (x + 24, y + 140), "Pump", "#475569", "small")
        text(draw, (x + 24, y + 160), str(row["pump_status"]).upper(), "#111827", "h")
        text(draw, (x + 24, y + 188), "historian value present", "#64748b", "small")


def draw_panel(draw: ImageDraw.ImageDraw, rows: list[dict], x0: int, title: str, subtitle: str, mode: str) -> None:
    bg = "#101827" if mode == "before" else "#e5e7eb"
    fg = "#ffffff" if mode == "before" else "#1f2937"
    draw.rectangle((x0, 0, x0 + 860, 900), fill=bg)
    text(draw, (x0 + 24, 24), title, fg, "title")
    text(draw, (x0 + 24, 60), subtitle, "#cbd5e1" if mode == "before" else "#475569", "subtitle")
    row = rows[-1]
    if mode == "before":
        metrics = [
            ("level", f"{row['level']:.1f}%", "PV", "#ff00f5"),
            ("setpoint", f"{row['setpoint']:.1f}%", "SP", "#00ffff"),
            ("valve", f"{row['valve_pct']:.0f}%", "inlet valve", "#00ff00"),
            ("temperature", f"{row['temp']:.1f} F", str(row["pump_status"]), "#ff7a00"),
        ]
        for idx, metric in enumerate(metrics):
            x = x0 + 24 + idx * 202
            draw_metric(draw, (x, 104, x + 186, 190), metric[0], metric[1], metric[2], metric[3], "#ffffff")
    else:
        metrics = [
            ("level", f"{row['level']:.1f}%", "PV", None),
            ("setpoint", f"{row['setpoint']:.1f}%", "SP", None),
            ("valve", f"{row['valve_pct']:.0f}%", "inlet valve", None),
            ("temperature", f"{row['temp']:.1f} F", str(row["pump_status"]), None),
            ("historian", "LIVE", "deterministic data", None),
        ]
        for idx, metric in enumerate(metrics):
            x = x0 + 24 + idx * 160
            draw_metric(draw, (x, 104, x + 146, 190), metric[0], metric[1], metric[2], "#ffffff", "#111827", "#64748b")
    draw_trend(draw, rows[-300:], (x0 + 34, 260, x0 + 490, 530), mode)
    draw_tank(draw, row, (x0 + 548, 260, x0 + 780, 530), mode)
    draw_alarms(draw, row, (x0 + 584, 570), mode)
    if mode == "after":
        rect(draw, (x0 + 24, 570, x0 + 550, 658), "#ffffff", outline="#cbd5e1")
        text(draw, (x0 + 42, 588), "Operating state", "#475569", "small")
        text(draw, (x0 + 42, 610), "NORMAL OPERATING RANGE", "#111827", "h")
        text(draw, (x0 + 42, 636), f"Level {row['level']:.1f}% vs SP {row['setpoint']:.0f}% | constraints visible", "#334155", "small")


def render(gallery: Path, before_ref: str, after_ref: str, output: Path, samples: int) -> None:
    with tempfile.TemporaryDirectory(prefix="curiator-ot-figure-") as tmp:
        tmp_path = Path(tmp)
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        extract_ref(gallery, before_ref, before)
        extract_ref(gallery, after_ref, after)
        before_rows = generate_rows(before, samples)
        after_rows = generate_rows(after, samples)
    image = Image.new("RGB", (1720, 900), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw_panel(draw, before_rows, 0, "Before: rainbow mimic", f"{before_ref} seed HMI", "before")
    draw_panel(draw, after_rows, 860, "After: HP-HMI direction", f"{after_ref} after curator loop", "after")
    draw.line((860, 0, 860, 900), fill="#ffffff", width=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"wrote {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gallery", type=Path, default=DEFAULT_GALLERY)
    parser.add_argument("--before-ref", default=BEFORE_REF)
    parser.add_argument("--after-ref", default=AFTER_REF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples", type=int, default=900)
    args = parser.parse_args()
    render(args.gallery, args.before_ref, args.after_ref, args.output, args.samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
