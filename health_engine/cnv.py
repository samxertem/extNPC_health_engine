"""
Structural variation: copy-number variants (roadmap #12, the last third).
=========================================================================

#12 asked for three things: a realistic point-mutation rate, the paternal-age
effect, and "rare CNV/structural events". The first two have been in
`genome.py` since Stage 0 (Kong et al. 2012, the 4:1 paternal bias, the
+2-mutations-per-paternal-year slope). This module is the third, and
`mutate_gamete`'s docstring has carried the reason it was missing:

    LIMITATION: only point mutations. Copy-number and structural variants
    (Sebat et al. 2007) are not modelled -- a real CNV can delete or
    duplicate whole gene regions, which our fixed-length allele array
    cannot express.

That is still true of the allele array, and rebuilding it this late would
invalidate every calibrated heritability in the engine. It is not true of
the engine as a whole, because the allele array is not the only thing the
genotype-phenotype map reads.

The seam that already existed
-----------------------------
`traits.genotypic_value` multiplies every locus by an (L,) expression
factor:

    val = val * expression[arch.idx]

The epigenome (#16) writes into it in cis, the gene-regulatory network (#8)
in trans. A CNV is the third natural inhabitant of that seam, because
**a copy-number change is a gene-dosage change**: lose one of two copies and
the locus makes roughly half as much product; gain a third and it makes
roughly half again as much. So

    dosage multiplier = copy_number / 2

with 2 copies giving exactly 1.0 -- which is why a world with no CNVs is
bit-for-bit the world before this module existed.

What this does and does not capture -- read this before believing a result
--------------------------------------------------------------------------
The expression seam scales a locus's **genotypic deviation**, not its
absolute gene product. `genotypic_value` computes val in {+a, d, -a}, which
is a deviation from the trait's reference configuration, and multiplying it
by copy_number/2 moves the individual TOWARD that reference, not toward a
null.

Real gene dosage is not that. Deleting one copy of OCA2 removes half the
protein a melanin pathway needs, and the carrier is lighter whichever allele
survives. Halving the *deviation* instead moves them toward the population
reference, which for a locus whose derived allele is the light one means
slightly DARKER. The engine will say so, and the direction will be wrong.

So the honest statement of what this module models:

  * **magnitude** of a dosage effect, exactly: the shift is (c/2 - 1) times
    the locus's own contribution, in closed form (`predicted_mean_shift`);
  * **mirror symmetry** between a deletion and its reciprocal duplication,
    exactly and for free -- equal magnitude, opposite sign, which is the
    signature Jacquemont et al. 2011 found for BMI at reciprocal 16p11.2
    variants and the strongest evidence that a phenotype is dosage-driven;
  * **fitness**, and through it an emergent mutation-selection balance;
  * NOT the direction of a loss-of-function phenotype, and NOT hemizygous
    unmasking of the surviving allele.

That limitation is inherited from the seam rather than invented here: the
epigenome (#16) and the regulatory network (#8) scale the same deviation and
have the same property, which is why session 5 found the GRN multiplier to
be a symmetric amplifier that moves variance rather than the mean. Fixing it
properly means giving autosomes the hemizygous machinery `sexchrom.py`
already has for the X, which is a change to the calibrated genotype path
rather than a multiplier on it. See "Limitations".

Why these regions and no others
--------------------------------
Recurrent human CNVs are not random. They arise by non-allelic homologous
recombination between flanking segmental duplications, so the same
breakpoints recur in unrelated people, and the same deletion and its
reciprocal duplication are produced by the same event at similar rates
(Lupski 1998; Stankiewicz & Lupski 2002). Two of them land on genes this
catalogue actually contains:

  * **22q11.2** (chr22:18.9-21.5 Mb) contains **COMT** at 19.9 Mb. The
    commonest human microdeletion, ~1/4000 births (DiGeorge /
    velocardiofacial syndrome), and >90% de novo because carriers'
    reproductive fitness is very low. COMT hemizygosity halves dopamine
    catabolism in prefrontal cortex, which is why it is the most-studied
    single gene in the region.

  * **15q11-q13 BP1-BP3** (chr15:22.8-28.5 Mb) contains **OCA2** at 28.2 Mb
    and HERC2 at 28.1. The Prader-Willi / Angelman region, and an imprinted
    one, so the parent of origin decides which syndrome a deletion causes.
    Included because it is real, because it is the only imprinted recurrent
    CNV region, and because OCA2/HERC2 carry the largest trait weights of any
    catalogue gene inside a CNV region -- so it is the region where a dosage
    effect is actually visible rather than lost in the noise.

    It is also the clearest illustration of the limitation above. Patients
    with the LARGE (BP1-BP3) deletion are hypopigmented relative to their own
    families, and those with the smaller deletion are not, because only the
    large one takes a copy of OCA2 with it (Butler 1989; Spritz et al. 1997).
    **The engine does not reproduce that**, and the reason is instructive:
    OCA2's derived allele in this catalogue is the light one, so halving the
    locus's deviation moves a carrier toward the reference and therefore
    slightly darker. The magnitude is right and the sign is wrong, which is
    exactly what "scales the deviation, not the product" predicts.

There is no common, benign, multiallelic CNV in the catalogue, and this
module does not invent one. The canonical examples -- AMY1 copy number and
starch digestion (Perry et al. 2007), CCL3L1 and HIV susceptibility, beta-
defensin cluster copy number -- involve genes that are simply not in
`loci.py`, and adding them would change `N_LOCI` and invalidate every
calibrated heritability. `add_region` exists so a user can define one; the
DEFAULT catalogue contains only regions that are real and that overlap real
catalogue genes.

The consequence is that CNVs are RARE here, as they are in life. A
150-person world will usually contain none. `NPC.apply_cnv` is therefore the
main way to exercise the mechanism, exactly as `NPC.perturb_gene` is for the
regulatory network (#8) -- an in-silico experiment, not a demographic event.

Selection, and why the frequencies stay put
--------------------------------------------
Each region carries a fitness cost, applied through the juvenile-survival
path built for #31. That makes the observed carrier frequency an EMERGENT
mutation-selection balance, q ~ mu/s, rather than a number written down.
For 22q11.2 with mu = 1.2e-4 per gamete and s = 0.95 that gives a birth
prevalence near 1/4000 and a de novo fraction above 90% -- both of which
are the observed values, and neither of which is set anywhere in the code.

Determinism
-----------
De novo events are drawn from a spawned sub-generator (`inbreeding.
derived_rng`), so this layer costs the caller's RNG stream nothing and the
autosomal core stays byte-identical -- per-sequence, not merely
per-individual. See inbreeding.py for why that distinction matters.

References
----------
Sebat et al. 2007 (*Science* 316:445) -- de novo CNVs.
Lupski 1998 (*Trends Genet.* 14:417); Stankiewicz & Lupski 2002 (*Trends
Genet.* 18:74) -- NAHR between segmental duplications; reciprocal products.
Itsara et al. 2010 (*Genome Res.* 20:1469) -- de novo CNV rates.
McDonald-McGinn et al. 2015 (*Nat. Rev. Dis. Primers* 1:15071) -- 22q11.2.
Butler 1989 (*Am. J. Med. Genet.* 35:319); Spritz et al. 1997 (*Am. J. Med.
Genet.* 71:57) -- OCA2 dosage and hypopigmentation in PWS/AS.
Jacquemont et al. 2011 (*Nature* 478:97) -- mirror-image BMI phenotypes from
reciprocal 16p11.2 deletion and duplication: the dosage-response signature.
Rice & McLysaght 2017 (*Nat. Commun.* 8:14366) -- dosage sensitivity.
Perry et al. 2007 (*Nat. Genet.* 39:1256) -- AMY1 copy number and diet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .loci import LOCUS_BY_SYMBOL, N_LOCI

# Copy count carried on ONE haplotype. Two is a duplication of that copy, so
# an individual with (1, 2) has three copies in total.
DELETED = 0
NORMAL = 1
DUPLICATED = 2


@dataclass(frozen=True)
class CNVRegion:
    """
    One recurrent copy-number-variable region.

    `genes` are catalogue symbols inside the region -- the ones whose dosage
    actually changes. A real region contains dozens of genes; only those in
    `loci.py` can have a modelled consequence, and the docstring of each
    entry says which.

    `de_novo_rate` is per gamete per generation. `deletion_fitness` and
    `duplication_fitness` are RELATIVE viabilities of a carrier, folded into
    the same juvenile-survival path as the recessive load (#31), so the
    population frequency of the region is an emergent mutation-selection
    balance rather than a set constant.
    """
    name: str
    chrom: int
    start_mb: float
    end_mb: float
    genes: Tuple[str, ...]
    de_novo_rate: float
    deletion_fitness: float = 1.0
    duplication_fitness: float = 1.0
    note: str = ""

    def contains(self, symbol: str) -> bool:
        locus = LOCUS_BY_SYMBOL.get(symbol)
        if locus is None:
            return False
        return (locus.chrom == self.chrom
                and self.start_mb <= locus.bp_mb <= self.end_mb)

    @property
    def catalogue_indices(self) -> Tuple[int, ...]:
        out = []
        for sym in self.genes:
            locus = LOCUS_BY_SYMBOL.get(sym)
            if locus is not None:
                out.append(locus.index)
        return tuple(out)


# ----------------------------------------------------------------------
# The catalogue
# ----------------------------------------------------------------------
# Only regions that are (a) genuinely recurrent in humans and (b) contain a
# gene this catalogue carries. See the module docstring for what is
# deliberately absent.

REGIONS: Dict[str, CNVRegion] = {
    "22q11.2": CNVRegion(
        name="22q11.2",
        chrom=22, start_mb=18.9, end_mb=21.5,
        genes=("COMT",),
        # TOTAL NAHR rate per gamete; half the events give the deletion and
        # half the reciprocal duplication. Solved backwards from the observed
        # ~1/4000 birth prevalence of the deletion: prevalence = 2q with
        # q = (rate/2)/s, so rate = 4 s x prevalence / 2 ~ 2.4e-4 at s = 0.95.
        # `birth_prevalence` recomputes it, so the number stays checkable.
        de_novo_rate=2.4e-4,
        deletion_fitness=0.05,        # reproductive fitness of DiGeorge is very low
        duplication_fitness=0.70,     # 22q11.2 duplication is markedly milder
        note=("DiGeorge / velocardiofacial syndrome, the commonest human "
              "microdeletion. COMT hemizygosity halves prefrontal dopamine "
              "catabolism; in this catalogue COMT carries neuroticism and "
              "conscientiousness weight, so a deletion shifts both."),
    ),
    "15q11-q13": CNVRegion(
        name="15q11-q13",
        chrom=15, start_mb=22.8, end_mb=28.5,
        genes=("OCA2", "HERC2"),
        # Set for a combined deletion prevalence near 1/12,000 births, the
        # rough sum of Prader-Willi and Angelman deletion cases.
        de_novo_rate=8.0e-5,
        deletion_fitness=0.02,        # PWS/AS: reproduction is essentially absent
        duplication_fitness=0.35,
        note=("The Prader-Willi / Angelman region, and the only imprinted "
              "one in the catalogue. The BP1-BP3 (large) deletion takes a "
              "copy of OCA2 with it, which is why those patients are "
              "hypopigmented relative to their own families (Butler 1989; "
              "Spritz 1997). The engine gets the MAGNITUDE of that dosage "
              "effect and not its direction -- see the module docstring, "
              "'What this does and does not capture'."),
    ),
}

# Region order is fixed at import so the per-individual array is positional.
REGION_NAMES: Tuple[str, ...] = tuple(REGIONS)
N_REGIONS: int = len(REGION_NAMES)
_REGION_INDEX: Dict[str, int] = {n: i for i, n in enumerate(REGION_NAMES)}


def add_region(region: CNVRegion) -> None:
    """
    Register a CNV region at runtime.

    Provided so a user can model a common multiallelic CNV (AMY1 and starch
    digestion, say) if they extend `loci.py` to contain its gene. Changes the
    positional layout, so anything already carrying a `CopyNumber` should be
    rebuilt afterwards -- which is why the default catalogue is fixed and
    this is not called anywhere in the engine.
    """
    global REGION_NAMES, N_REGIONS, _REGION_INDEX
    REGIONS[region.name] = region
    REGION_NAMES = tuple(REGIONS)
    N_REGIONS = len(REGION_NAMES)
    _REGION_INDEX = {n: i for i, n in enumerate(REGION_NAMES)}


def region_index(name: str) -> int:
    return _REGION_INDEX[name]


# ======================================================================
# Per-individual copy-number state
# ======================================================================

@dataclass
class CopyNumber:
    """
    Copies carried on each haplotype, (2, R) int8. Row 0 maternal, row 1
    paternal -- the same convention as `Genome` and for the same reason: it
    makes parent-of-origin a structural fact rather than bookkeeping, which
    matters here because 15q11-q13 is the imprinted region where the parent
    of origin decides whether a deletion causes Prader-Willi or Angelman.

    Default is NORMAL on both haplotypes, i.e. two copies, i.e. a dosage
    multiplier of exactly 1.0 at every locus. An NPC with a default
    `CopyNumber` is indistinguishable from an NPC with none.
    """
    haplotypes: np.ndarray            # (2, R) int8

    @classmethod
    def normal(cls) -> "CopyNumber":
        return cls(np.full((2, N_REGIONS), NORMAL, dtype=np.int8))

    @property
    def copies(self) -> np.ndarray:
        """(R,) total copy number per region. 2 is the normal diploid state."""
        return self.haplotypes.sum(axis=0).astype(np.int8)

    @property
    def is_normal(self) -> bool:
        return bool(np.all(self.copies == 2))

    def copies_of(self, region: str) -> int:
        return int(self.copies[_REGION_INDEX[region]])

    def copy(self) -> "CopyNumber":
        return CopyNumber(self.haplotypes.copy())

    # ---- the phenotypic consequence ----------------------------------

    def dosage_multiplier(self) -> np.ndarray:
        """
        (L,) gene-dosage multiplier for the trait layer: copy_number / 2 at
        every catalogue gene inside an affected region, 1.0 everywhere else.

        Returns the shared all-ones array when the individual has no CNV, so
        the common case allocates nothing and composes to a no-op.
        """
        if self.is_normal:
            return _ONES
        m = np.ones(N_LOCI, dtype=np.float64)
        copies = self.copies
        for i, name in enumerate(REGION_NAMES):
            if copies[i] == 2:
                continue
            for j in REGIONS[name].catalogue_indices:
                m[j] = copies[i] / 2.0
        return m

    def fitness(self) -> float:
        """
        Relative viability of this copy-number state, multiplicative across
        regions. Feeds the same juvenile-survival path as the recessive load
        (#31), which is what turns the catalogue's de novo rates into an
        emergent carrier frequency instead of a stipulated one.
        """
        w = 1.0
        copies = self.copies
        for i, name in enumerate(REGION_NAMES):
            r = REGIONS[name]
            if copies[i] < 2:
                w *= r.deletion_fitness ** (2 - copies[i])
            elif copies[i] > 2:
                w *= r.duplication_fitness ** (copies[i] - 2)
        return float(w)

    # ---- reporting ---------------------------------------------------

    def variants(self) -> List[Dict[str, object]]:
        """Every non-diploid region this individual carries."""
        out: List[Dict[str, object]] = []
        copies = self.copies
        for i, name in enumerate(REGION_NAMES):
            if copies[i] == 2:
                continue
            out.append({
                "region": name,
                "copies": int(copies[i]),
                "kind": "deletion" if copies[i] < 2 else "duplication",
                "maternal_copies": int(self.haplotypes[0, i]),
                "paternal_copies": int(self.haplotypes[1, i]),
                # 15q11-q13 is imprinted, so which parent the loss came
                # through is the difference between two distinct syndromes.
                "parent_of_origin": ("maternal" if self.haplotypes[0, i] != NORMAL
                                     else "paternal"),
                "genes": REGIONS[name].genes,
            })
        return out


_ONES = np.ones(N_LOCI, dtype=np.float64)
_ONES.flags.writeable = False


# ======================================================================
# Inheritance and de novo formation
# ======================================================================

def sample_founder_copy_number(rng: np.random.Generator,
                               frequencies: Optional[Mapping[str, float]] = None
                               ) -> CopyNumber:
    """
    Founder copy number. Diploid-normal by default.

    Founders start CNV-free on purpose. Every pathogenic region in the
    catalogue sits at mutation-selection balance in the 1e-4 range, so
    drawing 12 founders from the population frequency would produce a
    carrier roughly once in a thousand worlds -- the sampling would be
    correct and completely invisible. Starting clean and letting de novo
    events introduce them makes the emergent balance observable from a known
    initial condition instead. Pass `frequencies` to override.
    """
    cn = CopyNumber.normal()
    if not frequencies:
        return cn
    for name, q in frequencies.items():
        i = _REGION_INDEX[name]
        cn.haplotypes[:, i] = np.where(rng.random(2) < q, DELETED, NORMAL)
    return cn


def transmit_copy_number(mother: CopyNumber, father: CopyNumber,
                         rng: np.random.Generator,
                         de_novo: bool = True,
                         rate_scale: float = 1.0) -> CopyNumber:
    """
    One haplotype from each parent, then de novo NAHR events.

    A region is transmitted as a unit -- a deleted segment has no internal
    recombination to model, and the duplicated one is inherited as a block.

    De novo events produce a deletion and its reciprocal duplication at the
    same rate, because a single unequal crossover between the flanking
    segmental duplications generates both products (Lupski 1998). Getting
    that symmetry for free is one of the reasons to model the mechanism
    rather than to assert two independent rates.
    """
    r = N_REGIONS
    egg = mother.haplotypes[rng.integers(0, 2, r), np.arange(r)].copy()
    sperm = father.haplotypes[rng.integers(0, 2, r), np.arange(r)].copy()

    if de_novo:
        for gamete in (egg, sperm):
            for i, name in enumerate(REGION_NAMES):
                if gamete[i] != NORMAL:
                    continue            # already rearranged; do not stack
                if rng.random() < REGIONS[name].de_novo_rate * rate_scale:
                    gamete[i] = DELETED if rng.random() < 0.5 else DUPLICATED

    return CopyNumber(np.stack([egg, sperm]).astype(np.int8))


def induce(region: str, kind: str = "deletion",
           parent: str = "maternal") -> CopyNumber:
    """
    Build a copy-number state carrying one named variant. The in-silico
    experiment API, analogous to `NPC.perturb_gene` for the regulatory
    network -- pathogenic CNVs are too rare to wait for.
    """
    cn = CopyNumber.normal()
    i = _REGION_INDEX[region]
    row = 0 if parent == "maternal" else 1
    cn.haplotypes[row, i] = DELETED if kind == "deletion" else DUPLICATED
    return cn


# ======================================================================
# Closed forms the validation harness checks against
# ======================================================================

def locus_mean_contribution(trait: str, symbol: str) -> float:
    """
    A single locus's contribution to the trait's population mean genotypic
    value, in liability units:

        E[val_j] = a_j (p_j - q_j) + 2 p_j q_j d_j

    This is precisely the j-th term of `TraitArchitecture.mean_g`, which
    `genotypic_value` subtracts. It is the quantity a dosage change scales,
    and therefore the whole content of the dosage-response law below.
    """
    from .traits import ARCHITECTURE

    arch = ARCHITECTURE[trait]
    locus = LOCUS_BY_SYMBOL[symbol]
    hit = np.flatnonzero(arch.idx == locus.index)
    if hit.size == 0:
        return 0.0
    k = int(hit[0])
    p = float(arch.p[k])
    q = 1.0 - p
    return float(arch.a[k] * (p - q) + 2.0 * p * q * arch.d[k])


def predicted_mean_shift(trait: str, region: str, copies: int) -> float:
    """
    The population-mean liability shift a copy-number change produces:

        E[z | copies] - E[z | 2] = (copies/2 - 1) * sum_j E[val_j]

    summed over the region's catalogue genes. Nothing in the trait layer
    evaluates this. It also makes the mirror-image prediction explicit: a
    deletion (copies = 1) and a duplication (copies = 3) give shifts of
    equal magnitude and opposite sign, which is the signature Jacquemont et
    al. 2011 found for BMI at reciprocal 16p11.2 variants.
    """
    factor = copies / 2.0 - 1.0
    return factor * sum(locus_mean_contribution(trait, sym)
                        for sym in REGIONS[region].genes)


def equilibrium_frequency(region: str) -> float:
    """
    Mutation-selection balance for a dominant-acting deleterious variant,
    q ~ mu / s (Haldane 1927). The de novo rate here counts BOTH products of
    the NAHR event, so the deletion gets half of it.

    Not used to set anything -- it is the prediction that the simulated
    carrier frequency is checked against.
    """
    r = REGIONS[region]
    s = 1.0 - r.deletion_fitness
    if s <= 0.0:
        return float("inf")
    return 0.5 * r.de_novo_rate / s


def birth_prevalence(region: str) -> float:
    """
    Expected fraction of newborns carrying the deletion at mutation-selection
    balance, 2q(1-q). ~1/4000 for 22q11.2, which is the observed figure the
    de novo rate was solved backwards from.
    """
    q = equilibrium_frequency(region)
    if not np.isfinite(q):
        return 1.0
    return float(2.0 * q * (1.0 - q))


def expected_de_novo_fraction(region: str) -> float:
    """
    Fraction of newborn carriers whose variant is NEW rather than inherited,
    which at mutation-selection balance is exactly the selection coefficient:

        q = q f + mu   =>   q = mu / s,  inherited share = q f / q = f

        de novo fraction = 1 - f = s

    A pleasingly clean result: you can read a variant's fitness cost straight
    off the proportion of cases that are sporadic. >90% of 22q11.2 deletions
    are de novo in the clinic, which says its reproductive fitness is below
    0.1 -- and that is where the catalogue's 0.05 comes from, rather than the
    other way round.
    """
    return float(1.0 - REGIONS[region].deletion_fitness)


def describe() -> str:
    lines = ["Recurrent CNV regions (roadmap #12)", "-" * 68]
    for name in REGION_NAMES:
        r = REGIONS[name]
        lines.append(
            f"  {name:<12} chr{r.chrom}:{r.start_mb:.1f}-{r.end_mb:.1f} Mb   "
            f"genes {', '.join(r.genes)}")
        lines.append(
            f"  {'':<12} de novo {r.de_novo_rate:.1e}/gamete   "
            f"fitness del {r.deletion_fitness:.2f} / dup "
            f"{r.duplication_fitness:.2f}   "
            f"q_eq {equilibrium_frequency(name):.2e}   "
            f"birth prevalence 1/{1 / birth_prevalence(name):.0f}   "
            f"de novo {expected_de_novo_fraction(name) * 100:.0f}%")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Limitations
# ----------------------------------------------------------------------
# * DEVIATION, NOT PRODUCT -- the important one, spelled out in the module
#   docstring. The multiplier scales a locus's genotypic deviation, so a
#   deletion moves an individual toward the reference configuration rather
#   than toward a null. Magnitude and mirror symmetry are exact; the
#   direction of a loss-of-function phenotype is not modelled, and the
#   OCA2/15q11-q13 pigmentation case shows the sign coming out wrong.
# * NO HEMIZYGOUS UNMASKING. A recessive allele sitting opposite a deletion
#   should be fully expressed; here it is merely half-weighted. This is the
#   identified next step, and the machinery exists -- sexchrom.py already
#   does hemizygosity for the X. Applying it to an autosome is a change to
#   the calibrated genotype path, not a multiplier on it, which is why it is
#   not in this session's scope.
# * Copy number is linear in dosage. Real dosage-response is often
#   non-linear, with buffering and autoregulation, and some genes are
#   sensitive to deletion but not duplication (Rice & McLysaght 2017). The
#   engine's fitness constants differ by direction; its EXPRESSION
#   multiplier does not.
# * Two regions, because two is how many real recurrent CNV regions contain
#   a gene this catalogue carries. No common multiallelic CNV (AMY1,
#   CCL3L1, beta-defensin) -- those genes are absent from loci.py and adding
#   them would change N_LOCI and invalidate the calibrated heritabilities.
# * 15q11-q13 is imprinted and the parent of origin is recorded, but the
#   engine does not yet make a maternal deletion cause a different syndrome
#   from a paternal one. `imprint.py` covers IGF2 only; wiring
#   parent-of-origin CNV effects to it would need SNRPN/UBE3A in the
#   catalogue.
# * Breakpoints are fixed and only whole regions vary. Non-recurrent,
#   variably sized structural variants -- the majority of large CNVs by
#   count -- are not modelled at all.
# * No inversions, translocations, or aneuploidy.
