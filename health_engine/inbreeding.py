"""
Inbreeding: pedigree kinship and inbreeding depression (roadmap #31).
====================================================================

Two halves, and the engine already had only the first one.

**Detection** was done: `mating.is_close_kin` measures realised genomic
relatedness with the GCTA estimator and refuses pairings above a threshold.
**Depression** was not: nothing anywhere applied a fitness cost to an inbred
individual. An engine that avoids incest without ever saying what incest
costs is asserting a taboo, not modelling a mechanism. This module supplies
the cost, and the pedigree machinery to say how inbred anyone actually is.

1. Malecot kinship over the full pedigree
-----------------------------------------
The kinship coefficient f(x, y) is the probability that an allele drawn at
random from x and one drawn at the same locus from y are identical by
descent (Malecot 1948). It obeys a recursion over the pedigree:

    f(x, x) = 1/2 (1 + F_x)             F_x = f(mother_x, father_x)
    f(x, y) = 1/2 (f(m_x, y) + f(p_x, y))       x strictly younger than y
    f(x, y) = 0                                  x, y distinct founders

`F_x = f(mother, father)` is Wright's inbreeding coefficient: the
probability that an individual's two alleles at a locus are IBD. Founders
are assumed unrelated, which is the standard base-population convention and
is *exactly true* here -- `sample_founder_genome` draws every founder
haplotype independently, so there genuinely is no shared ancestry to miss.
That is a rare luxury; in real pedigree analysis the founder-unrelatedness
assumption is a known source of downward bias in F.

Note what F is and is not. It is an **expectation over meioses**, not a
measurement. Two full sibs' children both have pedigree F = 1/4, but their
realised genome-wide homozygosity differs, because Mendelian segregation is
a lottery (Franklin 1977; Hill & Weir 2011 give the variance). `Pedigree.
inbreeding` returns the expectation; `realised_inbreeding` measures what the
individual actually got. The engine can therefore show the gap, which is the
same expectation-versus-realisation theme as sib relatedness in npc.py.

2. Where inbreeding depression comes from
------------------------------------------
Not from the trait loci. Inbreeding depression is overwhelmingly caused by
**rare, partially recessive, deleterious alleles** held at low frequency by
mutation-selection balance -- not by the common variants that generate
quantitative trait variation (Charlesworth & Willis 2009). The two are
different classes of site, and conflating them is the commonest way to model
this wrongly.

There is a second reason it does not come from the trait loci: viability is
not a trait in the catalogue, and the traits that ARE in the catalogue depress
through a different route. Trait depression under inbreeding is exactly

    M_F - M_0 = -F * sum_j 2 p_j q_j d_j                    (Falconer 4th ed.)

which needs the dominance deviations to point the same way. Most of the
catalogue's ratios are drawn `N(0, 0.15)` -- random in sign -- so that sum is
a random walk about zero for most traits. The two traits with a measured
depression are calibrated to it directly (`TraitSpec.depression_per_10F`;
Joshi et al. 2015, *Nature* 523:459: ~1.2 cm of height and ~137 ml of FEV1
per 10% of F across 35 cohorts), which is `traits.py`'s business, not this
module's. `directional_dominance` and `predicted_depression` below read that
calibration back out.

The two layers answer different questions and are kept apart on purpose:
this module asks whether an inbred individual SURVIVES, the trait layer asks
how TALL it is if it does.

So the load lives in its own parallel layer, exactly as the sex chromosomes
(#2) and mitochondria (#3) do: a set of load loci that carry no trait weight,
are invisible in the outbred phenotype, and dominate the response to
inbreeding.

3. The law: lethal equivalents
-------------------------------
Morton, Crow & Muller 1956 (*PNAS* 42:855) wrote survival against inbreeding
as a log-linear model:

        ln S(F) = ln S_0 - B F

`B` is the number of **lethal equivalents per gamete**: the number of
deleterious alleles that would cause one death if made homozygous. It is not
fitted here -- it follows in closed form from the load spectrum,

        B = sum_j s_j p_j q_j (1 - 2 h_j)

and the validation harness recovers it by regressing observed survival on
pedigree F, which is the same procedure a human geneticist runs on a real
consanguinity study. Nothing in the transmission or viability code computes
B, so the recovery is non-circular.

Calibration
-----------
`TARGET_LETHAL_EQUIVALENTS = 1.4`, inside the ~1-2 lethal equivalents per
haploid genome that Charlesworth & Willis 2009 give for human survival to
adulthood. **Unlike the canalization capacity (#14b), this one has real
human magnitudes behind it.** The spectrum's per-locus mutation rate `u` is
then *solved* so that B hits the target exactly, rather than being asserted
-- and the solved value can be sanity-checked two independent ways:

  * u = 1.24e-4 per locus per gamete, against the engine's own independently
    derived `genome.LOCUS_MUTATION_RATE` = 1.8e-4 (Kong 2012, for loci of the
    same assumed 15 kb span). Same order, from a completely different anchor.
  * the implied genome-wide deleterious rate is U = 2Ku ~ 0.50 per diploid
    genome per generation, against Eyre-Walker & Keightley 1999's ~1.6 for
    humans. Low by construction -- 2000 load loci stand in for a much larger
    real mutational target -- but the right order.

What that predicts, and how it lines up with the data:

    F = 1/16 (first cousins)   survival x0.916   ->  8.4% excess mortality
    F = 1/8  (double 1st cous) survival x0.839   -> 16.1%
    F = 1/4  (full sibs)       survival x0.704   -> 29.6%

Bittles & Black 2010 (*PNAS* 107:1779) report ~3.5% excess *early-childhood*
mortality in first-cousin progeny. Our 8.4% is over the whole pre-adult
window, so the two are consistent if roughly 40% of pre-adult depression is
expressed before age five. State that plainly as a reconciliation, not as an
independent confirmation: it is the same 1-2 lethal-equivalent literature
underneath both numbers.

Determinism
-----------
This layer draws from a **spawned sub-generator**, not from the caller's
`rng` (see `derived_rng`). `Generator.spawn` advances the parent's seed
sequence without touching its bit-generator state, so the parent's stream is
byte-identical to what it was before this module existed, while the child
stream stays fully reproducible from the same seed.

That is strictly stronger than the tail-draw discipline sexchrom.py (#2) and
mito.py (#3) use. Those consume from the shared generator at the end of
`random_founder`, so founder #0 is unchanged but #1 onward shifts -- the
bit-for-bit claim there is per-individual, not per-sequence (session-9
audit). This layer has no such caveat, and the same technique would retrofit
onto the earlier two.

References
----------
Malecot 1948 (*Les mathematiques de l'heredite*) -- the kinship coefficient.
Wright 1922 (*Am. Nat.* 56:330) -- coefficients of inbreeding and relationship.
Morton, Crow & Muller 1956 (*PNAS* 42:855) -- lethal equivalents; ln S = A - BF.
Haldane 1937 (*Am. Nat.* 71:337) -- mutation load depends on U, not on s.
Bittles & Neel 1994 (*Nat. Genet.* 8:117) -- the costs of human inbreeding.
Bittles & Black 2010 (*PNAS* 107:1779) -- consanguinity, excess mortality.
Charlesworth & Willis 2009 (*Nat. Rev. Genet.* 10:783) -- the genetics of
inbreeding depression; the partially-recessive-deleterious explanation.
Simmons & Crow 1977 (*Annu. Rev. Genet.* 11:49) -- dominance of deleterious
mutations; severe mutations are more recessive.
Deng & Lynch 1996 (*Genetics* 144:349) -- the h-s relationship.
Eyre-Walker & Keightley 1999 (*Nature* 397:344) -- deleterious mutation rate.
Joshi et al. 2015 (*Nature* 523:459) -- directional dominance on stature.
Franklin 1977 (*Theor. Popul. Biol.* 11:60) -- variance of realised inbreeding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# ======================================================================
# 1. Pedigree kinship (Malecot)
# ======================================================================


class Pedigree:
    """
    Parent map plus memoised Malecot kinship.

    Built from anything that can name an individual and its two parents:
    a list of NPCs, a `simulation.World`, or explicit `add()` calls. An
    individual whose parents are absent from the pedigree is treated as a
    founder, which is what happens at the edge of any real family record.

    The recursion is evaluated with an explicit stack rather than by Python
    recursion: a long-running world builds pedigrees hundreds of generations
    deep, and `f(x, y)` bottoms out through the ancestors of both arguments,
    which overruns the default recursion limit well before it overruns memory.
    """

    __slots__ = ("_parents", "_depth", "_kin")

    def __init__(self) -> None:
        self._parents: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        self._depth: Dict[str, int] = {}
        self._kin: Dict[Tuple[str, str], float] = {}

    # ---- construction -------------------------------------------------

    def add(self, name: str, mother: Optional[str] = None,
            father: Optional[str] = None) -> None:
        """Register one individual. Unknown parents mark them as a founder."""
        self._parents[name] = (mother, father)
        self._depth.clear()
        self._kin.clear()

    @classmethod
    def from_npcs(cls, npcs: Iterable) -> "Pedigree":
        ped = cls()
        for npc in npcs:
            if npc.parents:
                ped._parents[npc.name] = (npc.parents[0], npc.parents[1])
            else:
                ped._parents[npc.name] = (None, None)
        return ped

    @classmethod
    def from_world(cls, world) -> "Pedigree":
        """Every individual the world has ever held, living or dead."""
        return cls.from_npcs(world.people.values())

    def __len__(self) -> int:
        return len(self._parents)

    def __contains__(self, name: str) -> bool:
        return name in self._parents

    # ---- structure ----------------------------------------------------

    def parents(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        m, f = self._parents.get(name, (None, None))
        # A parent outside the pedigree is not a parent we can trace.
        m = m if m in self._parents else None
        f = f if f in self._parents else None
        return m, f

    def is_founder(self, name: str) -> bool:
        m, f = self.parents(name)
        return m is None and f is None

    def depth(self, name: str) -> int:
        """
        Pedigree generation: 0 for founders, else 1 + max(parent depths).

        The recursion needs a partial order in which no individual can be its
        own ancestor; depth supplies one, and expanding the *deeper* argument
        guarantees termination without needing birth dates.
        """
        if name in self._depth:
            return self._depth[name]
        stack = [name]
        while stack:
            cur = stack[-1]
            if cur in self._depth:
                stack.pop()
                continue
            m, f = self.parents(cur)
            missing = [p for p in (m, f) if p is not None and p not in self._depth]
            if missing:
                stack.extend(missing)
                continue
            d = 0
            for p in (m, f):
                if p is not None:
                    d = max(d, self._depth[p] + 1)
            self._depth[cur] = d
            stack.pop()
        return self._depth[name]

    # ---- kinship ------------------------------------------------------

    def _deps(self, a: str, b: str) -> List[Tuple[str, str]]:
        """Sub-problems f(a, b) needs before it can be evaluated."""
        if a == b:
            m, f = self.parents(a)
            if m is None or f is None:
                return []
            return [_key(m, f)]
        # expand the younger (deeper) individual
        x, y = (a, b) if self.depth(a) >= self.depth(b) else (b, a)
        m, f = self.parents(x)
        if m is None and f is None:
            return []
        return [_key(p, y) for p in (m, f) if p is not None]

    def _combine(self, a: str, b: str) -> float:
        if a == b:
            m, f = self.parents(a)
            if m is None or f is None:
                return 0.5                       # founder: F = 0
            return 0.5 * (1.0 + self._kin[_key(m, f)])
        x, y = (a, b) if self.depth(a) >= self.depth(b) else (b, a)
        m, f = self.parents(x)
        if m is None and f is None:
            return 0.0                           # distinct founders: unrelated
        total = 0.0
        for p in (m, f):
            # A missing parent is an untraceable founder, contributing 0.
            total += self._kin[_key(p, y)] if p is not None else 0.0
        return 0.5 * total

    def kinship(self, a: str, b: str) -> float:
        """
        Malecot's f(a, b): P(two alleles drawn at random, one from each, are
        identical by descent). f(a, a) = 1/2 (1 + F_a), not 1.
        """
        root = _key(a, b)
        if root in self._kin:
            return self._kin[root]
        stack = [root]
        while stack:
            key = stack[-1]
            if key in self._kin:
                stack.pop()
                continue
            missing = [d for d in self._deps(*key) if d not in self._kin]
            if missing:
                stack.extend(missing)
                continue
            self._kin[key] = self._combine(*key)
            stack.pop()
        return self._kin[root]

    def inbreeding(self, name: str) -> float:
        """Wright's F: P(an individual's two alleles at a locus are IBD)."""
        m, f = self.parents(name)
        if m is None or f is None:
            return 0.0
        return self.kinship(m, f)

    def relationship(self, a: str, b: str) -> float:
        """
        Wright's coefficient of relationship, 2f -- the scale the engine's
        genomic estimator and `mating.DEFAULT_KINSHIP_THRESHOLD` live on.
        Full sibs and parent-offspring 0.5, first cousins 0.125.
        """
        return 2.0 * self.kinship(a, b)

    def inbreeding_table(self) -> Dict[str, float]:
        return {n: self.inbreeding(n) for n in self._parents}


def _key(a: str, b: str) -> Tuple[str, str]:
    """Canonical (order-independent) memo key for the symmetric f(a, b)."""
    return (a, b) if a <= b else (b, a)


# ======================================================================
# 2. The recessive deleterious load
# ======================================================================

# How many load loci the layer carries. These are NOT in the trait
# catalogue: they have no trait weights, no cM position and no bearing on
# any phenotype. They stand in for the genome-wide mutational target that
# real inbreeding depression comes out of.
N_LOAD_LOCI: int = 2000

# Lethal equivalents per gamete for survival to adulthood. Charlesworth &
# Willis 2009 put humans at ~1-2; this is the value the spectrum is solved
# against. See the module docstring for the two independent sanity checks
# on the mutation rate that solving it implies.
TARGET_LETHAL_EQUIVALENTS: float = 1.4

# Selection coefficients are drawn from a gamma distribution -- the standard
# shape for a distribution of fitness effects (Eyre-Walker & Keightley 2007),
# heavily weighted toward the nearly-neutral with a thin tail of lethals.
_DFE_SHAPE: float = 0.30
_DFE_SCALE: float = 0.20

# Floor on s. Below roughly 1/(2 Ne) an allele's frequency is set by drift,
# not by selection, so mutation-selection balance is the wrong model for it
# (Ohta 1973). 0.02 keeps 2 Ne s > 1 for any population this engine
# simulates, so every locus here is genuinely selected.
_S_MIN: float = 0.02
_S_MAX: float = 1.0

# Dominance falls as severity rises: mild mutations are near-additive, severe
# ones close to fully recessive (Simmons & Crow 1977; Deng & Lynch 1996).
_H_MAX: float = 0.50
_H_MIN: float = 0.02
_H_DECAY: float = 13.0

# Guard on the mutation-selection-balance frequency. At the default
# calibration it binds on ZERO loci -- asserted by a test -- so it is a
# safety rail, not a tuning knob.
_Q_MAX: float = 0.05

# Fixed seed: the spectrum is a calibrated constant of the engine, like the
# trait architecture, not something that varies run to run.
_SPECTRUM_SEED: int = 20260804


@dataclass(frozen=True)
class LoadSpectrum:
    """
    The population genetics of the load layer: per-locus deleterious allele
    frequency, homozygous selection coefficient, and dominance coefficient.

    Everything else in this module is a consequence of these three arrays.
    """
    q: np.ndarray                # (K,) deleterious allele frequency
    s: np.ndarray                # (K,) homozygous selection coefficient
    h: np.ndarray                # (K,) dominance coefficient (h=0 fully recessive)
    mutation_rate: float         # per locus per gamete, solved to hit B

    @property
    def n_loci(self) -> int:
        return int(self.q.size)

    @property
    def p(self) -> np.ndarray:
        return 1.0 - self.q

    @property
    def lethal_equivalents(self) -> float:
        """
        B = sum_j s_j p_j q_j (1 - 2 h_j), the slope of ln S against F.

        Only the *partially recessive* part of the load contributes: at
        h = 1/2 (pure additivity) the term vanishes, because making an
        additive allele homozygous costs exactly what carrying two
        heterozygous copies did. Inbreeding depression is a dominance
        phenomenon, and this factor is where that shows up.
        """
        return float(np.sum(self.s * self.p * self.q * (1.0 - 2.0 * self.h)))

    @property
    def baseline_load(self) -> float:
        """
        A = sum_j (s_j q_j^2 + 2 h_j s_j p_j q_j): the mutation load carried
        by an OUTBRED individual, i.e. -ln S at F = 0.

        Haldane 1937's result is that this depends on the mutation rate and
        not on s or h -- a population pays for its mutations at the rate it
        makes them, however severe each one is. `haldane_load` checks it.
        """
        return float(np.sum(self.s * self.q ** 2
                            + 2.0 * self.h * self.s * self.p * self.q))

    @property
    def deleterious_mutation_rate(self) -> float:
        """U: expected new deleterious mutations per diploid genome per gen."""
        return 2.0 * self.n_loci * self.mutation_rate

    @property
    def haldane_load(self) -> float:
        """1 - exp(-U): Haldane's mutation load, for comparison with `A`."""
        return float(1.0 - np.exp(-self.deleterious_mutation_rate))

    @property
    def expected_heterozygous_carried(self) -> float:
        """Deleterious alleles an average outbred individual carries hidden."""
        return float(np.sum(2.0 * self.p * self.q))

    def exact_log_survival(self, F: float) -> float:
        """
        ln E[w | F] without the log-linear approximation, by summing the exact
        per-locus mean fitness under inbred genotype frequencies:

            P(DD) = q^2 + F p q,  P(Dd) = 2 p q (1-F),  P(dd) = p^2 + F p q

        Morton's ln S = A - BF is the first-order expansion of this. The two
        agree to four decimals at the default spectrum, which is worth
        knowing: the log-linear model is an approximation that happens to be
        an extremely good one at human load levels, not an identity.
        """
        w = (1.0 - self.s * (self.q ** 2 + F * self.p * self.q)
             - 2.0 * self.h * self.s * self.p * self.q * (1.0 - F))
        return float(np.sum(np.log(w)))

    def expected_survival(self, F: float, relative: bool = True) -> float:
        """
        E[w | F], relative to an outbred individual by default.

        `relative=True` divides out the baseline mutation load, because that
        load is a constant every individual pays and is therefore already
        inside any demographic rate calibrated on real populations. What is
        left is the *differential* cost of being inbred, which is the only
        part that should be applied on top of an existing mortality model.
        """
        v = np.exp(self.exact_log_survival(F))
        if relative:
            v /= np.exp(self.exact_log_survival(0.0))
        return float(v)

    def summary(self) -> str:
        return (
            f"load spectrum: {self.n_loci} loci, u = {self.mutation_rate:.3e}/locus/gamete\n"
            f"  lethal equivalents per gamete  B = {self.lethal_equivalents:.4f}"
            f"   (target {TARGET_LETHAL_EQUIVALENTS})\n"
            f"  baseline mutation load         A = {self.baseline_load:.4f}"
            f"   (outbred survival {np.exp(-self.baseline_load):.3f})\n"
            f"  deleterious mutations / diploid genome / gen  U = "
            f"{self.deleterious_mutation_rate:.3f}\n"
            f"  Haldane load 1-exp(-U)         = {self.haldane_load:.3f}"
            f"   (vs A -> {1 - np.exp(-self.baseline_load):.3f})\n"
            f"  hidden deleterious alleles carried per individual = "
            f"{self.expected_heterozygous_carried:.1f}"
        )


