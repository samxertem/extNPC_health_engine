"""The figure manifests have to be able to fail.

A manifest that stays the same whatever the figure plots is worse than no
manifest, because CI would go green over a changed model. Each test here names
the direction it checks: stable when nothing moved, different when something
did.
"""
from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402
import pytest                            # noqa: E402

from health_engine import provenance     # noqa: E402
from health_engine.viz import _save      # noqa: E402


def _fig(y_scale: float = 1.0, n: int = 40):
    fig, ax = plt.subplots()
    x = np.linspace(0.0, 1.0, n)
    ax.plot(x, y_scale * x ** 2, label="square")
    ax.scatter(x, x, label="dots")
    ax.set_title("title")
    ax.set_xlabel("xl")
    ax.set_ylabel("yl")
    return fig


def _digest(y_scale: float = 1.0, n: int = 40) -> str:
    fig = _fig(y_scale, n)
    try:
        return provenance.figure_manifest(fig, "x.png")["digest"]
    finally:
        plt.close(fig)


# ------------------------------------------------------- it holds still

def test_identical_figures_give_identical_digests():
    assert _digest() == _digest()


def test_digest_ignores_provenance():
    """Two runs on different machines must agree on the numbers even though
    they disagree about the platform, or CI can never compare anything."""
    fig = _fig()
    a = provenance.figure_manifest(fig, "x.png")
    b = provenance.figure_manifest(fig, "x.png", extra={"platform_note": "other"})
    plt.close(fig)
    assert a["digest"] == b["digest"]
    assert a["provenance"] != b["provenance"]


# ------------------------------------------------------- it can fail

def test_a_changed_value_changes_the_digest():
    assert _digest(y_scale=1.0) != _digest(y_scale=1.000001)


def test_a_changed_sample_size_changes_the_digest():
    assert _digest(n=40) != _digest(n=41)


def test_every_series_is_captured():
    fig = _fig()
    m = provenance.figure_manifest(fig, "x.png")
    plt.close(fig)
    kinds = {s["kind"] for s in m["axes"][0]["series"]}
    assert kinds == {"line", "points"}


def test_axis_labels_are_recorded():
    fig = _fig()
    m = provenance.figure_manifest(fig, "x.png")
    plt.close(fig)
    ax = m["axes"][0]
    assert (ax["title"], ax["xlabel"], ax["ylabel"]) == ("title", "xl", "yl")


# ------------------------------------------------------- it gets written

def test_save_writes_a_sidecar(tmp_path):
    png = os.path.join(str(tmp_path), "demo.png")
    _save(_fig(), png)
    side = os.path.join(str(tmp_path), "demo.json")
    assert os.path.exists(side)
    m = json.loads(open(side, encoding="utf-8").read())
    assert m["figure"] == "demo.png"
    assert m["schema"] == 1
    assert m["provenance"]["libraries"]["numpy"] == np.__version__


def test_manifest_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTNPC_NO_MANIFEST", "1")
    png = os.path.join(str(tmp_path), "demo.png")
    _save(_fig(), png)
    assert os.path.exists(png)
    assert not os.path.exists(os.path.join(str(tmp_path), "demo.json"))


def test_a_failing_manifest_never_destroys_the_figure(tmp_path, monkeypatch):
    """Minutes of simulation reach _save. A provenance bug must not cost them."""
    monkeypatch.setattr(provenance, "figure_manifest",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    png = os.path.join(str(tmp_path), "demo.png")
    _save(_fig(), png)
    assert os.path.exists(png)
    assert not os.path.exists(os.path.join(str(tmp_path), "demo.json"))


# ------------------------------------------------------- provenance content

def test_provenance_carries_no_timestamp():
    """A timestamp would make every regeneration differ and defeat the diff."""
    flat = json.dumps(provenance.run_provenance()).lower()
    for banned in ("timestamp", "generated_at", "date", "utcnow"):
        assert banned not in flat


def test_dirty_tree_is_recorded_when_git_is_available():
    p = provenance.run_provenance()
    assert p["git_dirty"] in (True, False, None)
    if p["git_commit"] is not None:
        assert p["git_dirty"] is not None


@pytest.mark.parametrize("lib", ["numpy", "matplotlib", "scipy"])
def test_library_versions_are_recorded(lib):
    assert provenance.library_versions()[lib] not in ("", "absent", "unknown")
