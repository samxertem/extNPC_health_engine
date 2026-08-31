"""Generate the README's diagrams as SVG.

Written rather than drawn, for the same reason every other figure in this
repository is regenerated rather than pasted: a diagram that cannot be rebuilt
drifts away from the thing it describes, and nobody notices until a reviewer
does. Run it and the three SVGs are byte-identical every time.

  docs/brand/banner.svg        the wordmark
  docs/brand/architecture.svg  four layers, one bundle, and the harness loop
  docs/brand/inheritance.svg   blending against meiosis, the core argument

Constraints that shaped the output. GitHub serves README images through a
proxy and sanitises them, so there is no <script>, no external font, no
<style> block and no CSS media query here: everything is a presentation
attribute. Each figure also carries its own dark panel rather than a
transparent background, because a transparent figure that looks right in dark
mode is unreadable in light mode, and the reader picks the mode.

Usage:  python docs/make_diagrams.py
"""
from __future__ import annotations

import random
from pathlib import Path

OUT = Path(__file__).resolve().parent / "brand"

# ----------------------------------------------------------------------
# Palette. Dark panel, high-contrast ink, and two hues that mean "from the
# mother" and "from the father" wherever they appear in any of the figures.
# ----------------------------------------------------------------------
PANEL = "#0B0E14"
EDGE = "#1F2733"
GRID = "#161C26"
INK = "#E6EDF3"
INK2 = "#AEBAC8"
MUTED = "#6E7B8B"
ACCENT = "#4EC9E0"
MAT = "#7C9EFF"      # maternal haplotype
PAT = "#FF9E64"      # paternal haplotype
GOOD = "#7EE787"
WARN = "#F2C14E"

FONT = ("ui-sans-serif,-apple-system,BlinkMacSystemFont,'Segoe UI',"
        "Helvetica,Arial,sans-serif")
MONO = ("ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
        "'Liberation Mono',monospace")


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text(x, y, s, size=13, fill=INK, weight="400", anchor="start",
         font=FONT, spacing=None, opacity=None):
    a = ['x="%s"' % x, 'y="%s"' % y, 'font-family="%s"' % font,
         'font-size="%s"' % size, 'fill="%s"' % fill,
         'font-weight="%s"' % weight, 'text-anchor="%s"' % anchor]
    if spacing is not None:
        a.append('letter-spacing="%s"' % spacing)
    if opacity is not None:
        a.append('opacity="%s"' % opacity)
    return "<text %s>%s</text>" % (" ".join(a), esc(s))


def rect(x, y, w, h, fill, rx=0, stroke=None, sw=1, opacity=None):
    a = ['x="%s"' % x, 'y="%s"' % y, 'width="%s"' % w, 'height="%s"' % h,
         'fill="%s"' % fill, 'rx="%s"' % rx]
    if stroke:
        a += ['stroke="%s"' % stroke, 'stroke-width="%s"' % sw]
    if opacity is not None:
        a.append('opacity="%s"' % opacity)
    return "<rect %s/>" % " ".join(a)


def line(x1, y1, x2, y2, stroke, sw=1.5, dash=None, cap="round"):
    a = ['x1="%s"' % x1, 'y1="%s"' % y1, 'x2="%s"' % x2, 'y2="%s"' % y2,
         'stroke="%s"' % stroke, 'stroke-width="%s"' % sw,
         'stroke-linecap="%s"' % cap]
    if dash:
        a.append('stroke-dasharray="%s"' % dash)
    return "<line %s/>" % " ".join(a)


def path(d, stroke=None, fill="none", sw=1.5, dash=None, cap="round"):
    a = ['d="%s"' % d, 'fill="%s"' % fill]
    if stroke:
        a += ['stroke="%s"' % stroke, 'stroke-width="%s"' % sw,
              'stroke-linecap="%s"' % cap, 'stroke-linejoin="round"']
    if dash:
        a.append('stroke-dasharray="%s"' % dash)
    return "<path %s/>" % " ".join(a)


