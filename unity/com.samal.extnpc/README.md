# extNPC World Viewer — Unity package

Reads a world bundle exported by the extNPC health engine and shows it.

**This package is a viewer.** It performs no biology, draws no random numbers,
and derives no phenotype. If a number reaches the screen there is a CSV cell it
came from. Anything the engine did not export is not available here, and the
correct fix for that is to export it from the engine — never to compute it in
C#. See `reads/UNITY_PLAN.md` Part 0 for the full contract.

## Requirements

- **Unity 6** (`6000.0` minimum, so it installs on 6.1 as well as 6.3).
  Nothing in this package needs a 6.3-only API.
- `com.unity.nuget.newtonsoft-json` (declared as a dependency).

**Which editor to use.** Unity 6.3 LTS is supported to Dec 2027 and is the
right target for a project meant to last; 6.0 LTS ended support in Oct 2026.
6.1 (a tech-stream release) works fine for this package today. The 2022.3
installs will *not* work — the manifest requires Unity 6.

## Install

Add to your project's `Packages/manifest.json`:

```json
"com.samal.extnpc": "file:../../extNPC_health_engine/unity/com.samal.extnpc"
```

or *Window → Package Manager → + → Add package from disk…*

## Getting a world

From the engine repository root:

```bash
python export_for_unity.py --years 90 --founders 16 --demes 3 --migration 0.08
```

That writes `outputs/unity/demo/`. Two ways to point Unity at it:

- set `ExtNpcWorldLoader.absolutePathOverride` to the absolute path
  (convenient while iterating — no copying), or
- copy the folder to `Assets/StreamingAssets/extnpc/<worldName>/` and set
  `worldName`.

Then add an `ExtNpcWorldLoader` to a scene and press play. The console prints
(actual output from that demo bundle on Unity 6000.1.6f1):

```
[extNPC] loaded 109 people (68 living) · 91 years · 91 frames / 4,111 rows ·
         seed 7 · year 90 · catalogue synthetic · commit 5522176 · 76 ms
```

*Window → extNPC → Bundle Inspector* shows the same provenance without
entering play mode.

## What is in a bundle

| File | Contents |
|---|---|
| `manifest.json` | provenance: commit, seed, **catalogue**, schema, frame coverage, caveats |
| `people.csv` | every individual who ever lived — **cross-sectional**, dead included |
| `history.csv` | population scalars per year |
| `pedigree.csv` | parent–child edges |
| `frames.csv` | **living villagers per year** — the viewer's primary feed |
| `demes.csv` | settlements per year |
| `flows.csv` | migration routes per year (empty with one deme — correctly) |
| `events.csv` | shocks, plagues, bottlenecks |

## Three limits you cannot code around

Inherited from `simulation/snapshots.py`, which states them itself. The viewer
must surface these, not paper over them.

1. **Frames hold the living only.** A death is a disappearance, not a row.
2. **The engine's frame ring is capped** (600 years). A longer run loses its
   earliest years. Check `Manifest.Frames.Truncated` before labelling a
   timeline as starting at year 0 — the loader logs a warning when it is set.
3. **Frames carry ~18 scalars, not genomes.** For a past year you can see who
   was alive, where they stood and their headline stats. A dead villager's
   genetic character sheet is *not* recoverable. Deep inspection is for the
   living, from `people.csv`.

## Two rules worth knowing before you extend it

**Colour is parsed, never recomputed.** The lineage colour rule — hue by
founder, saturation by ancestry purity, value by alive/dead — lives in
`simulation/lineage.py` and travels in the data as `#rrggbb`. A C#
reimplementation would be a second definition that drifts, and the dashboard
and the viewer would eventually colour the same villager differently. A test in
the engine repo (`tests/test_unity_contract.py`) fails if `HSVToRGB` appears
here.

**`height` is not `trait_height_cm`.** `frames.csv` carries the stature
expressed *at that age*; `people.csv` carries the *mature* phenotype. Reaching
for the wrong one draws children adult-sized — the exact defect session 13
found in the dashboard's BMI readout. Also tested.

## Division of labour with the dashboard

The Dash dashboard keeps every chart, distribution, validation figure and
thesis plot. This package does agents in space, time, and later bodies —
things a chart cannot show. Neither reimplements the other; both read the same
bundle so they cannot disagree about a villager.

## Testing

`Tests/` runs in Unity's Test Runner and covers the CSV dialect, locale-proof
number parsing, and manifest handling.

The column contract is tested from the *engine* side instead, in
`tests/test_unity_contract.py`: it reads this package's source as text and
asserts every column it asks for exists in a real export. A column-name typo
compiles fine and fails only at runtime on a machine with Unity — so it is
checked where it can be checked cheaply, in the normal pytest run.

## Licence note

MPFB2 (planned for Phase B character generation) is **GPLv3 code with CC0
assets**. Its generated meshes ship freely; its code must never be vendored
into this package. Blender + MPFB stay build-time tools on the developer's
machine. UMA, if adopted, is MIT and *may* ship here.