def build_spectrum(n_loci: int = N_LOAD_LOCI,
                   target_B: float = TARGET_LETHAL_EQUIVALENTS,
                   seed: int = _SPECTRUM_SEED) -> LoadSpectrum:
    """
    Draw a distribution of fitness effects and solve for the per-locus
    mutation rate that puts the lethal-equivalent count on target.

    The order matters and is the point: s and h are drawn from the
    biological literature, and then the ONE free parameter -- the mutation
    rate -- is solved rather than chosen. That leaves a falsifiable
    consequence, because the solved rate has to be biologically plausible
    on its own terms, and it is (see the module docstring).

    Frequencies come from mutation-selection balance for a partially
    recessive allele, q = u / (h s) (Haldane 1937; valid while h s >> u,
    which the `_S_MIN` floor guarantees).
    """
    rng = np.random.default_rng(seed)
    s = np.clip(rng.gamma(_DFE_SHAPE, _DFE_SCALE, n_loci), _S_MIN, _S_MAX)
    h = np.clip(_H_MAX * np.exp(-_H_DECAY * s), _H_MIN, _H_MAX)

    def B_at(u: float) -> float:
        q = np.minimum(u / (h * s), _Q_MAX)
        return float(np.sum(s * (1.0 - q) * q * (1.0 - 2.0 * h)))

    # B is monotone increasing in u; bisect.
    lo, hi = 1e-9, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if B_at(mid) < target_B:
            lo = mid
        else:
            hi = mid
    u = 0.5 * (lo + hi)
    q = np.minimum(u / (h * s), _Q_MAX)
    return LoadSpectrum(q=q, s=s, h=h, mutation_rate=u)


