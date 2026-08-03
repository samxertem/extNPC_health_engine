"""
Genomic imprinting: parent-of-origin effects (roadmap #4).
=========================================================

Most autosomal genes are expressed from both parental copies. Roughly
100-200 human genes are not: they are *imprinted*, expressed from only the
maternal or only the paternal allele, with the silent copy marked by DNA
methylation laid down in the germline. The mark is not written by the
allele's sequence -- an identical allele is silenced or expressed purely
according to which parent it came through.

Two consequences drive everything in this module:

  1. **Reciprocal heterozygotes differ.** Two individuals with the *same*
     genotype at an imprinted locus -- one carrying the alternate allele
     from its mother, one from its father -- have different phenotypes.
     Mendelian genetics says they must be identical. They are not. This is
     the benchmark the roadmap asks for.

  2. **There is no heterozygote intermediate.** If only one allele is
     transcribed, the phenotype reflects *that allele*, not an average of
     the two. A monoallelically expressed locus behaves as though the
     individual were homozygous for whichever copy is active.

The canonical human illustration is 15q11-q13, where the *same*
chromosomal deletion causes two entirely different disorders depending on
the parent of origin: Prader-Willi syndrome from a paternal deletion,
Angelman syndrome from a maternal one (Nicholls et al. 1998). The
canonical growth example, and the one this catalogue actually carries, is
IGF2 -- paternally expressed, maternally silenced (DeChiara et al. 1991).

Why this module needs no heritable state
----------------------------------------
Imprints are erased in the primordial germ cells and re-established
according to the sex of the individual making the gametes: every egg
carries maternal imprints, every sperm carries paternal ones, regardless
of what that parent inherited. So the imprint on an allele is determined
entirely by *which parent transmitted it* -- and `Genome` already records
that structurally:

    haplotypes[0] = maternal,  haplotypes[1] = paternal   (genome.py)

`fertilise` stacks the egg at index 0 and the sperm at index 1 on every
single reproduction, so the convention is exact and universal. Germline
erasure and re-establishment therefore happen automatically and perfectly,
and this layer stores nothing per-individual and draws no random numbers.
The RNG stream is untouched: genomes are bit-for-bit what they were before
this module existed.

Graded, not binary
------------------
Silencing is a strength in [0, 1], not an on/off switch, because real
imprinting is not absolute: expression from the "silent" allele is
partial and tissue-specific, and *loss of imprinting* is a continuum that
matters clinically (it is one of the commonest epigenetic lesions in
cancer, and the mechanism behind Beckwith-Wiedemann syndrome). Grading
also lets this layer meet the epigenome layer on its own terms: the
imprint is a methylation mark like any other, so the Dutch Hunger Winter
result the engine already models -- periconceptional famine leaving IGF2
*hypomethylated* six decades later (Heijmans et al. 2008, roadmap #19) --
is a partial loss of imprinting, expressible here as a reduction in
`strength` rather than a separate mechanism.

Scope, honestly stated
----------------------
The locus catalogue contains exactly one genuinely imprinted gene, IGF2,
so that is the only locus imprinted by default. The mechanism itself is
general -- any locus can be flagged, and the tests exercise multi-locus
and maternally-expressed cases -- but adding real imprinted genes
(H19, SNRPN, UBE3A, MEST, GRB10, CDKN1C) would change `N_LOCI` and
invalidate every calibrated heritability in the engine. That is not a
trade worth making for this mechanism, and pretending the catalogue is
richer than it is would be worse. See "Limitations" at the bottom.

References
----------
DeChiara, Robertson & Efstratiadis 1991 (*Cell* 64:849) -- IGF2 is
paternally expressed; maternal-allele knockouts are phenotypically normal.
Nicholls, Saitoh & Horsthemke 1998 (*Trends Genet.* 14:194) -- 15q11-q13,
Prader-Willi vs Angelman.
Barlow & Bartolomei 2014 (*CSH Perspect. Biol.* 6:a018382) -- germline
erasure and re-establishment.
Heijmans et al. 2008 (*PNAS* 105:17046) -- IGF2 hypomethylation after
prenatal famine.
Reik & Walter 2001 (*Nat. Rev. Genet.* 2:21) -- imprinting as a graded,
tissue-specific phenomenon.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

import numpy as np

from .genome import Genome
from .loci import LOCUS_BY_SYMBOL, N_LOCI

# Which parent's allele is TRANSCRIBED at an imprinted locus.
# The other one is the silenced (methylated) copy.
MATERNAL = 0
PATERNAL = 1

_HAP_NAME = {MATERNAL: "maternal", PATERNAL: "paternal"}


@dataclass(frozen=True)
class ImprintedLocus:
    """One imprinted gene in the catalogue."""
    symbol: str
    expressed_from: int          # MATERNAL or PATERNAL -- the ACTIVE copy
    strength: float              # 1.0 = fully monoallelic, 0.0 = biallelic
    note: str = ""

    @property
    def silenced_parent(self) -> str:
        return _HAP_NAME[1 - self.expressed_from]


# ----------------------------------------------------------------------
# The catalogue
# ----------------------------------------------------------------------
# Only genes that are genuinely imprinted in humans AND present in loci.py.
# `strength` below 1.0 reflects that silencing of the inactive allele is
# strong but not absolute in most tissues (Reik & Walter 2001).
IMPRINTED: Dict[str, ImprintedLocus] = {
    "IGF2": ImprintedLocus(
        symbol="IGF2",
        expressed_from=PATERNAL,
        strength=0.90,
        note=("Paternally expressed; the maternal copy is silenced by "
              "methylation at ICR1 (DeChiara 1991). A growth factor, which "
              "is why it carries weight on height and adiposity here. Also "
              "the Dutch Hunger Winter locus (Heijmans 2008): prenatal "
              "famine leaves it hypomethylated for life, i.e. a partial "
              "LOSS of imprinting -- see relax_imprint()."),
    ),
}


# ----------------------------------------------------------------------
# Per-individual imprint state
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class ImprintState:
    """
    What the trait layer needs to evaluate an imprinted genome.

    `strength` is (L,) in [0, 1]: 0 everywhere except imprinted loci.
    `mono_dosage` is (L,) in {0, 2}: the dosage this individual WOULD have
    if the locus were perfectly monoallelic -- twice the expressed allele.
    It is 2 when the transcribed parental copy carries the alternate
    allele and 0 when it carries the reference, because a monoallelically
    expressed gene still makes gene product; the phenotype tracks the
    identity of the active copy, not a halved dose.

    Both are precomputed so the hot phenotype path stays a vector multiply.
    """
    strength: np.ndarray         # (L,) float64
    mono_dosage: np.ndarray      # (L,) int8, values in {0, 2}

    @property
    def active(self) -> bool:
        return bool(np.any(self.strength > 0.0))


def imprint_strength_vector(
        catalogue: Optional[Mapping[str, ImprintedLocus]] = None) -> np.ndarray:
    """(L,) silencing strength; zero at every non-imprinted locus."""
    cat = IMPRINTED if catalogue is None else catalogue
    s = np.zeros(N_LOCI, dtype=np.float64)
    for sym, spec in cat.items():
        locus = LOCUS_BY_SYMBOL.get(sym)
        if locus is None:          # symbol not in this catalogue build
            continue
        s[locus.index] = spec.strength
    return s


def expressed_haplotype_vector(
        catalogue: Optional[Mapping[str, ImprintedLocus]] = None) -> np.ndarray:
    """
    (L,) index of the haplotype that is TRANSCRIBED at each locus.

    Non-imprinted loci are set to MATERNAL arbitrarily; `strength` is zero
    there, so the value is never used. Keeping the array dense avoids a
    gather-with-mask in the hot path.
    """
    cat = IMPRINTED if catalogue is None else catalogue
    h = np.zeros(N_LOCI, dtype=np.int64)
    for sym, spec in cat.items():
        locus = LOCUS_BY_SYMBOL.get(sym)
        if locus is None:
            continue
        h[locus.index] = spec.expressed_from
    return h


# Module-level defaults: pure functions of the catalogue, so computing them
# once at import is safe and keeps per-NPC cost to a single gather.
DEFAULT_STRENGTH = imprint_strength_vector()
DEFAULT_EXPRESSED_HAP = expressed_haplotype_vector()


def imprint_state(genome: Genome,
                  strength: Optional[np.ndarray] = None,
                  expressed_hap: Optional[np.ndarray] = None) -> ImprintState:
    """
    Build the per-individual imprint state from a genome.

    Reads `genome.haplotypes[parent, locus]` for the transcribed parent at
    every locus -- the one place in the engine where parent-of-origin,
    rather than dosage, decides a phenotype.
    """
    s = DEFAULT_STRENGTH if strength is None else strength
    hap = DEFAULT_EXPRESSED_HAP if expressed_hap is None else expressed_hap
    active_allele = genome.haplotypes[hap, np.arange(N_LOCI)]
    return ImprintState(strength=s, mono_dosage=(2 * active_allele).astype(np.int8))


def relax_imprint(strength_factor: float,
                  symbols: Optional[tuple] = None) -> np.ndarray:
    """
    A strength vector with imprinting partially LOST at the named loci
    (all imprinted loci if `symbols` is None).

    `strength_factor` in [0, 1] scales the default silencing: 1.0 leaves
    imprinting intact, 0.0 abolishes it entirely (full biallelic
    expression). This is how a developmental exposure expresses itself
    here -- the Dutch Hunger Winter cohort's lifelong IGF2 hypomethylation
    (Heijmans et al. 2008) is a partial loss of imprinting, not a separate
    mechanism, so it belongs on this axis rather than in a new one.
    """
    s = DEFAULT_STRENGTH.copy()
    if symbols is None:
        return s * float(strength_factor)
    for sym in symbols:
        locus = LOCUS_BY_SYMBOL.get(sym)
        if locus is not None:
            s[locus.index] *= float(strength_factor)
    return s


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def describe(catalogue: Optional[Mapping[str, ImprintedLocus]] = None) -> str:
    cat = IMPRINTED if catalogue is None else catalogue
    lines = ["Imprinted loci (roadmap #4)", "-" * 62]
    for sym, spec in sorted(cat.items()):
        locus = LOCUS_BY_SYMBOL.get(sym)
        where = f"chr{locus.chrom}" if locus is not None else "not in catalogue"
        lines.append(
            f"  {sym:<8} expressed from the {_HAP_NAME[spec.expressed_from]:<8} "
            f"copy  (silencing {spec.strength:.2f}, {where})")
    if len(lines) == 2:
        lines.append("  (none)")
    return "\n".join(lines)


def parent_of_origin_report(genome: Genome, symbol: str = "IGF2") -> Dict[str, object]:
    """
    Inspect one imprinted locus in one genome: which allele came from which
    parent, and which one is actually transcribed. Used by the demo and by
    the reciprocal-heterozygote test.
    """
    locus = LOCUS_BY_SYMBOL[symbol]
    spec = IMPRINTED[symbol]
    i = locus.index
    mat = int(genome.haplotypes[MATERNAL, i])
    pat = int(genome.haplotypes[PATERNAL, i])
    return {
        "symbol": symbol,
        "maternal_allele": mat,
        "paternal_allele": pat,
        "dosage": mat + pat,
        "heterozygous": mat != pat,
        "expressed_from": _HAP_NAME[spec.expressed_from],
        "expressed_allele": pat if spec.expressed_from == PATERNAL else mat,
        "silenced_allele": mat if spec.expressed_from == PATERNAL else pat,
        "strength": spec.strength,
    }


# ----------------------------------------------------------------------
# Limitations
# ----------------------------------------------------------------------
# * One imprinted locus. Humans have ~100-200; this catalogue contains one
#   real imprinted gene (IGF2) and adding more would change N_LOCI and
#   invalidate every calibrated heritability. The mechanism is general and
#   the tests exercise multi-locus and maternally-expressed configurations,
#   but the DEFAULT world imprints IGF2 alone.
# * Imprinting here is whole-body. Real imprinting is tissue-specific and
#   often developmental-stage-specific (IGF2 imprinting relaxes in adult
#   human liver). There is no tissue axis in this engine to hang that on.
# * Silencing strength is a fixed catalogue constant, not an inherited
#   per-individual variable. Loss of imprinting can be induced via
#   relax_imprint(), but it is not itself heritable or drifting.
# * No imprinted-gene conflict dynamics. The kinship theory of imprinting
#   (Haig 2000) predicts paternally expressed genes push fetal growth up
#   and maternally expressed ones restrain it; with a single imprinted
#   locus there is no antagonism to model.
