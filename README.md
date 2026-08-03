# extNPC Health Engine

A reproduction, inheritance and medical-issues engine for the **extNPC** NPC
framework (Uludagli et al.), rebuilt on real quantitative genetics.

The goal is not a game system that *feels* genetic. It is a simulator whose
emergent output can be checked against the closed-form laws of population
genetics — and which says so honestly when it cannot.

**Version 0.5.0** · 133 tests passing · roadmap 30/32 items

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
python health_engine_prototype.py          # full engine demo, ~90 s, writes outputs/*.png
python health_engine_prototype.py --fast   # ~40 s smoke run (widened tolerances;
                                           #   a rare noise-floor FAIL is expected)
python -m pytest tests/ -q                 # 133 tests, ~76 s — the rigorous gate
python run_dashboard.py                    # live population sim at localhost:8050
```

The demo drives the **engine** on a hand-built nine-person pedigree. The
**population layer** (yearly turnover, demes, migration, lineages) and its
seven-tab dashboard are separate — that's `run_dashboard.py`.

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
| Wright's F_ST | between-deme differentiation vs migration | Wright 1931 |

### The invariant that holds it together

Every layer added after the Stage-0 foundation either draws from its **own**
RNG or draws strictly **after** all autosomal draws. A default world is
therefore bit-for-bit identical to the one the original heritabilities were
calibrated against. This is why 113 pre-existing tests survived the large
session-8 additions unchanged, and it is the first thing to preserve when
adding anything new.

In a stochastic simulator the RNG stream is effectively a global variable:
inserting one `rng.uniform()` upstream shifts every downstream draw and silently
decalibrates the model. Append-only draws plus private generators per feature is
the discipline that prevents it.

---

## Known limitations

Kept deliberately visible, per the project's scientific-honesty standard.

- **F_ST is biased upward at current deme sizes.** `simulation/community.py`
  uses Nei's G_ST, which does not correct for finite sample size. Measured
  against a null of four demes drawn from one shared allele-frequency vector
  (true F_ST = 0), the estimator returns ≈0.019 at 20 individuals per deme and
  ≈0.038 at 10. The isolated-islands result (≈0.10–0.14) is well clear of that
  floor, but the melting-pot figure (≈0.025) is not meaningfully above it.
  Weir & Cockerham's (1984) corrected estimator is the fix. Until then F_ST is
  validated by **ordering**, not by value, and the reported contrast between
  presets should be read as directional only.
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
- **Inbreeding depression is not fully modelled** — the kinship guard rejects
  close pairs, but no explicit fitness load scales with F.
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
| **2** — structural realism | 2, 3, 5, 6, 11, 12 done · **4, 13 open** | in progress |
| **3** — algorithms + validation | 29, 30, 32 done · **31 partial** | in progress |

**Open:** #4 genomic imprinting (IGF2 is positioned and flagged, not yet
parent-of-origin silenced), #13 developmental trajectory (life-stage gating of
expression), #31 inbreeding depression.

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