# The engine's calibrated spectrum, built once at import.
SPECTRUM: LoadSpectrum = build_spectrum()


# ----------------------------------------------------------------------
# The per-individual layer
# ----------------------------------------------------------------------

@dataclass
class DeleteriousLoad:
    """
    An individual's deleterious-allele genotypes: (2, K) int8, 1 = the
    deleterious allele. Row 0 maternal, row 1 paternal, matching `Genome`.

    Load loci are treated as UNLINKED -- they stand for sites scattered over
    the whole genome, so independent segregation is the right default and
    linkage between them would be an invention. That also makes transmission
    a single vectorised Bernoulli draw.
    """
    haplotypes: np.ndarray            # (2, K) int8

    @property
    def dosage(self) -> np.ndarray:
        return self.haplotypes.sum(axis=0).astype(np.int8)

    @property
    def n_homozygous(self) -> int:
        """Load loci where BOTH copies are deleterious -- the ones that bite."""
        return int(np.count_nonzero(self.dosage == 2))

    @property
    def n_carried(self) -> int:
        """Deleterious alleles carried heterozygous, i.e. hidden."""
        return int(np.count_nonzero(self.dosage == 1))

    def copy(self) -> "DeleteriousLoad":
        return DeleteriousLoad(self.haplotypes.copy())

    def viability(self, spectrum: Optional[LoadSpectrum] = None) -> float:
        """
        Multiplicative viability across load loci:

            w = prod_j (1 - s_j x_j),   x_j = 1 if DD, h_j if Dd, 0 if dd

        Multiplicative rather than additive because independent causes of
        death compose that way, and because it cannot go negative however
        much load an individual carries.
        """
        sp = SPECTRUM if spectrum is None else spectrum
        g = self.dosage
        x = np.where(g == 2, 1.0, np.where(g == 1, sp.h, 0.0))
        return float(np.prod(1.0 - sp.s * x))

    def relative_viability(self, spectrum: Optional[LoadSpectrum] = None) -> float:
        """
        Viability divided by the outbred population mean.

        This is the number the simulation should use. The absolute figure
        includes the baseline mutation load every individual pays (~0.52 in
        log units, a 40% cost), which is already inside any demographic rate
        fitted to a real population; applying it again would double-count it
        and halve every cohort. Dividing it out leaves only the differential
        cost of inbreeding, which is what the engine does not yet have.
        """
        sp = SPECTRUM if spectrum is None else spectrum
        return self.viability(sp) / float(np.exp(sp.exact_log_survival(0.0)))


