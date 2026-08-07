# extNPC Health Engine

A reproduction, inheritance and medical-issues engine for the **extNPC** NPC
framework (Uludagli et al.), rebuilt on real quantitative genetics.

The goal is not a game system that *feels* genetic. It is a simulator whose
emergent output can be checked against the closed-form laws of population
genetics — and which says so honestly when it cannot.

**Version 0.5.0** · 264 tests passing · roadmap 32/32 items — engine complete

---

## What makes this different from a trait-blending system

> **Historical note — this section describes the *old* v0.2 prototype and why it
> was replaced. Everything it criticises was removed in July 2026 (Stage 0,
> session 1). It is here to show what the current engine does differently, not
> to describe the current engine.**

<details>
<summary><strong>The v0.2 prototype (removed) — click to expand</strong></summary>

v0.2 modelled inheritance with Simulated Binary Crossover, single-gene Mendelian
dominance, and a self-adaptive mutation sigma. Each is a defensible engineering
choice; none is how a genome works. The consequences were structural, not
cosmetic: one locus meant one trait, so no gene could affect two things; loci
assorted independently, so there was no linkage and no genome; and interpolating
a child's phenotype between its parents' meant heritability could not be a
parameter and selection response was simply wrong.

</details>

**The current engine — what replaced all of the above:**

| | |
|---|---|
| **Genome** | 22 autosomes with real centimorgan maps; meiosis draws crossovers as a Poisson process, so linked genes co-inherit |
| **Loci** | ~500 biallelic loci — ~50 named GWAS genes plus a peripheral background — feeding a sparse gene × trait weight matrix, so EDAR touches hair, teeth, ears, chin and sweat glands at once |
| **Phenotype** | P = additive + dominance + epistasis + G×E + environment, with variance components solved per trait to hit a target heritability |
| **Discrete traits** | Liability-threshold traits (Falconer 1965), not single-gene switches; expression is deterministic given the genome |
| **Epigenetics** | Lifetime-dynamic methylation with an epigenetic clock, and a germline firewall that resets ~95% of marks between generations |
| **Regulation** | A sparse gene→gene trans layer over 8 real TF hubs, so knocking out RUNX2 shifts traits it has no direct weight on |
| **Sex** | X/Y determination, hemizygosity, random X-inactivation (Lyon 1961), sex-limited expression |
| **Mitochondria** | Strict maternal transmission, heteroplasmy, an OXPHOS threshold, and the N_e=30 bottleneck |
| **Imprinting** | Parent-of-origin silencing at IGF2, so reciprocal heterozygotes — same genotype, opposite parent — differ by exactly 2·s·a |
| **Canalization** | Development is buffered; stress past a threshold releases cryptic genetic variation, raising variance as k² without moving the mean |
| **Body → mind** | A physiological state vector — hormones, interoception, allostatic load, circadian phase — emitting an action distribution for an LLM |

---

## Install

```bash
python -m pip install -r requirements.txt
```

Python **3.14.5** is what the suite is verified against. Dependencies are pinned
exactly rather than with `>=`, because the project's central claim is that a
seeded run is reproducible and numpy has changed RNG behaviour across minor
versions before.

## Run

```bash
python health_engine_prototype.py          # full engine demo, several minutes:
                                           #   validation harness + outputs/*.png
python health_engine_prototype.py --fast   # smoke run (widened tolerances;
                                           #   a rare noise-floor FAIL is expected)
python -m pytest tests/ -q                 # ~580 tests, ~12 min — the rigorous gate
python run_dashboard.py                    # live population sim at localhost:8050
```

The demo drives the **engine** on a hand-built nine-person pedigree. The
**population layer** (yearly turnover, demes, migration, lineages) and its
seven-tab dashboard are separate — that's `run_dashboard.py`.

```bash
EXTNPC_CATALOGUE=empirical python run_dashboard.py   # EXPERIMENTAL — see below
```

