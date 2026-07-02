"""Render the README launch demo GIF storyboard.

This is a deterministic placeholder for ``docs/demo.gif`` so the public README never ships with a
broken hero image. The live recording guide in ``docs/DEMO_SCRIPT.md`` remains the source for replacing
this with a real browser capture.
"""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - convenience script
    raise SystemExit("Install Pillow to render the demo GIF: python -m pip install pillow") from exc


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo.gif"
PLACEHOLDER_MARKER = b"curiator-demo-gif: generated storyboard placeholder"
W, H = 1120, 630
BG = "#f7f8fb"
INK = "#22252a"
MUTED = "#6c7280"
PURPLE = "#8b3fb6"
BLUE = "#2b8ac6"
GREEN = "#24a05a"
ORANGE = "#e07b2a"
LIME = "#b8d40a"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


F12 = font(12)
F14 = font(14)
F16 = font(16)
F18 = font(18, bold=True)
F22 = font(22, bold=True)
F30 = font(30, bold=True)


def rect(draw: ImageDraw.ImageDraw, xy, fill, outline="#d9dee8", width=1, radius=8) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, fill: str, fg: str = "white") -> None:
    bbox = draw.textbbox((0, 0), text, font=F12)
    w = bbox[2] - bbox[0] + 18
    draw.rounded_rectangle((x, y, x + w, y + 22), radius=11, fill=fill)
    draw.text((x + 9, y + 4), text, font=F12, fill=fg)