def derived_rng(rng: np.random.Generator) -> np.random.Generator:
    """
    An independent, reproducible generator that costs the parent NO draws.

    `Generator.spawn` advances the parent's *seed sequence* (a counter used
    only to make children) and leaves its bit-generator state alone, so every
    number the caller draws after this call is byte-identical to what it would
    have drawn if this layer did not exist. That is how a new layer gets added
    to `random_founder`/`reproduce` in this engine without the session-9
    caveat that tail draws shift founder #1 onward.

    Falls back to deriving a seed from the parent's state for exotic bit
    generators that carry no seed sequence -- also consuming nothing, though
    it would repeat if called twice at the same state.
    """
    try:
        return rng.spawn(1)[0]
    except (AttributeError, TypeError, ValueError):      # pragma: no cover
        state = rng.bit_generator.state
        return np.random.default_rng(abs(hash(repr(state))) % (2 ** 63))


def sample_founder_load(rng: np.random.Generator,
                        spectrum: Optional[LoadSpectrum] = None
                        ) -> DeleteriousLoad:
    """
    Founder genotypes under Hardy-Weinberg at the mutation-selection-balance
    frequencies. Each haplotype's allele is an independent Bernoulli(q), so
    founders are outbred (F = 0) by construction -- consistent with
    `Pedigree` treating them as unrelated, and with `sample_founder_genome`
    doing the same for the trait loci.
    """
    sp = SPECTRUM if spectrum is None else spectrum
    haps = (rng.random((2, sp.n_loci)) < sp.q).astype(np.int8)
    return DeleteriousLoad(haps)


