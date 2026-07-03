#!/usr/bin/env python3
"""Render the git-as-memory provenance excerpt figure from its Markdown source."""

from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "provenance-log-excerpt.md"
DEFAULT_OUTPUT = HERE / "provenance-log-excerpt.png"
W = 1300

BG = "#f8fafc"
INK = "#111827"
MUTED = "#64748b"
PANEL = "#111827"
PANEL_LINE = "#334155"
CODE = "#e5e7eb"
ACCENT = "#93c5fd"


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if mono:
        names = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        ]
    else:
        names = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ]
    for path in names:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


F_TITLE = font(34, True)
F_BODY = font(20)
F_CODE = font(28, mono=True)
F_CODE_BOLD = font(28, True, True)


def extract_first_commit(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    match = re.search(r"```text\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise ValueError(f"no text code block found in {source}")
    excerpt = match.group(1).strip()
    first, *_rest = excerpt.split("\n----", 1)
    return first.strip()


def wrap_code(value: str, width: int = 58) -> list[str]:
    lines: list[str] = []
    for raw in value.splitlines():
        if not raw:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw, width=width, subsequent_indent="  ", break_long_words=False) or [""])
    return lines


def render(source: Path, output: Path) -> None:
    lines = wrap_code(extract_first_commit(source))
    line_height = 40
    h = 190 + len(lines) * line_height + 54
    image = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(image)
    draw.text((42, 40), "Git as memory: one curator commit", fill=INK, font=F_TITLE)
    draw.text((42, 84), "Source: docs/paper/figures/provenance-log-excerpt.md", fill=MUTED, font=F_BODY)
    panel = (42, 130, W - 42, h - 42)
    draw.rounded_rectangle(panel, radius=22, fill=PANEL, outline=PANEL_LINE, width=3)
    y = panel[1] + 28
    for idx, line in enumerate(lines):
        fill = ACCENT if idx == 0 or line.startswith("Curiator-") else CODE
        font_obj = F_CODE_BOLD if idx == 0 or line.startswith("Curiator-") else F_CODE
        draw.text((panel[0] + 28, y), line.replace("★", "*"), fill=fill, font=font_obj)
        y += line_height
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
