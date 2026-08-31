"""Run manifests: what a figure plots, and where it came from.

A PNG is evidence you cannot check. Two runs of the same seeded code produce
two files that are byte-identical on one machine and byte-different on another,
because font rasterisation and antialiasing are platform properties, and
because matplotlib stamps its own version into the PNG metadata. So a CI step
built on `git diff --exit-code outputs/` fails whenever the runner has
different fonts, which is a red build that means nothing.

This writes a JSON sidecar next to every figure carrying the *numbers the
figure plots*, read straight off the matplotlib artists, plus the provenance of
the run that produced them. Diffing those is platform-independent, and a
failure names the series that moved instead of saying that some pixels changed.

TWO DESIGN DECISIONS WORTH THE PARAGRAPH.

**Read the artists, do not ask the caller.** The alternative was a `values=`
argument on each of the twenty `plot_*` functions. That drifts: someone adds a
series and forgets to add it to the dict, and the manifest quietly stops
describing the figure. Walking `fig.axes` cannot drift, and it cannot be
forgotten when figure twenty-one arrives.

**No timestamp.** Provenance usually wants one, and here it would defeat the
entire point: a timestamp makes every regeneration differ, so nothing could
ever be diffed. The git revision is the timestamp, and it is recorded.

Series are stored as a statistical digest rather than a raw dump, because
`pedigree_relatedness` alone plots tens of thousands of points and a manifest
nobody can open is a manifest nobody reads. The digest is a hash over the
rounded values, so any change to a plotted number moves it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from typing import Any, Dict, List, Optional

import numpy as np

# Rounding applied before hashing. Nine decimals is far below anything the
# model can meaningfully assert and far above float64 noise from a reordered
# sum, so the digest is stable across platforms without being blind.
_ROUND = 9

_VERSIONED = ("numpy", "scipy", "matplotlib", "networkx", "plotly", "dash")


def _git(*args: str) -> Optional[str]:
    """A git query that returns None instead of raising, because a figure must
    still be written from a tarball with no .git directory."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run(("git",) + args, cwd=root, capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def library_versions() -> Dict[str, str]:
    """Installed versions of the libraries a figure's numbers depend on.

    Imported lazily and individually: a missing optional library records as
    absent rather than crashing the figure that did not need it.
    """
    out: Dict[str, str] = {}
    for name in _VERSIONED:
        try:
            mod = __import__(name)
            out[name] = str(getattr(mod, "__version__", "unknown"))
        except ImportError:
            out[name] = "absent"
    return out


def run_provenance(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Where this run came from. Deliberately timestamp-free; see the module
    docstring."""
    commit = _git("rev-parse", "--short", "HEAD")
    status = _git("status", "--porcelain")
    prov: Dict[str, Any] = {
        "git_commit": commit,
        # A figure generated from an edited tree is not reproducible from any
        # revision, and saying so is the whole point of recording it.
        "git_dirty": (bool(status) if status is not None else None),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "catalogue": os.environ.get("EXTNPC_CATALOGUE", "synthetic"),
        "libraries": library_versions(),
    }
    if extra:
        prov.update(extra)
    return prov


def _stats(values) -> Optional[Dict[str, Any]]:
    """Compact description of one plotted series."""
    a = np.asarray(values, dtype=float).ravel()
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    rounded = np.round(a, _ROUND)
    return {
        "n": int(a.size),
        "min": float(rounded.min()),
        "max": float(rounded.max()),
        "mean": float(np.round(a.mean(), _ROUND)),
        "std": float(np.round(a.std(), _ROUND)),
        "digest": hashlib.sha256(rounded.tobytes()).hexdigest()[:16],
    }


def _series_from_axis(ax) -> List[Dict[str, Any]]:
    """Every drawable on one axis, as x/y digests.

    Handles the artist kinds this project's figures actually use. An unknown
    artist is skipped rather than guessed at, because a wrong summary is worse
    than an absent one.
    """
    out: List[Dict[str, Any]] = []

    for ln in getattr(ax, "lines", []):
        x, y = _stats(ln.get_xdata()), _stats(ln.get_ydata())
        if y is not None:
            out.append({"kind": "line", "label": str(ln.get_label()),
                        "x": x, "y": y})

    for coll in getattr(ax, "collections", []):
        offs = None
        try:
            offs = coll.get_offsets()
        except (AttributeError, TypeError):
            offs = None
        if offs is not None and len(offs):
            arr = np.asarray(offs, dtype=float)
            out.append({"kind": "points", "label": str(coll.get_label()),
                        "x": _stats(arr[:, 0]), "y": _stats(arr[:, 1])})
            continue
        arr = getattr(coll, "get_array", lambda: None)()
        if arr is not None and np.size(arr):
            out.append({"kind": "mesh", "label": str(coll.get_label()),
                        "v": _stats(arr)})

    heights = [p.get_height() for p in getattr(ax, "patches", [])
               if hasattr(p, "get_height")]
    if heights:
        out.append({"kind": "bars", "label": "patches", "v": _stats(heights)})

    for im in getattr(ax, "images", []):
        arr = im.get_array()
        if arr is not None and np.size(arr):
            out.append({"kind": "image", "label": str(im.get_label()),
                        "v": _stats(np.asarray(arr, dtype=float))})

    return out


def figure_manifest(fig, png_path: str,
                    extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Describe a figure by the numbers it draws."""
    axes = []
    for i, ax in enumerate(fig.axes):
        series = _series_from_axis(ax)
        axes.append({
            "index": i,
            "title": str(ax.get_title()),
            "xlabel": str(ax.get_xlabel()),
            "ylabel": str(ax.get_ylabel()),
            "series": series,
        })

    # One digest over every series digest, so a single field answers "did any
    # number in this figure move".
    blob = json.dumps([a["series"] for a in axes], sort_keys=True)
    return {
        "figure": os.path.basename(png_path),
        "generated_by": "health_engine.viz",
        "schema": 1,
        "digest": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
        "provenance": run_provenance(extra),
        "axes": axes,
    }


def write_manifest(fig, png_path: str,
                   extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Write `<figure>.json` beside `<figure>.png`.

    Never raises. A manifest is evidence about a figure, and failing to write
    the evidence must not destroy the figure: the caller has usually spent
    minutes of simulation getting here. Set EXTNPC_NO_MANIFEST=1 to skip.
    """
    if os.environ.get("EXTNPC_NO_MANIFEST"):
        return None
    try:
        dest = os.path.splitext(png_path)[0] + ".json"
        payload = figure_manifest(fig, png_path, extra)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        return dest
    except Exception as exc:                      # pragma: no cover - defensive
        print("  [manifest] skipped %s: %s" % (png_path, exc), file=sys.stderr)
        return None