def transmit_load(mother: DeleteriousLoad, father: DeleteriousLoad,
                  rng: np.random.Generator,
                  spectrum: Optional[LoadSpectrum] = None,
                  mutation: bool = True) -> DeleteriousLoad:
    """
    One meiosis per parent at unlinked loci, plus new deleterious mutation.

    Mutation is one-directional: reference -> deleterious at rate `u`, with no
    back-mutation. That asymmetry is the whole reason mutation-selection
    balance exists, and without it the load would erode away under selection
    within a few hundred generations of a simulated world.
    """
    sp = SPECTRUM if spectrum is None else spectrum
    k = sp.n_loci
    egg = mother.haplotypes[rng.integers(0, 2, k), np.arange(k)]
    sperm = father.haplotypes[rng.integers(0, 2, k), np.arange(k)]
    if mutation:
        egg = np.where(rng.random(k) < sp.mutation_rate, 1, egg)
        sperm = np.where(rng.random(k) < sp.mutation_rate, 1, sperm)
    return DeleteriousLoad(np.stack([egg, sperm]).astype(np.int8))


# ----------------------------------------------------------------------
# Purging: the load a population CURRENTLY carries, not the one it was
# founded with
# ----------------------------------------------------------------------

def realised_load_frequencies(loads: Sequence[DeleteriousLoad]) -> np.ndarray:
    """
    Per-locus deleterious allele frequency measured from a set of actual
    load genotypes: mean dosage over 2. A pure measurement -- no RNG, no
    mutation of anything -- of what the population segregates NOW.
    """
    if not loads:
        return np.array([])
    dosages = np.stack([ld.dosage for ld in loads]).astype(float)
    return dosages.mean(axis=0) / 2.0