`EXTNPC_CATALOGUE=empirical` swaps 21 core genes' hand-set allele
frequencies for measured 1000 Genomes phase 3 EUR values (vendored with
provenance in `health_engine/data/`). The default is byte-identical to
every committed figure and pinned by test. The two modes are different
model versions: world saves record which one they were made under and
refuse to load across the boundary.

> **Empirical mode is experimental and must not be used for results.**
> Full suite under the flag: 6 failed / 574 passed / 3 skipped, against
> 582 passed / 1 skipped on the default. Real EUR frequencies change the
> *shape* of the genotypic distribution — `eye_color`'s kurtosis flips
> sign, −0.771 → +0.978 — and redistribute variance sharply for traits
> whose variance is concentrated in a few loci: SLC24A5 keeps its −1.80
> weight and loses 98.7% of its variance contribution, because at
> q = 0.997 there is nearly nothing left to vary. Tests asserting the
> synthetic architecture's shape then fail correctly. See the KNOWN
> FAILURES block in `health_engine/loci.py`.

```bash
python -m health_engine.catalogue_compare   # synthetic vs EUR, side by side
```

Runs the engine under both catalogues and prints a markdown table of what
moves and why — built for the thesis comparison. Costs two subprocess
imports; touches no figure and consumes no RNG.

> On Windows, two dev servers can both bind `:8050` and a stale process will
> silently serve old code. Kill every `:8050` listener before relaunching.

---

## Layout

```
health_engine/        the engine — everything below is per-individual genetics
  genetic_map.py        22 autosomes, physical (Mb) and genetic (cM) maps
  loci.py               ~50 named GWAS genes + ~450 peripheral SNPs
  genome.py             diploid genome, meiosis with crossover, mutation
  traits.py             genotype -> phenotype: A + D + I + GxE + E
  npc.py                the individual: genome + persistent deviates + life
  epigenome.py          lifetime-dynamic methylation, clock, germline firewall
  grn.py                gene-regulatory / omnigenic network
  sexchrom.py           X-linked, X-inactivation, sex-limited inheritance
  mito.py               maternal inheritance, heteroplasmy, bottleneck
  imprint.py            genomic imprinting: parent-of-origin silencing
  canalize.py           developmental buffering, cryptic variation release
  physiology.py         physiological state vector, hormones, action bias
  medical.py            acquired, non-heritable conditions
  mating.py             life-partner selection (greedy baseline)
  legacy.py             v0.2 operators (SBX, n-point crossover), kept for comparison
  validation.py         the harness: HWE, Haldane, h^2, breeder's, PGS, ...
  viz.py                figures

simulation/           the population layer — many individuals over time
  world.py              yearly turnover: birth, pairing, ageing, death
  demography.py         Gompertz mortality, fertility, Gale-Shapley matching
  community.py          Wright island model: demes, migration, F_ST
  pedigree.py           pedigree graph + kinship
  lineage.py            founder-ancestry lineage colours
  events.py             shocks: plague, famine, bottleneck
  chronicle.py          narrates notable events from the metrics stream
  metrics.py, embedding.py

dashboard/            live Plotly/Dash command deck (7 tabs) + canvas RTS map
tests/                133 tests
reads/                CLAUDE_PROJECT_ROADMAP.md (the spec) and REPORT.md (the log)
outputs/              validation figures, regenerated by the demo
```

---

## The validation harness

This is the part that matters scientifically. Nothing in the engine computes
these laws; they are measured from emergent output and compared to theory.

