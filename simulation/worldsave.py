"""
Complete world save / restore.
==============================

`export.py` is for ANALYSIS: flat CSVs, portable, lossy on purpose. This is
the other thing entirely -- an engine-ready snapshot that restores to a world
you can keep stepping.

What "complete" has to mean here
--------------------------------
Everything the next `step()` reads, including the parts it is tempting to skip
because the file looks fine without them:

* the **bit-generator state**, not just the seed. A world reloaded with a
  fresh generator seeded from `seed` would replay its FIRST years rather than
  continue. The save would look correct and be silently wrong -- the worst
  possible failure for a thesis run.
* the **name counters**, or a reloaded world starts handing out names that are
  already in use, and names are dictionary keys.
* the **PCA fit**, or every dot on the genetic map jumps on reload.
* the **snapshot ring**, or time travel quietly loses its history.

Encoding
--------
Generic, because the object graph is deep and made almost entirely of
dataclasses holding numpy arrays: genome haplotypes, deleterious-load
haplotypes, methylation vectors, X chromosomes. Arrays are stored as base64 of
their raw buffer plus dtype and shape -- lossless, and far smaller than a JSON
list of numbers. Dataclasses are tagged with their qualified name and rebuilt
field by field.

Decoding instantiates classes only from an allow-list of this project's own
modules. A save file is data; data should never be able to name an arbitrary
importable class.
"""

from __future__ import annotations

import base64
import dataclasses
import gzip
import importlib
import json
from collections import deque
from typing import Any

import numpy as np

SAVE_FORMAT_VERSION = 1


def _catalogue_mode() -> str:
    """The locus-catalogue mode this process is running under."""
    from health_engine.loci import CATALOGUE_MODE
    return CATALOGUE_MODE

_ALLOWED_MODULE_PREFIXES = ("health_engine.", "simulation.")


# ---------------------------------------------------------------------
# codec
# ---------------------------------------------------------------------