def realised_lethal_equivalents(loads: Sequence[DeleteriousLoad],
                                spectrum: Optional[LoadSpectrum] = None,
                                unbiased: bool = True) -> float:
    """
    B evaluated at the population's REALISED allele frequencies:

        B_t = sum_j s_j p_hat_j q_hat_j (1 - 2 h_j)

    `SPECTRUM.lethal_equivalents` is the founding value and never moves;
    this is what the same closed form says about the load the living
    actually carry. The gap between the two is the engine's purging
    read-out: a population that inbreeds exposes rare recessives as
    homozygotes, selection removes them, and the frequencies -- hence B --
    fall (Crnokrak & Barrett 2002; Hedrick & Garcia-Dorado 2016). s and h
    stay the founding constants because purging changes how COMMON each
    allele is, not what it does.

    THE SAMPLE-SIZE BIAS, and why it is corrected by default
    -------------------------------------------------------
    `p_hat q_hat` is a plug-in estimate of `pq`, and it is biased DOWNWARD,
    because a finite sample of 2n gametes underestimates heterozygosity:

        E[p_hat q_hat] = p q (1 - 1/(2n))                 (Nei 1978)

    So a naive B_hat is low by 1/(2n) -- 5% in a 10-founder cohort -- and
    a founding population would appear to have "already purged" before a
    single child was born. Measured across 60 replicate cohorts against the
    true B = 1.400, the naive estimator gives 0.958 of it at n = 10, 0.977
    at n = 20, 0.989 at n = 50 and 0.998 at n = 200: the predicted
    1 - 1/(2n) to three decimals. `unbiased=True` applies the standard
    2n/(2n-1) correction, which is the same lesson session 11 learned when
    G_ST was replaced by Weir & Cockerham's estimator -- a bias that scales
    with sample size will be read as a biological trend in exactly the
    small populations this engine simulates. `unbiased=False` is kept so
    the comparison is testable rather than remembered.

    Residual NOISE is separate from bias and is not correctable: the
    standard deviation across replicate cohorts is ~0.13 at n = 10, ~0.06
    at n = 50 and ~0.03 at n = 200. In a village of ~50 a single-tick move
    of 0.05 is noise.

    And a confound the caller must not forget: in a SMALL population, B
    also falls because drift loses rare alleles, which is not purging.
    Only law [9e], with its large random-mating control, separates the two.
    """
    if not loads:
        return 0.0
    sp = SPECTRUM if spectrum is None else spectrum
    q_hat = realised_load_frequencies(loads)
    pq = (1.0 - q_hat) * q_hat
    if unbiased:
        n_gametes = 2 * len(loads)
        if n_gametes > 1:
            pq = pq * n_gametes / (n_gametes - 1.0)
    return float(np.sum(sp.s * pq * (1.0 - 2.0 * sp.h)))


