<h1 align="center">extNPC World Viewer</h1>

<p align="center"><em>Reads a world bundle exported by the extNPC health engine, and shows it.</em></p>

<p align="center">
  <img alt="unity" src="https://img.shields.io/badge/unity-6000.0%2B-4ea3ff">
  <img alt="tests" src="https://img.shields.io/badge/tests-34%20passing-0ca30c">
  <img alt="upm"   src="https://img.shields.io/badge/UPM-com.samal.extnpc-1a1a19">
</p>

---

**This package is a viewer.** It performs no biology, draws no random numbers,
and derives no phenotype. If a number reaches the screen there is a CSV cell it
came from. Anything the engine did not export is not available here, and the
correct fix for that is to export it from the engine — never to compute it in
C#. See `reads/UNITY_PLAN.md` Part 0 for the full contract.

Those are not aspirations. A test in the engine repo fails if `HSVToRGB`
appears anywhere in this package, if any runtime file touches `Random`, if a
number is parsed without `InvariantCulture`, or if the viewer reaches for
`people.csv`'s mature stature where the frame's age-expressed value belongs.

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
| `demes.csv` | settlements per year, with the settlement's `label` |
| `flows.csv` | migration routes per year (empty with one deme — correctly) |
| `events.csv` | shocks, plagues, bottlenecks |
| `diseases.csv` | the Mendelian panel as a **reference table** — slug → gene, name, OMIM, citation |

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

**Wording lives in `InspectorFormat.cs`, and only there.** Every label, unit,
rounding rule and colour threshold the inspector uses names the
`dashboard/inspector.py` line it mirrors. Do not format a number at a call
site: `tests/test_unity_contract.py` compares that file's tables against the
Python source directly, and a threshold changed on one side only is a red
test rather than a quiet disagreement. The trap worth knowing about — Python's
`f"{p:.0%}"` renders `50%`, C#'s `ToString("P0", InvariantCulture)` renders
`50 %`. Mirroring a formatter means mirroring its *output*, not calling the
method with a similar name.

## The inspector (Stage 4)

`VillagerInspector` draws the selected villager as an IMGUI panel and works in
two modes, loudly:

- **Live year** — headline stats from `frames.csv` plus the deep sheet from
  `people.csv`: realised F, hidden and expressed load, named Mendelian
  diagnoses (`dx GJB2` → *GJB2 nonsyndromic deafness*, resolved through
  `diseases.csv`), carrier status, heterozygosity, conditions, and the 25
  `trait_*` mature phenotypes.
- **Any earlier year** — frame fields only, behind a `⏱ historical view`
  banner. `people.csv` is *cross-sectional*: joining it to a past frame would
  describe a year-40 villager with year-90 genetics and show no seam. The
  banner exists so a thinner panel reads as *a year with less recorded*, not
  *a villager with less going on*.

## Numbers are parsed at the width Python holds them

Every column this package **prints** is parsed with `CsvParse.Double`, not
`CsvParse.Float`. Geometry (`x`, `y`) stays float because it is never shown as
text.

This is not tidiness. Python holds these values as binary64 and formats from
that; parsing the same text into binary32 gives a slightly different number,
and at a rounding boundary the two print different text. Measured on a 40-year
export, **77 of 1323 `stress` values and 64 of 1323 `aerobic` values** rendered
differently in the viewer than in the dashboard:

```
stress  "-1.385"  ->  float64 -1.39   float32 -1.38
aerobic "39.305"  ->  float64  39.30  float32  39.31
```

`snapshots.py` rounds those columns to three decimals and the drawer prints
two, so an exact 3-dp midpoint is the *ordinary* case rather than an exotic
one. Both numbers look right, and the parity fixture could not see it: the
formatters were correct on both sides — they were being handed different
numbers.

## Division of labour with the dashboard

The Dash dashboard keeps every chart, distribution, validation figure and
thesis plot. This package does agents in space, time, and later bodies —
things a chart cannot show. Neither reimplements the other; both read the same
bundle so they cannot disagree about a villager.

## Testing

`Tests/` runs in Unity's Test Runner and covers the CSV dialect, locale-proof
number parsing, manifest handling, and the inspector's formatters.

**Unity will not run them until the project opts in.** Tests inside a *package*
are invisible to the Test Runner unless the consuming project lists the package
in `testables`, as a sibling of `dependencies` in `Packages/manifest.json`:

```json
"testables": [ "com.samal.extnpc" ]
```

Without it the Test Runner reports **`total="0" result="Passed"`** — zero tests,
green. That is the most dangerous possible output: it is indistinguishable at a
glance from a suite that ran and passed, and it is what you get by default. If
the EditMode list does not show an `ExtNPC.Tests` node with ~35 tests under it,
nothing in this package has been checked, whatever colour the bar is.

`Tests/ParityFixture.generated.cs` is **generated** by
`tests/test_unity_parity_fixture.py` in the engine repo, from
`dashboard/inspector.py`'s real formatters. Every `Expected` string in it is
text the Dash drawer actually prints. `ParityFixtureTests.cs` replays all of it
against `InspectorFormat` — once normally, once under `de-DE`. Do not edit the
generated file; regenerate it with `EXTNPC_UPDATE_PARITY='<reason>'`, which
requires a reason of at least 12 characters and records it in the header.

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
