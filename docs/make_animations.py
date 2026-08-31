"""Build the animated figures in docs/showcase/ from the full-resolution captures.

Companion to `make_showcase.py`, and it exists for one figure the still images
cannot carry. The claim "one fixed genome yields a different body at every age"
is a claim about CHANGE, and a montage of seven panels asks the reader to do
the comparison themselves. An animation does it for them: the same man, the
same seed, the same genome, and a body that grows, fills out and then loses
six centimetres of stature in old age.

WHAT THE FRAMES ARE. Seven Unity captures of Darius over one 100-year run at
seed 4, taken at the years his life stage changes. Nothing is interpolated and
nothing is re-rendered: each frame is a real capture of the viewer, and the
height in the caption is the height its own inspector panel is displaying in
that frame. A tween between them would be inventing bodies the engine never
produced.

Run from the repository root:  python docs/make_animations.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "article_screenings"
OUT = ROOT / "docs" / "showcase"

WIDTH = 900

# The Unity editor's own toolbar and the Game tab's control strip. Cropped
# because they are the same in every frame and say nothing about the run, and
# because a README figure of an editor chrome is a figure of an editor.
CHROME_TOP = 0.092

# Milliseconds per frame. Slow: each frame is a different decade of a life and
# there are numbers in the panel worth reading, so this is a slideshow rather
# than a flip-book.
HOLD_MS = 1400
HOLD_LAST_MS = 2200

# (source file, year, age, life stage, stature cm). The numbers are the ones
# the capture's own inspector is showing, taken from the filenames the run
# wrote, not re-derived here.
LIFE = [
    ("45_unity_darius_y16_age0_infant_49cm.png", 16, 0, "infant", 49),
    ("46_unity_darius_y19_age3_child_91cm.png", 19, 3, "child", 91),
    ("47_unity_darius_y27_age11_adolescent_137cm.png", 27, 11, "adolescent", 137),
    ("48_unity_darius_y39_age23_adult_170cm.png", 39, 23, "adult", 170),
    ("49_unity_darius_y56_age40_midlife_170cm.png", 56, 40, "midlife", 170),
    ("50_unity_darius_y81_age65_senescent_168cm.png", 81, 65, "senescent", 168),
    ("51_unity_darius_y100_age84_senescent_164cm.png", 100, 84, "senescent", 164),
]

BAR_H = 46
INK = (232, 232, 228)
INK_DIM = (150, 152, 150)
GROUND = (22, 22, 21)
ACCENT = (232, 176, 64)


def load_font(size: int):
    """A real face if the machine has one, Pillow's bitmap default if not.

    The default is unreadable at this size, so a caption drawn with it is
    worse than no caption; but a missing font is not a reason to fail a build
    that is otherwise fine, so it degrades rather than raises.
    """
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf",
                 "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def frame(path: Path, caption: str, right: str, size, fonts) -> Image.Image:
    im = Image.open(path).convert("RGB")
    im = im.crop((0, int(im.height * CHROME_TOP), im.width, im.height))
    im = im.resize(size, Image.LANCZOS)

    canvas = Image.new("RGB", (size[0], size[1] + BAR_H), GROUND)
    canvas.paste(im, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.line([(0, size[1]), (size[0], size[1])], fill=(60, 60, 58), width=1)
    draw.text((14, size[1] + 13), caption, font=fonts[0], fill=INK)
    w = draw.textlength(right, font=fonts[1])
    draw.text((size[0] - w - 14, size[1] + 15), right, font=fonts[1], fill=INK_DIM)
    return canvas


def build_life_stages() -> int:
    missing = [f for f, *_ in LIFE if not (SRC / f).is_file()]
    if missing:
        print(f"  SKIP life-stages.gif: {len(missing)} captures missing "
              f"(first: {missing[0]})")
        print(f"       they live in {SRC}, which is not tracked")
        return 0

    first = Image.open(SRC / LIFE[0][0])
    cropped_h = first.height - int(first.height * CHROME_TOP)
    size = (WIDTH, int(cropped_h * WIDTH / first.width))
    fonts = (load_font(19), load_font(15))

    frames, durations = [], []
    for i, (name, year, age, stage, cm) in enumerate(LIFE):
        caption = f"year {year}   age {age}   {stage}   {cm} cm"
        frames.append(frame(SRC / name, caption,
                            "SAMARA  one genome, seven bodies", size, fonts))
        durations.append(HOLD_LAST_MS if i == len(LIFE) - 1 else HOLD_MS)

    dest = OUT / "life-stages.gif"
    frames[0].save(dest, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    kb = dest.stat().st_size // 1024
    print(f"  life-stages.gif   {len(frames)} frames  {size[0]}x{size[1] + BAR_H}"
          f"  {kb} KB")
    if kb > 8000:
        print("  WARNING: over 8 MB. GitHub will serve it, but slowly.")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"source {SRC}")
    written = build_life_stages()
    print(f"\n{written} animation(s) written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