def encode(obj: Any):
    """Recursively encode to JSON-safe primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        arr = np.ascontiguousarray(obj)
        return {"__ndarray__": base64.b64encode(arr.tobytes()).decode("ascii"),
                "dtype": arr.dtype.str, "shape": list(arr.shape)}
    if isinstance(obj, deque):
        # maxlen must survive: it is the snapshot ring's cap, and a restored
        # buffer without it would grow without bound for the rest of the run.
        return {"__deque__": [encode(v) for v in obj], "maxlen": obj.maxlen}
    if isinstance(obj, (list, tuple)):
        return {"__seq__": [encode(v) for v in obj],
                "tuple": isinstance(obj, tuple)}
    if isinstance(obj, dict):
        return {"__map__": [[encode(k), encode(v)] for k, v in obj.items()]}
    if isinstance(obj, (set, frozenset)):
        return {"__set__": [encode(v) for v in obj]}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        cls = type(obj)
        return {"__dataclass__": f"{cls.__module__}.{cls.__qualname__}",
                "fields": {f.name: encode(getattr(obj, f.name))
                           for f in dataclasses.fields(obj)}}
    if hasattr(obj, "__dict__"):
        cls = type(obj)
        return {"__object__": f"{cls.__module__}.{cls.__qualname__}",
                "state": {k: encode(v) for k, v in vars(obj).items()}}
    raise TypeError(f"cannot serialise {type(obj).__name__}")


def _resolve(path: str):
    module, _, qualname = path.rpartition(".")
    if not any(module.startswith(p) for p in _ALLOWED_MODULE_PREFIXES):
        raise ValueError(
            f"refusing to load a class from outside this project: {path}")
    obj = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def decode(node: Any):
    """Inverse of `encode`."""
    if node is None or isinstance(node, (bool, int, float, str)):
        return node
    if isinstance(node, list):
        return [decode(v) for v in node]
    if not isinstance(node, dict):
        return node
    if "__ndarray__" in node:
        raw = base64.b64decode(node["__ndarray__"])
        return (np.frombuffer(raw, dtype=np.dtype(node["dtype"]))
                .reshape(node["shape"]).copy())
    if "__deque__" in node:
        return deque((decode(v) for v in node["__deque__"]),
                     maxlen=node.get("maxlen"))
    if "__seq__" in node:
        seq = [decode(v) for v in node["__seq__"]]
        return tuple(seq) if node.get("tuple") else seq
    if "__map__" in node:
        return {decode(k): decode(v) for k, v in node["__map__"]}
    if "__set__" in node:
        return {decode(v) for v in node["__set__"]}
    if "__dataclass__" in node:
        cls = _resolve(node["__dataclass__"])
        fields = {k: decode(v) for k, v in node["fields"].items()}
        try:
            return cls(**fields)
        except TypeError:
            # dataclasses with non-init fields (caches): build bare, populate
            obj = cls.__new__(cls)
            for k, v in fields.items():
                object.__setattr__(obj, k, v)
            return obj
    if "__object__" in node:
        cls = _resolve(node["__object__"])
        obj = cls.__new__(cls)
        for k, v in node["state"].items():
            setattr(obj, k, decode(v))
        return obj
    return {k: decode(v) for k, v in node.items()}


# ---------------------------------------------------------------------
# world <-> state
# ---------------------------------------------------------------------

def _seed_seq_state(rng) -> dict:
    """Everything needed to rebuild the generator's SeedSequence, including
    how many children it has already spawned."""
    ss = rng.bit_generator.seed_seq
    entropy = ss.entropy
    return {
        "entropy": int(entropy) if isinstance(entropy, (int, np.integer))
        else [int(e) for e in entropy],
        "spawn_key": [int(k) for k in ss.spawn_key],
        "pool_size": int(ss.pool_size),
        "n_children_spawned": int(ss.n_children_spawned),
    }


def _rng_from_seed_seq(info: dict):
    """
    A generator whose SeedSequence is restored *including* its spawn counter.

    `bit_generator.seed_seq` is read-only, so the sequence has to be supplied
    at construction; the draw state is then overwritten separately. The two
    are genuinely independent and both must be restored.
    """
    entropy = info["entropy"]
    ss = np.random.SeedSequence(
        entropy=entropy if isinstance(entropy, int) else tuple(entropy),
        spawn_key=tuple(info.get("spawn_key", ())),
        pool_size=int(info.get("pool_size", 4)),
        n_children_spawned=int(info.get("n_children_spawned", 0)),
    )
    return np.random.default_rng(ss)


def world_state(world, note: str = "") -> dict:
    """The complete state of a world, as JSON-safe primitives."""
    from .export import manifest
    return {
        "format": SAVE_FORMAT_VERSION,
        "manifest": manifest(world, note),
        "seed": int(world.seed),
        "tick": int(world.tick),
        # Which locus catalogue this world's genotypes mean anything under
        # (session 16). A genome is an array of dosages; the frequencies
        # that give those dosages meaning live in loci.py, and the
        # empirical flag changes them. Loading across modes would neither
        # raise nor warn -- every statistic would just quietly be wrong.
        "catalogue": _catalogue_mode(),
        "params": encode(world.params),
        "environment": encode(world.environment),
        # the bit-generator STATE, not the seed
        "rng_state": encode(world.rng.bit_generator.state),
        # ...AND the seed sequence, which is a separate thing entirely.
        #
        # `Generator.spawn()` advances the seed sequence's CHILD COUNTER and
        # deliberately leaves the bit-generator state untouched -- that is the
        # whole reason the engine uses it (inbreeding.derived_rng, roadmap
        # #31/#12). The consequence for saving is that `bit_generator.state`
        # does NOT contain the counter, so restoring state alone rewinds it to
        # zero and every subsequently spawned sub-generator is a different
        # stream. The world then continues with identical people, identical
        # births and identical draws -- and different inherited deleterious
        # load. Found exactly that way: the first divergence after a reload
        # was `load_carried` and `mean_viability`, five years in, with the
        # bit-generator states still equal.
        "rng_seed_seq": _seed_seq_state(world.rng),
        "id_counter": int(world._id),
        "name_seq": encode(world._name_seq),
        "people": encode(world.people),
        "living": [n.name for n in world.living],
        "meta": encode(world.meta),
        "history": encode(world.history),
        "lineage_history": encode(world.lineage_history),
        "registry": encode(world.registry),
        "pca": encode(world.pca),
        "snapshots": encode(world.snapshots),
        "chronicle": encode(world.chronicle),
        "deme_centers": encode(world.deme_centers),
        "territory_radius": float(world.territory_radius),
        "migration_flow": encode(world.migration_flow),
        "shock_queue": encode(getattr(world, "shock_queue", [])),
        "event_log": encode(getattr(world, "event_log", [])),
        "last_migrations": int(getattr(world, "_last_migrations", 0)),
    }


def build_world_save(world, note: str = "") -> bytes:
    """Gzipped JSON: complete enough to restore and keep stepping."""
    payload = json.dumps(world_state(world, note), separators=(",", ":"))
    return gzip.compress(payload.encode("utf-8"), compresslevel=6)


def load_world_save(blob: bytes):
    """
    Rebuild a `World` from `build_world_save` output.

    Constructed with ZERO founders, then every field replaced. Restoring into
    a freshly seeded world would leave the founders that world generated
    sitting in `people` alongside the loaded ones -- a duplication that would
    not raise, and would quietly corrupt every population statistic.
    """
    from .world import World

    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    if isinstance(blob, (bytes, bytearray)):
        blob = blob.decode("utf-8")
    state = json.loads(blob)

    fmt = state.get("format")
    if fmt != SAVE_FORMAT_VERSION:
        raise ValueError(f"unsupported save format {fmt!r}; this build reads "
                         f"version {SAVE_FORMAT_VERSION}")

    # Saves from before the flag existed are all synthetic-catalogue saves,
    # so a missing key defaults to "synthetic" and they keep loading.
    saved_mode = state.get("catalogue", "synthetic")
    if saved_mode != _catalogue_mode():
        raise ValueError(
            f"this save was made under the {saved_mode!r} locus catalogue "
            f"but the current process runs {_catalogue_mode()!r} "
            f"(EXTNPC_CATALOGUE). The genotypes are not comparable across "
            f"catalogues; restart with the matching mode to load it.")

    params = decode(state["params"])
    world = World(n_founders=0, seed=state["seed"], params=params)

    world.tick = int(state["tick"])
    world.environment = decode(state["environment"])
    # Restore the seed sequence FIRST (it can only be supplied at
    # construction), then overwrite the draw state on top of it. Doing only
    # the second is the subtle-corruption path described in `world_state`.
    seq = state.get("rng_seed_seq")
    if seq:
        world.rng = _rng_from_seed_seq(seq)
    world.rng.bit_generator.state = decode(state["rng_state"])
    world._id = int(state["id_counter"])
    world._name_seq = decode(state["name_seq"])
    world.people = decode(state["people"])
    world.meta = decode(state["meta"])
    world.living = [world.people[n] for n in state["living"]
                    if n in world.people]
    world.history = decode(state["history"])
    world.lineage_history = decode(state["lineage_history"])
    world.registry = decode(state["registry"])
    world.pca = decode(state["pca"])
    world.snapshots = decode(state["snapshots"])
    world.chronicle = decode(state["chronicle"])
    world.deme_centers = decode(state["deme_centers"])
    world.territory_radius = float(state["territory_radius"])
    world.migration_flow = decode(state["migration_flow"])
    world.shock_queue = decode(state["shock_queue"])
    world.event_log = decode(state["event_log"])
    world._last_migrations = int(state["last_migrations"])
    world.invalidate_pedigree()     # rebuilt lazily from the restored people
    return world