def svg(w, h, body, title, desc):
    """Wrap a body. The <title> and <desc> are what a screen reader gets, so
    they carry the figure's content rather than its filename."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'width="%d" height="%d" role="img" aria-labelledby="t d">\n'
        '<title id="t">%s</title>\n<desc id="d">%s</desc>\n'
        '%s\n</svg>\n' % (w, h, w, h, esc(title), esc(desc), body))


def panel(w, h, pad=0):
    return rect(pad, pad, w - 2 * pad, h - 2 * pad, PANEL, rx=14,
                stroke=EDGE, sw=1)


# ======================================================================
# 1. Banner
# ======================================================================
def banner() -> str:
    W, H = 1200, 300
    p = [panel(W, H, 1)]

    # A faint chromosome-ladder field behind the mark, so the panel is not
    # an empty rectangle. Deterministic: fixed seed, fixed geometry.
    rnd = random.Random(11)
    for i in range(46):
        x = 40 + i * 25.0
        y0 = 40 + rnd.random() * 30
        y1 = H - 40 - rnd.random() * 30
        p.append(line(x, y0, x, y1, GRID, sw=2))

    # The samara: a seed carrying a wing. The wing is drawn as a double
    # helix, because the whole point of the name is what the wing carries.
    cx, cy = 148, 150
    p.append("<g opacity='0.95'>")
    p.append(path("M %d %d C %d %d, %d %d, %d %d" %
                  (cx + 8, cy - 4, cx + 70, cy - 68, cx + 168, cy - 52,
                   cx + 196, cy - 8),
                  stroke=ACCENT, sw=2.4))
    p.append(path("M %d %d C %d %d, %d %d, %d %d" %
                  (cx + 8, cy + 6, cx + 74, cy - 20, cx + 166, cy - 4,
                   cx + 196, cy - 8),
                  stroke=MAT, sw=2.4))
    # rungs between the two strands: the base pairs of the wing
    for t in [0.16, 0.3, 0.44, 0.58, 0.72, 0.86]:
        def bez(p0, p1, p2, p3, t):
            u = 1 - t
            return (u * u * u * p0 + 3 * u * u * t * p1
                    + 3 * u * t * t * p2 + t * t * t * p3)
        x1 = bez(cx + 8, cx + 70, cx + 168, cx + 196, t)
        y1 = bez(cy - 4, cy - 68, cy - 52, cy - 8, t)
        x2 = bez(cx + 8, cx + 74, cx + 166, cx + 196, t)
        y2 = bez(cy + 6, cy - 20, cy - 4, cy - 8, t)
        p.append(line(round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1),
                      PAT, sw=1.6, dash=None))
    # the seed itself
    p.append("<ellipse cx='%d' cy='%d' rx='17' ry='22' fill='%s' "
             "stroke='%s' stroke-width='2' transform='rotate(-18 %d %d)'/>"
             % (cx, cy, "#12202B", ACCENT, cx, cy))
    p.append("<circle cx='%d' cy='%d' r='5' fill='%s'/>" % (cx, cy, ACCENT))
    p.append("</g>")

    x = 400
    p.append(text(x, 138, "SAMARA", 76, INK, "700", spacing="14"))
    p.append(text(x + 4, 172, "Simulated Ancestry, Meiosis And Regulatory Architecture",
                  17, ACCENT, "600", spacing="0.4"))
    p.append(line(x + 4, 194, W - 60, 194, EDGE, sw=1))
    p.append(text(x + 4, 222,
                  "A quantitative-genetics engine for believable non-player characters.",
                  15, INK2))
    p.append(text(x + 4, 246,
                  "Real meiosis, a declared heritability, and twenty population-genetics",
                  15, INK2))
    p.append(text(x + 4, 246 + 22,
                  "laws measured from its own output rather than computed into it.",
                  15, INK2))

    return svg(W, H, "\n".join(p), "SAMARA",
               "Wordmark: a samara seed whose wing is drawn as a double helix, "
               "beside the name SAMARA, Simulated Ancestry, Meiosis And "
               "Regulatory Architecture.")


# ======================================================================
# 2. Architecture
# ======================================================================
def architecture() -> str:
    W, H = 1200, 585
    p = [panel(W, H, 1)]

    def box(x, y, w, h, tag, title, lines, hue):
        g = [rect(x, y, w, h, "#0E141C", rx=12, stroke=hue, sw=1.4),
             rect(x, y, w, 3.5, hue, rx=2),
             text(x + 16, y + 30, tag, 9.5, hue, "700", spacing="1.6"),
             text(x + 16, y + 54, title, 18, INK, "700")]
        for i, ln in enumerate(lines):
            g.append(text(x + 16, y + 80 + i * 19, ln, 12.5, INK2))
        return "\n".join(g)

    def box_h(n_lines):
        """Height that actually contains n_lines of body text."""
        return 80 + max(0, n_lines - 1) * 19 + 22

    def arrow(x1, y1, x2, y2, hue, dash=None):
        """A segment with a filled head, pointing along its own direction."""
        import math
        a = math.atan2(y2 - y1, x2 - x1)
        # stop the shaft short so it does not poke through the head
        sx, sy = x2 - 9 * math.cos(a), y2 - 9 * math.sin(a)
        pts = []
        for off in (2.5, -2.5):
            pts.append("%.1f,%.1f" % (x2 - 11 * math.cos(a - off * 0.13),
                                      y2 - 11 * math.sin(a - off * 0.13)))
        return "\n".join([
            line(x1, y1, round(sx, 1), round(sy, 1), hue, sw=2, dash=dash),
            '<polygon points="%.1f,%.1f %s" fill="%s"/>' % (x2, y2, " ".join(pts), hue),
        ])

    p.append(text(40, 42, "ONE SIMULATION, FOUR LAYERS, ONE BUNDLE BETWEEN THEM",
                  11, MUTED, "700", spacing="2"))

    ENG = (40, 70, 240, box_h(4))
    SIM = (330, 70, 240, box_h(4))
    BUN = (620, 86, 180, box_h(3))
    DSH = (850, 60, 310, box_h(4))
    VWR = (850, 236, 310, box_h(4))

    p.append(box(*ENG, "PYTHON  ·  14.2k LINES", "Engine", [
        "505 loci, 22 autosomes + XY", "meiosis as a Poisson process",
        "P = A + D + I + G×E + E", "42 traits, declared h²"], ACCENT))
    p.append(box(*SIM, "PYTHON  ·  3.8k LINES", "Simulation", [
        "yearly turnover, Gompertz", "Gale-Shapley pairing",
        "island demes + migration", "8 scenarios, 3 shocks"], MAT))
    p.append(box(*BUN, "CSV + MANIFEST", "Bundle", [
        "people · history · pedigree", "frames · demes · flows",
        "seed, params, revision"], WARN))
    p.append(box(*DSH, "DASH / PLOTLY  ·  5.2k LINES", "Dashboard", [
        "28 panels, 12-metric deck", "7 views, 5-tab character sheet",
        "timeline replay of any year", "two-individual comparison"], GOOD))
    p.append(box(*VWR, "UNITY C#  ·  10.8k LINES", "Viewer", [
        "one rigged body per life stage", "provenance HUD in every frame",
        "headcount reconciled per year", "122 EditMode tests"], PAT))

    ey, sy_, by = ENG[1] + ENG[3] / 2, SIM[1] + SIM[3] / 2, BUN[1] + BUN[3] / 2
    p.append(arrow(ENG[0] + ENG[2] + 4, ey, SIM[0] - 6, sy_, MUTED))
    p.append(arrow(SIM[0] + SIM[2] + 4, sy_, BUN[0] - 6, by, MUTED))
    p.append(arrow(BUN[0] + BUN[2] + 4, by - 8, DSH[0] - 6, DSH[1] + 70, MUTED))
    p.append(arrow(BUN[0] + BUN[2] + 4, by + 8, VWR[0] - 6, VWR[1] + 60, MUTED))

    # The two surfaces are tied to each other, not merely fed from one file.
    px = DSH[0] + 40
    p.append(line(px, DSH[1] + DSH[3], px, VWR[1], GOOD, sw=1.6, dash="4 4"))
    p.append(text(px + 12, (DSH[1] + DSH[3] + VWR[1]) / 2 + 4,
                  "parity fixture · identical strings", 10.5, MUTED, "600",
                  font=MONO))

    # The harness reads output back and never feeds the engine.
    HAR = (40, 400, 700, 160)
    p.append(box(*HAR, "MEASURED, NOT COMPUTED", "Validation harness", [
        "Hardy-Weinberg · Haldane · midparent-offspring · breeder's equation",
        "Daetwyler · drift · imprinting gap · Malécot kinship · lethal equivalents",
        "directional dominance · purging · CNV dosage · growth curve"], WARN))
    p.append(text(HAR[0] + 16, HAR[1] + 137,
                  "20 gated verdicts, 20 passes  ·  1,211 tests  ·  every one can fail",
                  12.5, WARN, "600"))

    p.append(line(160, HAR[1], 160, ENG[1] + ENG[3] + 34, WARN, sw=2, dash="5 5"))
    p.append(arrow(160, ENG[1] + ENG[3] + 34, 160, ENG[1] + ENG[3] + 6, WARN))
    p.append(text(176, ENG[1] + ENG[3] + 26, "reads output back", 10.5, MUTED,
                  "600", font=MONO))
    p.append(text(176, ENG[1] + ENG[3] + 44, "never writes into it", 10.5,
                  MUTED, "600", font=MONO))

    p.append(text(772, 428, "No code path evaluates a population-genetics law",
                  13, INK2))
    p.append(text(772, 448, "in order to produce output. Those appear only in",
                  13, INK2))
    p.append(text(772, 468, "the harness, reading the output back and testing",
                  13, INK2))
    p.append(text(772, 488, "it against closed form.", 13, INK2))
    p.append(text(772, 518, "That is the whole methodological claim.", 13,
                  ACCENT, "600"))

    return svg(W, H, "\n".join(p), "SAMARA architecture",
               "Engine feeds Simulation, which exports a CSV bundle read by "
               "both the Dashboard and the Unity Viewer, the two held to "
               "identical output by a generated parity fixture. A validation "
               "harness reads the output back and never writes into it.")


# ======================================================================
# 3. Blending against meiosis
# ======================================================================
def inheritance() -> str:
    W, H = 1200, 430
    p = [panel(W, H, 1)]
    rnd = random.Random(4)

    def chrom(x, y, w, h, blocks, rx=4):
        """A chromosome as a run of coloured blocks."""
        g = [rect(x, y, w, h, "#0E141C", rx=rx)]
        n = len(blocks)
        seg = w / n
        for i, c in enumerate(blocks):
            g.append(rect(round(x + i * seg, 2), y, round(seg, 2) + 0.4, h, c,
                          rx=0))
        g.append(rect(x, y, w, h, "none", rx=rx, stroke=EDGE, sw=1))
        return "\n".join(g)

    def shade(base, k):
        return base

    N = 24
    mother = [MAT if rnd.random() > 0.35 else "#5B76C4" for _ in range(N)]
    father = [PAT if rnd.random() > 0.35 else "#C4703F" for _ in range(N)]

    # ---- left panel: blending ----------------------------------------
    p.append(rect(30, 30, 540, H - 60, "#0E141C", rx=12, stroke=EDGE, sw=1))
    p.append(text(56, 66, "BLENDING", 12, WARN, "700", spacing="2"))
    p.append(text(56, 94, "child = (mother + father) / 2 + noise", 15, INK,
                  "600", font=MONO))

    p.append(text(56, 132, "mother", 11, MUTED, "600"))
    p.append(rect(130, 120, 300, 16, "#0E141C", rx=8, stroke=EDGE, sw=1))
    p.append("<circle cx='190' cy='128' r='7' fill='%s'/>" % MAT)
    p.append(text(56, 164, "father", 11, MUTED, "600"))
    p.append(rect(130, 152, 300, 16, "#0E141C", rx=8, stroke=EDGE, sw=1))
    p.append("<circle cx='372' cy='160' r='7' fill='%s'/>" % PAT)

    p.append(line(130, 186, 430, 186, EDGE, sw=1, dash="3 4"))
    p.append(line(281, 112, 281, 300, MUTED, sw=1, dash="4 5"))
    p.append(text(281, 106, "midparent", 10, MUTED, "600", anchor="middle"))

    for i, dy in enumerate((0, 30, 60)):
        y = 206 + dy
        p.append(text(56, y + 8, "child %d" % (i + 1), 11, MUTED, "600"))
        p.append(rect(130, y, 300, 16, "#0E141C", rx=8, stroke=EDGE, sw=1))
        jitter = (-9, 5, -2)[i]
        p.append("<circle cx='%d' cy='%d' r='7' fill='%s'/>"
                 % (281 + jitter, y + 8, WARN))

    p.append(text(56, 336, "Every child lands on the midpoint. There is no", 13, INK2))
    p.append(text(56, 356, "genotype to vary, so siblings correlate at 0.54", 13, INK2))
    p.append(text(56, 376, "where theory says 0.21, and heritability cannot", 13, INK2))
    p.append(text(56, 396, "be a parameter of the model at all.", 13, WARN, "600"))

    # ---- right panel: meiosis ----------------------------------------
    p.append(rect(630, 30, 540, H - 60, "#0E141C", rx=12, stroke=EDGE, sw=1))
    p.append(text(656, 66, "MEIOSIS", 12, ACCENT, "700", spacing="2"))
    p.append(text(656, 94, "crossovers drawn along a centimorgan map", 15, INK,
                  "600", font=MONO))

    p.append(text(656, 132, "mother", 11, MUTED, "600"))
    p.append(chrom(730, 120, 400, 16, mother))
    p.append(text(656, 164, "father", 11, MUTED, "600"))
    p.append(chrom(730, 152, 400, 16, father))

    for i, dy in enumerate((0, 30, 60)):
        y = 206 + dy
        # an independent meiosis per child: crossover points differ
        k = rnd.randint(1, 3)
        cuts = sorted(rnd.sample(range(2, N - 1), k))
        src, out, cur = mother, [], 0
        for c in cuts + [N]:
            out += [(mother if src is mother else father)[j]
                    for j in range(cur, c)]
            src = father if src is mother else mother
            cur = c
        p.append(text(656, y + 8, "child %d" % (i + 1), 11, MUTED, "600"))
        p.append(chrom(730, y, 400, 16, out))
        for c in cuts:
            cx = round(730 + 400 * c / N, 1)
            p.append(line(cx, y - 4, cx, y + 20, INK, sw=1.2))

    p.append(text(656, 336, "Each child is an independent mosaic. Linked genes", 13, INK2))
    p.append(text(656, 356, "travel together, one gene reaches several traits,", 13, INK2))
    p.append(text(656, 376, "and the declared heritability comes back out of", 13, INK2))
    p.append(text(656, 396, "the measurement: 0.835 against a declared 0.80.", 13, ACCENT, "600"))

    return svg(W, H, "\n".join(p), "Blending against meiosis",
               "Left: under blending every child lands on the midparent value. "
               "Right: under meiosis each child is an independent recombined "
               "mosaic of the parental haplotypes.")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("banner.svg", banner),
                     ("architecture.svg", architecture),
                     ("inheritance.svg", inheritance)):
        dest = OUT / name
        dest.write_text(fn(), encoding="utf-8")
        print("  %-20s %6d bytes" % (name, dest.stat().st_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