# ======================================================================
# 3. Closed forms the validation harness checks against
# ======================================================================

def lethal_equivalents(spectrum: Optional[LoadSpectrum] = None) -> float:
    """B, the slope of ln S against F. See `LoadSpectrum.lethal_equivalents`."""
    return (SPECTRUM if spectrum is None else spectrum).lethal_equivalents


def predicted_log_survival(F: np.ndarray | float,
                           spectrum: Optional[LoadSpectrum] = None,
                           relative: bool = True) -> np.ndarray:
    """
    Morton's model, ln S(F) = ln S_0 - B F, evaluated on an array of F.
    `relative=True` sets ln S_0 = 0 so the curve starts at the outbred mean.
    """
    sp = SPECTRUM if spectrum is None else spectrum
    F = np.asarray(F, dtype=float)
    intercept = 0.0 if relative else -sp.baseline_load
    return intercept - sp.lethal_equivalents * F


def excess_mortality(F: float, spectrum: Optional[LoadSpectrum] = None) -> float:
    """
    Fractional excess mortality of an inbred cohort relative to an outbred
    one: 1 - S(F)/S(0). At F = 1/16 this is the first-cousin figure the
    consanguinity literature reports.
    """
    sp = SPECTRUM if spectrum is None else spectrum
    return 1.0 - sp.expected_survival(F, relative=True)


def first_cousin_excess_mortality(spectrum: Optional[LoadSpectrum] = None) -> float:
    """Excess mortality at F = 1/16, the most-reported human benchmark."""
    return excess_mortality(0.0625, spectrum)


def realised_inbreeding(npc) -> float:
    """
    F measured from the genome the individual actually got, rather than
    predicted from its pedigree:

        F_realised = 1 - H_observed / H_expected

    with H_expected the catalogue's mean heterozygosity under Hardy-Weinberg.
    This is the excess-homozygosity estimator (Wright 1922; the F_hat of
    modern ROH work). It scatters around the pedigree value because meiosis
    is a lottery, and it can go negative for an individual who happened to
    inherit an unusually heterozygous genome.
    """
    from .loci import HETEROZYGOSITY
    expected = float(np.mean(HETEROZYGOSITY))
    if expected <= 0.0:
        return 0.0
    return 1.0 - npc.genome.heterozygosity() / expected