| Law | Checks | Source |
|---|---|---|
| Hardy–Weinberg proportions | genotype frequencies under random mating | Hardy 1908; Weinberg 1908 |
| Haldane's map function | recombination fraction vs map distance, 40 locus pairs | Haldane 1919 |
| Midparent–offspring regression | slope ≈ h² per trait | Falconer & Mackay 1996 |
| Breeder's equation | selection response ≈ h² × S | Lush 1937 |
| Daetwyler's law | PGS accuracy vs training N and marker count | Daetwyler et al. 2008 |
| Allele-frequency drift | variance vs 2N_e expectation | Wright 1931 |
| X-linked epidemiology | colour blindness at q in males, q² in females (8% / 0.8%) | Lyon 1961 |
| mtDNA bottleneck | offspring heteroplasmy variance = h(1−h)/N_e | Wallace 1999 |
| Reciprocal-heterozygote gap | imprinted-locus parent-of-origin effect = 2·s·a | DeChiara et al. 1991 |
| Cryptic-variation release | Var(z) = k²·V_gen + V_env past the buffering threshold | Waddington 1942 |
| Wright's F_ST | between-deme differentiation vs migration | Wright 1931; Weir & Cockerham 1984 |
| Lethal equivalents | ln S(F) = ln S₀ − B·F, B recovered by regression | Morton, Crow & Muller 1956 |
| Directional dominance | M_F − M₀ = −F·Σⱼ2pⱼqⱼdⱼ; −1.2 cm of stature per 10% F | Falconer & Mackay 1996; Joshi et al. 2015 |
| Malécot kinship | pedigree coefficients to machine precision | Malécot 1948; Wright 1922 |
| CNV dosage response | shift = (copies/2 − 1)·Σⱼ E[valⱼ]; deletion/duplication mirror | Jacquemont et al. 2011 |
| Developmental identity | age schedule is *exactly* 1.0 at the calibration age | — |
| Growth curve | fraction of adult stature vs age, rms 0.0014 | Preece & Baines 1978; Tanner 1962 |

### The invariant that holds it together

Every layer added after the Stage-0 foundation either draws from its **own**
RNG or draws strictly **after** all autosomal draws. A default world is
therefore identical to the one the original heritabilities were calibrated
against. This is why 113 pre-existing tests survived the large session-8
additions unchanged, and it is the first thing to preserve when adding
anything new.

In a stochastic simulator the RNG stream is effectively a global variable:
inserting one `rng.uniform()` upstream shifts every downstream draw and silently
decalibrates the model. Append-only draws plus private generators per feature is
the discipline that prevents it.

