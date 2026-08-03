"""
Generate a cohesive top-down villager spritesheet for the extNPC world map.
============================================================================

Authored in the flat, dark-outlined style of the Kenney "Tiny Town" terrain
(CC0) so the character and the ground read as ONE game. Output is a 4x4 sheet
of 24x24 frames:

    rows  = facing direction   [0 down, 1 up, 2 left, 3 right]
    cols  = walk frame          [0 idle/contact, 1 step, 2 contact, 3 step]

The tunic is a light neutral grey so the renderer can multiply it to each
bloodline's team colour. Everything (this file + the PNG) is CC0.

Run:  python dashboard/assets/sprites/make_villager.py
"""
from __future__ import annotations
import os
from PIL import Image

T = 24                      # frame size
OUT = (38, 28, 46, 255)     # dark outline
SKIN = (236, 188, 132, 255)
SKIN_SH = (206, 152, 102, 255)
HAIR = (88, 56, 38, 255)
HAIR_SH = (64, 40, 28, 255)
TUNIC = (226, 226, 230, 255)     # tinted per team at draw time
TUNIC_SH = (190, 190, 198, 255)
BELT = (112, 76, 46, 255)
LEG = (94, 66, 42, 255)
BOOT = (54, 40, 26, 255)
EYE = (34, 24, 40, 255)


def px(img):
    return img.load()


def rect(p, x0, y0, x1, y1, c):
    for y in range(int(y0), int(y1) + 1):
        for x in range(int(x0), int(x1) + 1):
            if 0 <= x < T and 0 <= y < T:
                p[x, y] = c


def add_outline(img):
    """1px dark border around every opaque cluster (the Kenney look)."""
    src = img.copy()
    s = src.load(); d = img.load()
    for y in range(T):
        for x in range(T):
            if src.getpixel((x, y))[3] != 0:
                continue
            near = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < T and 0 <= ny < T and s[nx, ny][3] != 0 and s[nx, ny] != OUT:
                    near = True; break
            if near:
                d[x, y] = OUT


def legs_front(p, frame, y0):
    """Two legs seen from front/back. `frame` lifts one leg to read as a step."""
    lift = {0: (0, 0), 1: (0, 2), 2: (0, 0), 3: (2, 0)}[frame]
    # left leg (x8..10), right leg (x13..15)
    rect(p, 8, y0, 10, y0 + 4 - lift[0], LEG)
    rect(p, 8, y0 + 4 - lift[0] - 1, 10, y0 + 4 - lift[0], BOOT)
    rect(p, 13, y0, 15, y0 + 4 - lift[1], LEG)
    rect(p, 13, y0 + 4 - lift[1] - 1, 15, y0 + 4 - lift[1], BOOT)


def legs_side(p, frame, y0, face):
    """Profile legs: a front leg and a back leg swinging in `face` (+1 right)."""
    step = {0: 0, 1: 3, 2: 0, 3: -3}[frame]
    fx = 11 + face * 1                    # near the body centre
    # back leg
    bx = fx - face * (2 + max(0, -step * face))
    rect(p, bx, y0, bx + 2, y0 + 4, LEG)
    rect(p, bx, y0 + 3, bx + 2, y0 + 4, BOOT)
    # front leg (stepped forward in facing direction)
    frx = fx + face * (1 + max(0, step * face))
    rect(p, frx, y0, frx + 2, y0 + 4, LEG)
    rect(p, frx, y0 + 3, frx + 2, y0 + 4, BOOT)


def draw(direction, frame):
    img = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    p = px(img)
    bob = 1 if frame in (1, 3) else 0     # body rises mid-step
    hy = 5 - bob                           # head top

    if direction in ("down", "up"):
        legs_front(p, frame, 17)
        # body
        rect(p, 7, 11 - bob, 16, 16 - bob, TUNIC)
        rect(p, 7, 15 - bob, 16, 16 - bob, TUNIC_SH)
        rect(p, 7, 16 - bob, 16, 16 - bob, BELT)
        # arms
        rect(p, 5, 11 - bob, 6, 15 - bob, TUNIC)
        rect(p, 17, 11 - bob, 18, 15 - bob, TUNIC)
        rect(p, 5, 15 - bob, 6, 16 - bob, SKIN)
        rect(p, 17, 15 - bob, 18, 16 - bob, SKIN)
        # head
        rect(p, 8, hy, 15, hy + 6, SKIN)
        rect(p, 8, hy + 5, 15, hy + 6, SKIN_SH)
        if direction == "down":
            rect(p, 8, hy, 15, hy + 1, HAIR)          # fringe
            rect(p, 8, hy, 9, hy + 2, HAIR)
            rect(p, 14, hy, 15, hy + 2, HAIR)
            rect(p, 10, hy + 3, 10, hy + 4, EYE)      # eyes (1px, calmer)
            rect(p, 13, hy + 3, 13, hy + 4, EYE)
        else:  # up -> back of the head, all hair
            rect(p, 8, hy, 15, hy + 5, HAIR)
            rect(p, 8, hy + 4, 15, hy + 5, HAIR_SH)

    else:  # left / right profile
        face = -1 if direction == "left" else 1
        legs_side(p, frame, 17, face)
        # body (narrower)
        rect(p, 8, 11 - bob, 15, 16 - bob, TUNIC)
        rect(p, 8, 15 - bob, 15, 16 - bob, TUNIC_SH)
        rect(p, 8, 16 - bob, 15, 16 - bob, BELT)
        # one swinging arm in front
        ax = 12 + face * 2
        rect(p, ax, 11 - bob, ax + face * 1 if False else ax + 1, 15 - bob, TUNIC)
        rect(p, min(ax, ax + 1), 15 - bob, max(ax, ax + 1), 16 - bob, SKIN)
        # head
        rect(p, 8, hy, 15, hy + 6, SKIN)
        rect(p, 8, hy + 5, 15, hy + 6, SKIN_SH)
        # hair at the back (opposite the facing direction)
        if face < 0:   # facing left -> hair on the right
            rect(p, 12, hy, 15, hy + 5, HAIR)
            rect(p, 8, hy, 15, hy + 1, HAIR)
            rect(p, 9, hy + 3, 9, hy + 4, EYE)        # front eye
        else:          # facing right -> hair on the left
            rect(p, 8, hy, 11, hy + 5, HAIR)
            rect(p, 8, hy, 15, hy + 1, HAIR)
            rect(p, 14, hy + 3, 14, hy + 4, EYE)

    add_outline(img)
    return img


def build():
    dirs = ["down", "up", "left", "right"]
    sheet = Image.new("RGBA", (T * 4, T * 4), (0, 0, 0, 0))
    for r, d in enumerate(dirs):
        for c in range(4):
            sheet.alpha_composite(draw(d, c), (c * T, r * T))
    out = os.path.join(os.path.dirname(__file__), "villager.png")
    sheet.save(out)
    print("wrote", out, sheet.size)


if __name__ == "__main__":
    build()