def directional_dominance(trait: str) -> float:
    """
    The trait-scale inbreeding depression the CATALOGUE predicts:

        M_F - M_0 = -F * sum_j 2 p_j q_j d_j

    Returns `sum_j 2 p_j q_j d_j`, in liability SD per unit F, positive when
    inbreeding LOWERS the trait (Falconer & Mackay 1996 eq. 15.1).

    Two regimes, and the number means something different in each:

      * A trait calibrated against a measured depression (`TraitSpec.
        depression_per_10F` -- height_cm, lung_capacity) returns exactly its
        target, because `traits._calibrate_trait` solved for it. Here the
        function is a consistency check on the calibration.

      * Every other trait returns a small residual of the random walk that
        `loci.py`'s N(0, 0.15) dominance ratios leave behind. It is NOT
        calibrated to zero and should not be read as a modelled null: it is
        an uncalibrated leftover, ~0.02-0.3 liability SD per unit F, which on
        the trait scale is a fraction of the smallest depression anyone has
        measured. For the four traits Joshi et al. 2015 tested and found no
        depression in -- bmi, adiposity, bp_set_point, lipid_profile -- that
        leftover is how the reproduced null is represented.
    """
    from .traits import ARCHITECTURE
    arch = ARCHITECTURE[trait]
    twopq = 2.0 * arch.p * (1.0 - arch.p)
    return float(np.sum(twopq * arch.d))


def predicted_depression(trait: str, F: float) -> float:
    """
    The expected shift in `trait`, IN ITS OWN UNITS, for an individual with
    inbreeding coefficient F. Negative = smaller than the outbred mean.

        M_F - M_0 = -F * sd * sum_j 2 p_j q_j d_j

    This is the trait-scale counterpart of `predicted_log_survival`: the same
    pedigree F drives both, one through dominance deviations at the trait
    loci and one through recessive load at the fitness loci. They are
    independent mechanisms measured in different literatures (Joshi et al.
    2015 vs Morton, Crow & Muller 1956) and this engine now carries both, so
    they must not be read as two views of one number.

    Categorical traits have no unit scale, so the shift is returned in
    liability SD -- which is also what it means for the z-scored continuous
    traits whose sd is 1.0.
    """
    from .traits import ARCHITECTURE
    sd = ARCHITECTURE[trait].spec.sd
    return -float(F) * sd * directional_dominance(trait)


# ----------------------------------------------------------------------
# Limitations
# ----------------------------------------------------------------------
# * DIRECTIONAL DOMINANCE IS NOW MODELLED, on two traits only. Inbreeding
#   costs viability here (this module) AND shortens stature (traits.py, via
#   TraitSpec.depression_per_10F: height -1.2 cm and lung capacity -137 ml per
#   10% F, Joshi et al. 2015). It is deliberately NOT applied to every trait:
#   Joshi tested 16 and found depression in 4, so bmi, adiposity, bp_set_point
#   and lipid_profile stay flat to reproduce the paper's nulls. Traits with no
#   published estimate at all -- aerobic_capacity, the immune traits, the
#   personality traits -- are simply uncalibrated in this respect, and
#   `directional_dominance` reports the small residual left by loci.py's
#   random-sign dominance ratios rather than a modelled zero.
# * The two mechanisms are independent and must not be summed into one
#   "cost of inbreeding". Dominance deviations at trait loci move a phenotype;
#   recessive load at the fitness loci kills. An individual can be short and
#   viable. The engine deliberately keeps them on separate scales.
# * The load spectrum is a fixed constant of the engine: frequencies do not
#   respond to the simulated population's own selection or drift. A world
#   that inbreeds heavily for many generations should PURGE some of its
#   recessive load (Crnokrak & Barrett 2002) and the transmitted genotypes do
#   drift, but `SPECTRUM.q` -- and hence B -- stays at its founding value, so
#   the predicted law is the founding-population one throughout.
# * 2000 load loci stand in for a genome-wide mutational target of order
#   10^4 sites. The implied U ~ 0.50 is consequently about a third of Eyre-
#   Walker & Keightley 1999's ~1.6 for humans.
# * Viability is applied at birth as juvenile survival, not spread across the
#   pre-reproductive years. Lethal equivalents ARE conventionally measured on
#   survival to adulthood, so the total is right and only its timing is
#   compressed.
# * Load loci are unlinked and carry no cM position, so they cannot show
#   associative overdominance or background selection -- real recessive load
#   is linked to the trait loci it sits between.
# * Founders are assumed unrelated. True by construction here; a genuine
#   source of downward bias in F for any real pedigree.