**Two strengths of that claim, and the difference matters.** The tail-draw
layers — sex chromosomes (#2) and mitochondria (#3) — consume from the
*caller's* generator. Founder #0 is then byte-identical, but the extra draws
advance the shared stream, so founder #1 onward is not. Their invariant is
therefore **per-individual, not per-sequence**: any loop drawing N founders
from a single generator drifted when those layers landed, which is why seven
committed figures changed on regeneration in session 9. Statistically
harmless — the founders are still drawn from the same distribution — but the
claim has to be stated at the strength it actually holds, and a thesis
methods section should say "per individual".

The layers added in session 11 — the recessive load (#31) and copy number
(#12) — do not carry that caveat. They draw from a **spawned sub-generator**
(`inbreeding.derived_rng`): `numpy.random.Generator.spawn` advances the
parent's *seed sequence* while leaving its bit-generator state alone, so the
caller's stream is byte-identical and the invariant holds **per sequence**.
All 175 pre-existing tests passed unchanged when those two layers were added,
with no expected value touched. The same one-line change would retrofit onto
#2 and #3; it has not been applied there, because doing so would rewrite
every figure and expectation seeded through them to fix a drift that is
harmless.

---

## Known limitations

Kept deliberately visible, per the project's scientific-honesty standard.

- ~~**F_ST is biased upward at current deme sizes.**~~ **Fixed in session 11.**
  `simulation/community.fst` now implements the Weir & Cockerham (1984)
  estimator it had been citing while actually computing Nei's G_ST. Against a
  null of four demes drawn independently from one shared allele-frequency
  vector (true F_ST = 0), the old estimator returned ≈0.038 at 10 individuals
  per deme and ≈0.019 at 20; the new one returns 0.000 ± 0.002 at every size
  tested, and recovers a Balding–Nichols target of 0.05 to within 0.001. The
  correction matters: under the fixed estimator the melting-pot preset falls
  from ≈0.025–0.058 to **0.010** (negative on some seeds, as an unbiased
  estimator should be when there is nothing to find) while isolated islands
  hold at **0.095**, so the contrast between presets is *larger* than it
  looked, not smaller. F_ST is no longer clipped at zero — clipping would
  reintroduce the bias. The old estimator is retained as `fst_gst` so the
  comparison is checked by a test rather than remembered.
- **PGS do not transfer across ancestries.** Allele frequencies here are
  neutral placeholders, not ancestry-specific; nothing in this model licenses
  cross-population comparison.
- **Candidate-gene → behaviour links are contested.** COMT/MAOA/5-HTTLPR-style
  single-SNP behavioural switches largely failed to replicate (Border et al.
  2019). Genetic variation here sets only modest polygenic priors on hormone
  and receptor-sensitivity parameters.
- **The omnigenic core/peripheral split is an engineering device**, not settled
  biology — Wray et al. 2018 argue it understates real complexity.
- **Resource stratification is a stylized family-wealth proxy** by lineage
  headcount. It is not an economic model and emphatically not a gene-for-status
  claim.
- **Migration is isolation-by-distance on a static settlement layout**, not a
  stepping-stone lattice; settlements never move or get founded.
- **Only one locus is imprinted.** Humans have ~100–200; the catalogue contains
  exactly one genuinely imprinted gene (IGF2), and adding more would change
  `N_LOCI` and invalidate every calibrated heritability. Imprinting here is also
  whole-body, where real imprinting is tissue- and stage-specific.
- **The canalization capacity is not calibrated against human data**, because
  no such data exists — the HSP90 capacitor experiments are qualitative and in
  flies and plants. What is tested is Waddington's *qualitative* claim
  (buffered below threshold, released above) plus internal k² consistency. Do
  not read the magnitude as an empirical estimate. Canalization here also
  cannot evolve: buffering capacity is a per-trait constant, not a heritable
  modifier, which is precisely what Waddington's selection experiments were
  about.
- **Directional dominance covers two traits, not all of them.** Inbreeding now
  costs both viability (1.4 lethal equivalents per gamete) *and* stature:
  `height_cm` and `lung_capacity` are calibrated to Joshi et al. 2015 (−1.2 cm
  and −137 ml per 10% F) with `V_D` as an output of the calibration rather than
  an input. Four traits Joshi tested and found nothing in — BMI, adiposity,
  blood pressure, lipids — are deliberately left flat, so the model reproduces
  the paper's nulls as well as its positives. But every *other* trait is
  **uncalibrated in this respect, not calibrated to zero**: what
  `inbreeding.directional_dominance()` returns for them is the small residual
  of `loci.py`'s random-sign dominance ratios. `lung_capacity` carries a second
  caveat — Joshi measured FEV1, a timed volume, while this trait is a generic
  spirometric capacity, and reproducing the slope costs `V_D = 0.11` because
  only 82 loci carry it. Sign and mechanism are real; the magnitude is
  indicative.
- **The load spectrum does not evolve.** A world that inbreeds heavily for
  many generations should *purge* some of its recessive load (Crnokrak &
  Barrett 2002). Transmitted genotypes drift, but `SPECTRUM.q` — and hence the
  predicted B — stays at its founding value throughout.
- **CNVs model dosage, not loss of function.** The copy-number multiplier
  (#12) scales a locus's genotypic *deviation*, not its absolute gene product,
  so the magnitude of a dosage effect and the mirror symmetry between a
  deletion and its reciprocal duplication are exact, while the *direction* of
  a loss-of-function phenotype is not modelled. The worked example is in
  `cnv.py`: 15q11–q13 deletion patients are hypopigmented, and the engine
  gets that sign wrong for exactly this reason. There is also no hemizygous
  unmasking of the allele opposite a deletion.
- **Development varies in endpoint, not in tempo.** Every NPC travels the same
  normalised growth curve (#13) toward its own genetic adult stature, so the
  model cannot produce early and late maturers — and therefore cannot show the
  variance spike during puberty that makes adolescent height so dispersed. The
  developmental schedule is also applied to the *output* of `phenotype()`
  rather than inside it; that is what makes the calibration structurally safe,
  but it means age never feeds back into the genotype→phenotype map.
- **The physiological state vector has never been connected to a live LLM.** It
  emits `to_prompt()` and `action_distribution()`, validated by KL divergence
  between states, but nothing consumes them yet.

---

## Roadmap status

Tracked against `reads/CLAUDE_PROJECT_ROADMAP.md` (32 items, 3 thrusts).
Per-session detail is in `reads/REPORT.md`.

| Stage | Items | Status |
|---|---|---|
| **0** — foundation | 1, 7, 9, 10, 29, 32 | complete |
| **1** — headline requests | 15–20, 21–27, 8 | complete |
| **2** — structural realism | 2, 3, 4, 5, 6, 11, 12, 13, 14 | complete |
| **3** — algorithms + validation | 29, 30, 31, 32 | complete |

**The roadmap is closed.** Session 11 landed the last three items: #31
inbreeding depression (`inbreeding.py`), #12 structural variants
(`cnv.py`) and #13 developmental trajectory (`development.py`).

What remains is not roadmap work. It is the scientific debt listed under
[Known limitations](#known-limitations) — session 15 closed the largest item,
directional dominance, so inbreeding now shortens people as well as killing
them — and the one genuinely open question: **`PhysiologicalState` has never
driven a live LLM.** `to_prompt()` and `action_distribution()` are validated by KL
divergence between states, but nothing consumes them. That is the gap between
"a genetics simulator" and "a genetics simulator that demonstrably changes how
an agent behaves."

---

## Figures

Regenerated by `python health_engine_prototype.py` into `outputs/`.

| File | Shows |
|---|---|
| `recombination_haldane.png` | Simulated recombination fraction vs Haldane's map function |
| `heritability_validation.png` | Midparent–offspring regression vs theoretical h² |
| `pleiotropy_matrix.png` | Core gene × trait weight matrix, EDAR outlined |
| `pedigree_relatedness.png` | Realised genomic relatedness (GCTA) across the pedigree |
| `family_ocean_radars.png` | OCEAN profiles, founders dashed vs offspring solid |
| `epigenetics.png` | Smoking→AHRR trajectory, epigenetic clock, germline firewall |
| `physiology.png` | Action distributions by state, HPA axis over a day, EDAR→behaviour |
| `grn_network.png` | RUNX2 knockout syndrome and its downstream program |
| `sex_linked.png` | Colour-blindness q vs q², G6PD mosaicism, sex-limited alopecia |
| `mito_inheritance.png` | OXPHOS threshold, mtDNA bottleneck vs closed form |
| `imprinting.png` | Reciprocal heterozygotes, the 2·s·a law, and the population effect |
| `canalization.png` | Variance flat while the buffer holds, then released; same mean, wider spread |
| `inbreeding_depression.png` | ln S vs pedigree F recovering B; realised vs expected F; hidden load exposed |
| `cnv_dosage.png` | Linear mirror-symmetric dosage response; emergent mutation–selection balance |
| `development.png` | Individual growth to a genetic endpoint; Preece–Baines vs Tanner; the identity at age 20 |

The `dashboard_*.png` files are captures of the live dashboard, not engine
output, and are not regenerated by the demo.

---

## Assets

Terrain art is Kenney's "Tiny Town" (CC0) — see
`dashboard/assets/sprites/tiny_town_LICENSE.txt`. The villager sprite sheet is
authored here and regenerable via
`dashboard/assets/sprites/make_villager.py` (requires Pillow); it is also CC0.

## Citation

This engine is the foundation of an in-progress thesis. If you use it, please
cite the extNPC framework paper (Uludagli et al.) alongside this repository.
