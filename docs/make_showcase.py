"""Build docs/showcase/ from the full-resolution captures.

The raw captures in `article_screenings/` and `outputs/paper/` are 1800 to 1900
pixels wide and total about 13 MB, which is more than a README needs and more
than a public repository should carry. This produces a curated set, trimmed of
the white page tail a browser capture leaves below the app, resized to a width
GitHub actually renders, and re-encoded.

Run from the repository root:  python docs/make_showcase.py
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "showcase"
WIDTH = 1500

# (destination name, source, trim the white page tail?[, crop fraction off top])
PLAN = [
    ("dashboard-overview.png",
     "outputs/paper/fig_dash_overview.png", True),
    ("dashboard-worldmap.png",
     "article_screenings/10_worldmap_bloodlines.png", False),
    ("dashboard-worldmap-stress.png",
     "article_screenings/12_worldmap_stress_load.png", False),
    ("dashboard-genetics.png",
     "article_screenings/13_genetics_trait_evolution_fingerprint_afs_heterozygosity.png",
     False),
    ("dashboard-community.png",
     "article_screenings/17_community_fst_demes_twocosts_kinship.png", False),
    ("dashboard-individual.png",
     "article_screenings/20_darius42_info.png", False),
    ("dashboard-family-tree.png",
     "article_screenings/24_darius42_family_tree.png", False),
    ("dashboard-controls.png",
     "article_screenings/19_controls_run_parameters.png", False),
    ("dashboard-guide.png",
     "outputs/paper/fig_dash_guide.png", True),
    ("unity-life-stages.png",
     "outputs/paper/fig_life_stages.png", False),
    ("unity-villager.png",
     "article_screenings/48_unity_darius_y39_age23_adult_170cm.png", False,
     0.055),
    ("two-sisters.png",
     "outputs/paper/fig_sisters_sheets.png", False),
]


def trim_page_tail(im: Image.Image) -> Image.Image:
    """Drop the white page under the app.

    A full-page browser capture of a dark UI ends in the browser's own white
    background. Detecting the DARK plane rather than "non-white content" is
    what makes this work: white is bright, so a brightness test keeps the
    very rows it is meant to remove.
    """
    a = np.asarray(im.convert("RGB"))
    dark = (a.max(axis=2) < 60).sum(axis=1)
    rows = np.nonzero(dark > im.width * 0.5)[0]
    if not len(rows):
        return im
    return im.crop((0, 0, im.width, min(im.height, rows.max() + 8)))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for entry in PLAN:
        name, src, trim = entry[0], entry[1], entry[2]
        # Optional fourth field: fraction of the image height to drop from the
        # top, for a capture that includes the host application's own chrome.
        top = entry[3] if len(entry) > 3 else 0.0
        p = ROOT / src
        if not p.exists():
            print("  MISSING  %s" % src)
            continue
        im = Image.open(p).convert("RGB")
        if top:
            im = im.crop((0, int(im.height * top), im.width, im.height))
        if trim:
            im = trim_page_tail(im)
        if im.width > WIDTH:
            h = round(im.height * WIDTH / im.width)
            im = im.resize((WIDTH, h), Image.LANCZOS)
        dest = OUT / name
        im.save(dest, optimize=True)
        kb = dest.stat().st_size // 1024
        total += kb
        print("  %-30s %4d x %4d  %5d KB" % (name, im.width, im.height, kb))
    print("\n%d files, %.1f MB" % (len(PLAN), total / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
