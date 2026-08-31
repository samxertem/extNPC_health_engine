"""Did regenerating the figures change what they say?

The obvious CI step is `git diff --exit-code outputs/`, and it does not work.
Font rasterisation and antialiasing are platform properties and matplotlib
stamps its own version into PNG metadata, so a Linux runner comparing against
figures generated on Windows produces a red build that means "different
fonts". Nothing about the model has changed.

This compares the JSON manifests instead, which carry the numbers the figures
plot (see `health_engine.provenance`). It reads the committed manifest out of
git and the regenerated one out of the working tree, so the intended CI shape
is: check out, regenerate, run this.

    python health_engine_prototype.py
    python tools/check_figures.py

A GRADUATED RESPONSE, because the two failure modes are not the same thing.
The digest is an exact hash, so it moves on the last bit of a float that a
reordered summation put somewhere else. The summary statistics carry an
explicit tolerance. So:

    digest same                     -> silent, nothing moved
    digest differs, stats within tol -> reported as NOISE, exit 0
    a statistic moves beyond tol     -> reported as CHANGED, exit 1

That middle case is the one worth having. It says "this platform computes a
slightly different float and nothing you claim depends on it", which is true
and useful, and it is exactly the case a byte-diff cannot express.

Usage:
    python tools/check_figures.py [--tol 1e-9] [--ref HEAD] [--dir outputs]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from health_engine.provenance import axes_digest      # noqa: E402

# Fields of a series summary that are compared numerically.
_STATS = ("n", "min", "max", "mean", "std")


def git_show(ref: str, rel: str) -> Optional[str]:
    out = subprocess.run(["git", "show", "%s:%s" % (ref, rel)],
                         cwd=str(ROOT), capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def series_index(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Flatten a manifest to {addressable name: summary}.

    Keyed by axis index, artist kind, label and position, so a message can name
    the thing that moved rather than saying "series 3".
    """
    flat: Dict[str, Dict[str, Any]] = {}
    for ax in manifest.get("axes", []):
        for i, s in enumerate(ax.get("series", [])):
            key = "ax%s/%s/%s#%d" % (ax.get("index"), s.get("kind"),
                                     s.get("label"), i)
            for axis_name in ("x", "y", "v"):
                if s.get(axis_name):
                    flat["%s.%s" % (key, axis_name)] = s[axis_name]
    return flat


def compare(old: Dict[str, Any], new: Dict[str, Any],
            tol: float) -> Tuple[List[str], List[str]]:
    """Return (changed, noise) descriptions."""
    changed: List[str] = []
    noise: List[str] = []
    a, b = series_index(old), series_index(new)

    for key in sorted(set(a) | set(b)):
        if key not in a:
            changed.append("    + new series %s" % key)
            continue
        if key not in b:
            changed.append("    - series gone %s" % key)
            continue
        for f in _STATS:
            av, bv = a[key].get(f), b[key].get(f)
            if av is None or bv is None:
                continue
            if f == "n":
                if av != bv:
                    changed.append("    %s  n %s -> %s" % (key, av, bv))
                continue
            d = abs(float(av) - float(bv))
            if d > tol:
                changed.append("    %s  %s %.9g -> %.9g  (delta %.3g)"
                               % (key, f, av, bv, d))
        if a[key].get("digest") != b[key].get("digest") and not changed:
            noise.append("    %s  digest moved, every statistic within %g"
                         % (key, tol))
    return changed, noise


def provenance_note(old: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
    """Differences that explain a result without invalidating it."""
    out = []
    po, pn = old.get("provenance", {}), new.get("provenance", {})
    for f in ("python", "platform", "catalogue"):
        if po.get(f) != pn.get(f):
            out.append("      %s: %s -> %s" % (f, po.get(f), pn.get(f)))
    lo, ln = po.get("libraries", {}), pn.get("libraries", {})
    for lib in sorted(set(lo) | set(ln)):
        if lo.get(lib) != ln.get(lib):
            out.append("      %s: %s -> %s" % (lib, lo.get(lib), ln.get(lib)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD",
                    help="git ref holding the baseline manifests")
    ap.add_argument("--dir", default="outputs",
                    help="directory of regenerated figures")
    ap.add_argument("--tol", type=float, default=1e-9,
                    help="allowed movement in a summary statistic")
    args = ap.parse_args()

    d = ROOT / args.dir
    current = sorted(p for p in d.glob("*.json"))
    if not current:
        print("no manifests in %s; run the demo first" % args.dir)
        return 1

    n_ok = n_new = 0
    failures: List[str] = []
    noises: List[str] = []

    for p in current:
        rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
        raw = git_show(args.ref, rel)
        new = json.loads(p.read_text(encoding="utf-8"))
        if raw is None:
            print("  NEW      %s  (no baseline at %s)" % (p.name, args.ref))
            n_new += 1
            continue
        old = json.loads(raw)

        # Never trust a stored digest without recomputing it. A manifest whose
        # digest field disagrees with its own content has been edited by hand
        # or truncated, and reporting that is the point of having a digest.
        for tag, man in (("baseline", old), ("regenerated", new)):
            if man.get("digest") != axes_digest(man.get("axes", [])):
                print("  TAMPERED %s  (%s manifest's digest does not match "
                      "its own content)" % (p.name, tag))
                failures.append(p.name)

        # The statistics are compared whatever the digests say. The digest only
        # decides, once the statistics agree, whether this is identical output
        # or the last bit of a float landing elsewhere.
        changed, noise = compare(old, new, args.tol)
        if not changed and old.get("digest") == new.get("digest"):
            n_ok += 1
            continue

        if changed:
            print("  CHANGED  %s" % p.name)
            for line in changed[:12]:
                print(line)
            if len(changed) > 12:
                print("    ... and %d more" % (len(changed) - 12))
            note = provenance_note(old, new)
            if note:
                print("    generated under:")
                for line in note:
                    print(line)
            failures.append(p.name)
        else:
            print("  NOISE    %s  (digest moved, statistics agree)" % p.name)
            for line in noise[:4]:
                print(line)
            noises.append(p.name)
            n_ok += 1

    # One file can trip both the tamper check and the comparison; it is still
    # one broken figure.
    failures = sorted(set(failures))

    print()
    print("%d unchanged, %d float-noise, %d new, %d changed"
          % (n_ok - len(noises), len(noises), n_new, len(failures)))
    if failures:
        print("\nA figure's numbers moved. If that was intended, regenerate,")
        print("commit the manifests with the change, and say why in the")
        print("commit message. If it was not, this is the regression.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
