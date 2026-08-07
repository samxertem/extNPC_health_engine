"""
Tests for the catalogue flag (session 16): EXTNPC_CATALOGUE.

The claim that matters most is the FIRST one: the default build is
byte-identical to what every committed figure, calibrated constant and
world save was produced under. The empirical mode is opt-in, recalibrates
itself at import, and refuses to read saves across the boundary.
"""

import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from health_engine.loci import (ALT_FREQ, CATALOGUE_MODE, EMPIRICAL_OVERRIDES,
                                LOCUS_BY_SYMBOL, _EMPIRICAL_PATH)


# md5 of the default catalogue's alt_freq vector, pinned 2026-08-07. If
# this fails, the DEFAULT catalogue changed -- which invalidates every
# committed figure and every existing world save, and must be a
# deliberate, documented model-version event.
_DEFAULT_ALT_FREQ_MD5 = "e94aa5f46271a103a991e358ce5cc35c"


@pytest.mark.skipif(CATALOGUE_MODE != "synthetic",
                    reason="asserts the DEFAULT catalogue; the process was "
                           "started with EXTNPC_CATALOGUE=empirical")
def test_default_mode_is_synthetic_and_byte_identical():
    assert CATALOGUE_MODE == "synthetic"
    assert EMPIRICAL_OVERRIDES == {}
    assert hashlib.md5(ALT_FREQ.tobytes()).hexdigest() == _DEFAULT_ALT_FREQ_MD5


def test_vendored_file_carries_its_provenance():
    """The empirical values must stay auditable: source, population,
    retrieval date, and a per-gene effect-allele rationale."""
    with open(_EMPIRICAL_PATH, encoding="utf-8") as fh:
        bundle = json.load(fh)
    assert bundle["population"] == "1000GENOMES:phase_3:EUR"
    assert bundle["retrieved"]          # a date string
    assert len(bundle["genes"]) >= 20
    for gene, rec in bundle["genes"].items():
        assert rec["rsid"].startswith("rs"), gene
        assert 0.0 < rec["eur_freq"] < 1.0, gene
        assert rec["why"], f"{gene} has no effect-allele rationale"
        # every vendored gene must actually exist in the catalogue
        assert gene in LOCUS_BY_SYMBOL, gene


def _run_empirical(code: str) -> str:
    """Run a snippet under EXTNPC_CATALOGUE=empirical in a fresh process
    (the flag is read at import, so it cannot be flipped in-process)."""
    env = dict(os.environ, EXTNPC_CATALOGUE="empirical")
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_empirical_mode_applies_the_vendored_frequencies():
    out = _run_empirical(
        "from health_engine.loci import (CATALOGUE_MODE, EMPIRICAL_OVERRIDES,"
        " LOCUS_BY_SYMBOL)\n"
        "print(CATALOGUE_MODE, len(EMPIRICAL_OVERRIDES))\n"
        "for g in ('HERC2', 'SLC24A5', 'EDAR', 'GJB2'):\n"
        "    print(g, f'{LOCUS_BY_SYMBOL[g].alt_freq:.4f}')\n"
        "print('bg000', repr(LOCUS_BY_SYMBOL['bg000'].alt_freq))\n")
    lines = out.strip().splitlines()
    assert lines[0].split() == ["empirical", "21"]
    got = dict(l.split() for l in lines[1:])
    # the four flagship values, straight from 1000G phase 3 EUR
    assert got["HERC2"] == "0.6362"
    assert got["SLC24A5"] == "0.9970"      # light-skin allele at fixation
    assert got["EDAR"] == "0.0109"         # 370A nearly absent in EUR
    assert got["GJB2"] == "0.0089"         # 35delG carrier ~1/56
    # peripheral loci are bit-identical across modes
    assert float(got["bg000"]) == pytest.approx(
        LOCUS_BY_SYMBOL["bg000"].alt_freq, abs=1e-12)


def test_empirical_mode_recalibrates_itself():
    """Changing 21 core frequencies re-solves every trait scale at import.
    The calibration targets must still be hit -- same machinery, different
    population -- and the load spectrum (a separate layer with its own
    frequencies) must not move at all."""
    out = _run_empirical(
        "from health_engine.validation import analytic_heritability\n"
        "from health_engine.inbreeding import SPECTRUM, directional_dominance\n"
        "print(f\"{analytic_heritability('height_cm'):.4f}\")\n"
        "print(f\"{analytic_heritability('neuroticism'):.4f}\")\n"
        "print(f\"{directional_dominance('height_cm'):.4f}\")\n"
        "print(f\"{SPECTRUM.lethal_equivalents:.4f}\")\n")
    h2_height, h2_neuro, dirdom, B = out.split()
    assert float(h2_height) == pytest.approx(0.80, abs=0.01)
    assert float(h2_neuro) == pytest.approx(0.40, abs=0.01)
    # the Joshi-calibrated depression survives the frequency change
    assert float(dirdom) == pytest.approx(1.3333, abs=0.01)
    assert float(B) == pytest.approx(1.4, abs=1e-6)


@pytest.mark.skipif(CATALOGUE_MODE != "synthetic",
                    reason="the cross-mode simulation below assumes the "
                           "process itself is running the default catalogue")
def test_saves_refuse_to_load_across_catalogue_modes():
    from simulation import World
    from simulation import worldsave

    w = World(n_founders=6, seed=13)
    for _ in range(3):
        w.step()
    blob = worldsave.build_world_save(w)

    # same mode: loads
    w2 = worldsave.load_world_save(blob)
    assert len(w2.people) == len(w.people)

    # cross mode: must refuse with an explanation, not corrupt quietly
    import health_engine.loci as loci
    original = loci.CATALOGUE_MODE
    try:
        loci.CATALOGUE_MODE = "empirical"
        with pytest.raises(ValueError, match="catalogue"):
            worldsave.load_world_save(blob)
    finally:
        loci.CATALOGUE_MODE = original

    # a pre-flag save (no 'catalogue' key) is a synthetic save and loads
    import gzip
    state = json.loads(gzip.decompress(blob))
    del state["catalogue"]
    legacy = gzip.compress(json.dumps(state).encode())
    w3 = worldsave.load_world_save(legacy)
    assert len(w3.people) == len(w.people)