def draw_plot(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, fixed: bool) -> None:
    rect(draw, (x, y, x + w, y + h), "white", "#dfe4ee", radius=6)
    draw.text((x + 22, y + 16), "Aviato - monthly performance", font=F18, fill=INK)
    px, py = x + 54, y + 68
    pw, ph = w - 92, h - 132
    draw.rectangle((px, py, px + pw, py + ph), fill="#ffffff", outline="#edf0f5")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    rev = [42, 62, 49, 72, 82, 92, 84, 108]
    costs = [35, 48, 44, 55, 60, 67, 72, 78]
    maxv = 120
    group_w = pw / len(months)
    for i, month in enumerate(months):
        gx = px + i * group_w + 13
        rh = rev[i] / maxv * (ph - 24)
        ch = costs[i] / maxv * (ph - 24)
        draw.rectangle((gx, py + ph - rh, gx + 16, py + ph), fill=ORANGE)
        draw.rectangle((gx + 19, py + ph - ch, gx + 35, py + ph), fill=LIME)
        if i % 2 == 0:
            draw.text((gx - 2, py + ph + 10), month, font=F12, fill=MUTED)
    draw.line((px, py + ph, px + pw, py + ph), fill="#9aa3b2", width=2)
    draw.line((px, py, px, py + ph), fill="#9aa3b2", width=2)
    if fixed:
        draw.text((x + w // 2 - 36, y + h - 42), "Month", font=F14, fill=MUTED)
        draw.text((x + 12, y + h // 2), "$k", font=F14, fill=MUTED)
        lx, ly = px + pw - 182, y + 38
        rect(draw, (lx, ly, lx + 168, ly + 34), "#ffffff", "#dfe4ee", radius=12)
    else:
        lx, ly = px + pw // 2 - 80, py + 22
        rect(draw, (lx, ly, lx + 168, ly + 54), "#ffffffcc", "#dfe4ee", radius=6)
    draw.rectangle((lx + 14, ly + 10, lx + 28, ly + 23), fill=ORANGE)
    draw.text((lx + 34, ly + 8), "revenue", font=F12, fill=INK)
    draw.rectangle((lx + 92, ly + 10, lx + 106, ly + 23), fill=LIME)
    draw.text((lx + 112, ly + 8), "costs", font=F12, fill=INK)


def draw_shell(draw: ImageDraw.ImageDraw, *, step: int, fixed: bool, note: str, status: str) -> None:
    draw.rectangle((0, 0, W, H), fill=BG)
    draw.rectangle((0, 0, W, 58), fill="white", outline="#e6e9f0")
    draw.polygon([(26, 29), (36, 19), (46, 29), (36, 39)], fill=PURPLE)
    draw.text((56, 17), "curIAtor", font=F22, fill=INK)
    draw.text((155, 22), "gallery", font=F16, fill=MUTED)
    draw.text((910, 21), "aviato@local", font=F14, fill=MUTED)

    draw.rectangle((0, 58, 230, H), fill="#fbfbfd", outline="#e3e7ef")
    rect(draw, (18, 82, 210, 114), "white", "#d7dce7", radius=6)
    draw.text((32, 90), "search...", font=F14, fill="#a4abb8")
    rect(draw, (14, 142, 216, 202), "#f2ebfa", "#e0d4ee", radius=8)
    draw.text((28, 154), "aviato", font=F18, fill=INK)
    draw.text((28, 178), "demo - broken", font=F12, fill=MUTED)
    pill(draw, 30, 214, "demo", PURPLE)
    draw.text((28, 262), "sales overview", font=F14, fill=INK)
    draw.text((28, 294), "cohort explorer", font=F14, fill=INK)

    draw.text((270, 84), "Aviato", font=F30, fill=INK)
    draw.text((270, 121), "Live app mounted at /app/aviato", font=F14, fill=MUTED)
    draw_plot(draw, 270, 154, 560, 390, fixed=fixed)

    draw.rectangle((858, 58, W, H), fill="white", outline="#e3e7ef")
    draw.text((884, 86), "Feedback", font=F22, fill=INK)
    draw.text((884, 118), "aviato", font=F14, fill=MUTED)
    draw.text((884, 148), "stars  * * * * *", font=F16, fill="#db8a00")
    rect(draw, (884, 184, 1085, 274), "#ffffff", "#d7dce7", radius=6)
    draw.text((900, 202), note, font=F14, fill=INK)
    rect(draw, (884, 290, 980, 326), "#ffffff", "#d7dce7", radius=6)
    draw.text((902, 299), "capture view", font=F12, fill=INK)
    rect(draw, (884, 340, 1085, 378), GREEN, GREEN, radius=6)
    draw.text((935, 350), "Save feedback", font=F14, fill="white")

    draw.text((884, 420), "prior feedback", font=F16, fill=INK)
    rect(draw, (884, 448, 1085, 574), "#f7fbff", "#d0e7f6", radius=6)
    pill(draw, 900, 463, status, BLUE if status != "done" else GREEN)
    draw.text((900, 496), "axis labels missing,\nlegend covers chart,\nclean up layout", font=F14, fill=INK)
    if step >= 3:
        rect(draw, (900, 526, 1070, 606), "#eaf5ff", "#cfe4f8", radius=6)
        draw.text((914, 540), "Codex reply", font=F16, fill=BLUE)
        draw.text((914, 565), "Added axis titles,\nmoved legend,\nwidened margins.", font=F12, fill="#345")


def frame(step: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    notes = {
        0: "cramped chart",
        1: "axis labels missing,\nlegend covers chart,\nclean up layout",
        2: "captured screenshot",
        3: "curator working",
        4: "fixed and reloaded",
    }
    status = ["new", "new", "working", "done", "done"][step]
    draw_shell(draw, step=step, fixed=step >= 4, note=notes[step], status=status)
    captions = [
        "1. Broken app loads in the gallery",
        "2. Drop feedback on the live app",
        "3. Screenshot + note become a task",
        "4. The curator edits and replies",
        "5. Refresh: the app is fixed",
    ]
    rect(draw, (260, 574, 846, 616), "#20172b", "#20172b", radius=10)
    draw.text((284, 584), captions[step], font=F18, fill="white")
    return img


def main() -> None:
    frames = [frame(i) for i in range(5)]
    durations = [1200, 1400, 1100, 1500, 1800]
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        comment=PLACEHOLDER_MARKER,
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
