"""
Sex chromosomes: X/Y determination, X-linked & sex-limited inheritance.
=======================================================================

Roadmap item #2. The autosomal genome (`genome.py`) segregates 22 pairs of
chromosomes and feeds the calibrated quantitative-genetics map. It has no
notion of sex chromosomes -- `sex` was, until now, a free attribute assigned
by a coin flip, disconnected from any gene. This module adds the real thing.

Why a *separate* module rather than a 23rd chromosome in the array
------------------------------------------------------------------
The autosomal core is calibrated (every trait's V_A solved to its target
heritability) and validated (Hardy-Weinberg, Haldane, breeder's equation).
Sex chromosomes obey qualitatively different rules -- hemizygosity in males,
X-inactivation in females, no X-Y recombination outside the pseudo-autosomal
region -- and the X assorts INDEPENDENTLY of every autosome, so nothing about
autosomal linkage is lost by modelling it alongside rather than inside the
(2, L) array. Keeping it parallel leaves the calibrated autosomal genetics
bit-for-bit untouched (the same design choice used for the epigenome,
physiology and population layers) while letting the sex-linked layer be
built and validated on its own terms.

What is modelled
----------------
1. SEX DETERMINATION. XX = female, XY = male. Sex is set at fertilisation by
   which sex chromosome the father transmits: his X -> daughter, his Y ->
   son. The Y carries the male-determining SRY (Sinclair et al. 1990); we do
   not model its gene content beyond that switch. This makes the ~50:50 sex
   ratio an emergent consequence of Mendelian transmission, not a coin flip.

2. HEMIZYGOSITY. Males carry a single X, so an X-linked recessive allele has
   no second copy to mask it and is expressed directly. This is why X-linked
   recessive conditions are far commoner in males: prevalence ~ q in males
   but ~ q^2 in females. `validation`/`tests` check exactly this against the
   red-green colour-blindness allele frequency (q ~ 0.08).

3. X-INACTIVATION (Lyon 1961). In each female cell one X is randomly and
   permanently silenced, so a woman is a mosaic of two cell populations. We
   summarise the whole body by one heritable-per-individual *skew* -- the
   fraction of cells expressing the maternal X -- drawn from a distribution
   centred on 0.5 with a skewed tail (Amos-Landgraf et al. 2006). This gives
   dosage compensation between the sexes and, for a cell-autonomous
   enzyme (G6PD), an INTERMEDIATE activity in heterozygous carriers rather
   than a clean dominant/recessive split -- the direct signature of mosaicism.

4. SEX-LIMITED / SEX-INFLUENCED expression. Some genotypes express only, or
   far more strongly, in one hormonal sex. Androgenetic alopecia is the
   canonical case: an androgen-receptor (AR, Xq12) liability that manifests
   as patterned hair loss chiefly in males because it is testosterone-gated
   (Hillmer et al. 2005). This ties the sex-linked layer to the existing
   sex-dependent sex-hormone baselines in `physiology.py`.

The X-linked loci
-----------------
Three, each chosen to exercise one mechanism and each with real literature:

  color_vision  OPN1LW/OPN1MW cluster, Xq28. Red-green colour blindness, an
                X-linked recessive; q ~ 0.08 in European-ancestry males
                (~8% male, ~0.6% female prevalence). Flagship for the
                hemizygous q-vs-q^2 validation. (Deeb 2005; Birch 2012.)
  g6pd          Glucose-6-phosphate dehydrogenase, Xq28. Deficiency allele;
                enzyme activity is the XCI-mosaic showcase -- female carriers
                are intermediate. Frequency is strongly ancestry- and
                malaria-dependent; the value here is a neutral placeholder,
                NOT ancestry-specific. (Beutler 2008; WHO 1989.)
  ar            Androgen receptor, Xq12. Risk allele for androgenetic
                alopecia; SEX-LIMITED -- manifests chiefly in males.
                (Hillmer et al. 2005; Nyholt et al. 2003.)

G6PD and colour blindness both sit at Xq28 and are ~3-4 cM apart -- genuinely
linked in humans -- which our X map reproduces, giving a within-X linkage
case for free.

CAVEATS (roadmap Section 5 -- load-bearing)
-------------------------------------------
* Allele frequencies are broadly representative, NOT ancestry-specific. G6PD
  in particular varies from <1% to >20% across populations under malaria
  selection; the single value here must not be read as a population estimate.
* The pseudo-autosomal region (PAR1/PAR2), where X and Y do recombine, is not
  modelled: the father's X and Y are transmitted intact. Consequence: no
  PAR-linked or XY-recombinant inheritance. Real PAR is ~5% of the X.
* X-inactivation is summarised by a single body-wide skew, not a true
  per-tissue mosaic; escape from XCI (~15-25% of X genes; Carrel & Willard
  2005) and age-related skewing drift are not modelled.
* Colour blindness and G6PD are population-level statistical/mechanistic
  findings, not diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

# ----------------------------------------------------------------------
# X chromosome genetic map
# ----------------------------------------------------------------------
# The X recombines only in females (males are hemizygous and transmit their
# single X intact). The female X genetic map is ~180 cM (Kong et al. 2002).
# We only ever need it for maternal X meiosis.
X_CM_LENGTH_FEMALE = 180.0


@dataclass(frozen=True)
class XLocus:
    """One X-linked biallelic locus. allele 0 = reference/functional,
    allele 1 = risk/non-functional (the minor, trait-causing allele)."""
    symbol: str
    trait: str
    cm: float                    # position on the female X map, centimorgans
    risk_freq: float             # population frequency of the risk allele (q)
    recessive: bool              # True: needs two copies (or hemizygous) to show
    sex_limited: bool = False    # True: manifests chiefly in one hormonal sex
    note: str = ""


# Positions place G6PD and colour blindness close together at Xq28 (linked,
# ~3 cM apart), AR near the centromere (Xq12). Sign convention: allele 1 is
# always the trait-causing allele.
X_LOCI: List[XLocus] = [
    XLocus("ar", "pattern_baldness", 90.0, 0.30, recessive=False, sex_limited=True,
           note="Androgen receptor, Xq12. Androgenetic-alopecia risk allele; "
                "androgen-gated, so expressed chiefly in males. Hillmer 2005."),
    XLocus("g6pd", "g6pd_activity", 174.0, 0.06, recessive=True,
           note="G6PD, Xq28. Deficiency allele. Enzyme activity is the "
                "XCI-mosaic showcase (intermediate in carriers). Beutler 2008. "
                "Frequency is a NEUTRAL placeholder, not ancestry-specific."),
    XLocus("color_vision", "color_vision", 177.0, 0.08, recessive=True,
           note="OPN1LW/MW, Xq28. Red-green colour blindness, X-linked "
                "recessive; q~0.08 -> ~8% male, ~0.6% female. Deeb 2005. "
                "~3 cM from G6PD -> genuinely linked; our X map reproduces it."),
]

X_LOCUS_INDEX: Dict[str, int] = {L.symbol: i for i, L in enumerate(X_LOCI)}
N_X_LOCI: int = len(X_LOCI)
X_RISK_FREQ: np.ndarray = np.array([L.risk_freq for L in X_LOCI])
X_CM_POS: np.ndarray = np.array([L.cm for L in X_LOCI])

# G6PD activity of the deficiency allele, relative to the functional allele.
# Class-II/III variants retain ~10% activity; hemizygous males with the
# allele are frankly deficient, carriers are intermediate by XCI mosaic.
G6PD_DEFICIENT_ACTIVITY = 0.10

# X-inactivation skew (fraction of cells expressing the MATERNAL X). Centred
# on 0.5; SD ~0.13 reproduces the empirical spread, with ~5-10% of women
# skewed beyond 75:25 (Amos-Landgraf et al. 2006).
XCI_SKEW_SD = 0.13
# A cell-autonomous recessive trait manifests in a heterozygous female only
# if the functional-allele cell fraction falls below this -- i.e. extreme
# skew toward the mutant X. Keeps manifesting carriers rare, as observed.
MANIFEST_FUNCTIONAL_FRACTION = 0.20


# ======================================================================
# Sex-chromosome genotype
# ======================================================================

@dataclass
class SexChromosomes:
    """
    An individual's sex-chromosome constitution.

    Female (XX): two X haplotypes over the X-linked loci, `x_maternal` and
        `x_paternal` (each (N_X_LOCI,) int8 in {0,1}), plus a body-wide
        X-inactivation skew in [0, 1] = fraction of cells expressing the
        maternal X.
    Male (XY): one X haplotype `x_maternal` (from the mother) and a Y (no
        X-linked loci; carries the SRY male switch). `x_paternal` is None and
        `xci_skew` is None -- males are hemizygous, no inactivation.
    """
    sex: str                                  # "female" | "male"
    x_maternal: np.ndarray                    # (N_X_LOCI,) int8
    x_paternal: Optional[np.ndarray] = None   # (N_X_LOCI,) int8, females only
    xci_skew: Optional[float] = None          # females only

    @property
    def is_female(self) -> bool:
        return self.sex == "female"

    def copy(self) -> "SexChromosomes":
        return SexChromosomes(
            self.sex,
            self.x_maternal.copy(),
            None if self.x_paternal is None else self.x_paternal.copy(),
            self.xci_skew,
        )

    # ---- expression of the X-linked loci ----------------------------

    def _functional_fraction(self, i: int) -> float:
        """
        Fraction of the body expressing the FUNCTIONAL (allele-0) copy at
        X-linked locus i.

        Male: 1.0 if his single X carries the functional allele, else 0.0
              (hemizygous -- all-or-nothing).
        Female: an XCI mosaic. Each X contributes its allele weighted by the
              fraction of cells in which it is the active X.
        """
        if self.sex == "male":
            return 1.0 if self.x_maternal[i] == 0 else 0.0
        mat_functional = 1.0 if self.x_maternal[i] == 0 else 0.0
        pat_functional = 1.0 if self.x_paternal[i] == 0 else 0.0
        s = self.xci_skew
        return s * mat_functional + (1.0 - s) * pat_functional

    def color_vision(self) -> str:
        """'normal' or 'colorblind'. Recessive, cell-autonomous: males need
        one allele (hemizygous), females need two -- or extreme XCI skew in a
        carrier (a rare manifesting heterozygote)."""
        i = X_LOCUS_INDEX["color_vision"]
        if self.sex == "male":
            return "colorblind" if self.x_maternal[i] == 1 else "normal"
        both_mutant = self.x_maternal[i] == 1 and self.x_paternal[i] == 1
        carrier = self.x_maternal[i] + self.x_paternal[i] == 1
        manifesting = carrier and self._functional_fraction(i) < MANIFEST_FUNCTIONAL_FRACTION
        return "colorblind" if (both_mutant or manifesting) else "normal"

    def g6pd_activity(self) -> float:
        """
        Relative G6PD enzyme activity in [G6PD_DEFICIENT_ACTIVITY, 1.0].

        The XCI-mosaic showcase: a hemizygous male is either fully functional
        or frankly deficient, but a heterozygous female is INTERMEDIATE, her
        activity set by the inactivation skew -- the quantitative fingerprint
        of Lyonisation.
        """
        i = X_LOCUS_INDEX["g6pd"]
        frac = self._functional_fraction(i)          # functional-cell fraction
        return G6PD_DEFICIENT_ACTIVITY + (1.0 - G6PD_DEFICIENT_ACTIVITY) * frac

    def pattern_baldness_liability(self) -> float:
        """
        Androgenetic-alopecia liability from the AR risk allele, in [0, 1]
        dosage terms. SEX-LIMITED: the same genotype expresses chiefly in
        males because the pathway is androgen-gated. Returned here as the raw
        genetic liability; `manifests_baldness` applies the sex gate.
        """
        i = X_LOCUS_INDEX["ar"]
        if self.sex == "male":
            return 1.0 if self.x_maternal[i] == 1 else 0.0
        # female: dominant-ish AR risk, but see the sex gate below
        return 0.5 * (int(self.x_maternal[i]) + int(self.x_paternal[i]))

    def manifests_baldness(self) -> bool:
        """Whether patterned hair loss actually manifests, after the androgen
        sex gate. Females carrying the risk allele show at most diffuse
        thinning; frank male-pattern balding is essentially male-limited."""
        liab = self.pattern_baldness_liability()
        return self.sex == "male" and liab >= 1.0

    def phenotype(self) -> Dict[str, object]:
        """All X-linked phenotypes for this individual."""
        return {
            "color_vision": self.color_vision(),
            "g6pd_activity": round(self.g6pd_activity(), 3),
            "pattern_baldness": self.manifests_baldness(),
        }


# ======================================================================
# Founder sampling (Hardy-Weinberg on the X)
# ======================================================================

def _draw_xci_skew(rng: np.random.Generator) -> float:
    """Body-wide X-inactivation skew ~ clipped Normal(0.5, XCI_SKEW_SD)."""
    return float(np.clip(rng.normal(0.5, XCI_SKEW_SD), 0.02, 0.98))


def sample_founder_sex_chromosomes(rng: np.random.Generator,
                                   sex: str) -> SexChromosomes:
    """
    Draw a founder's X-linked genotype under Hardy-Weinberg.

    Males: one X, each locus Bernoulli(q)  -> hemizygous, prevalence ~ q.
    Females: two X's, each Bernoulli(q)    -> genotypes q^2 : 2pq : q^2.
    """
    if sex == "male":
        x = (rng.random(N_X_LOCI) < X_RISK_FREQ).astype(np.int8)
        return SexChromosomes("male", x_maternal=x)
    xm = (rng.random(N_X_LOCI) < X_RISK_FREQ).astype(np.int8)
    xp = (rng.random(N_X_LOCI) < X_RISK_FREQ).astype(np.int8)
    return SexChromosomes("female", x_maternal=xm, x_paternal=xp,
                          xci_skew=_draw_xci_skew(rng))


# ======================================================================
# Meiosis & fertilisation
# ======================================================================

def _recombine_x(x_a: np.ndarray, x_b: np.ndarray,
                 rng: np.random.Generator) -> np.ndarray:
    """
    One recombined X gamete from a female's two X's, via the same Poisson
    crossover model used for autosomes (`genome.meiosis`), on the female X
    map. With only a few loci this mostly transmits an intact parental X, but
    the linked G6PD/colour-blindness pair can recombine at the correct rate.
    """
    n_xo = rng.poisson(X_CM_LENGTH_FEMALE / 100.0)
    start = int(rng.integers(0, 2))
    haps = (x_a, x_b)
    if n_xo == 0:
        return haps[start].copy()
    xo = np.sort(rng.uniform(0.0, X_CM_LENGTH_FEMALE, size=n_xo))
    crossings = np.searchsorted(xo, X_CM_POS, side="right")
    which = (start + crossings) % 2
    return np.where(which == 0, x_a, x_b).astype(np.int8)


def transmit_sex_chromosomes(mother: SexChromosomes, father: SexChromosomes,
                             rng: np.random.Generator,
                             transmit_paternal_x: Optional[bool] = None
                             ) -> SexChromosomes:
    """
    Produce a child's sex chromosomes from the parents'.

    The mother (XX) always contributes a recombined X. The father (XY)
    contributes EITHER his X (-> daughter) OR his Y (-> son); that single
    Bernoulli(0.5) choice is what determines the child's sex.

    `transmit_paternal_x`: if given, forces the father's contribution
    (True = X = daughter). Used to (a) honour an explicitly requested child
    sex and (b) let the caller supply the coin flip so the autosomal RNG
    stream is preserved. If None, drawn here.
    """
    if mother.sex != "female" or father.sex != "male":
        raise ValueError("transmit expects a female mother and a male father")

    maternal_x = _recombine_x(mother.x_maternal, mother.x_paternal, rng)

    if transmit_paternal_x is None:
        transmit_paternal_x = rng.random() < 0.5

    if transmit_paternal_x:
        # father passes his X -> daughter (XX)
        paternal_x = father.x_maternal.copy()      # his single X, intact
        return SexChromosomes("female", x_maternal=maternal_x,
                              x_paternal=paternal_x, xci_skew=_draw_xci_skew(rng))
    # father passes his Y -> son (XY), hemizygous on the mother's X
    return SexChromosomes("male", x_maternal=maternal_x)


# ======================================================================
# Population-scale helpers (for the validation law)
# ======================================================================

def x_linked_prevalence(karyotypes: List[SexChromosomes], trait: str
                        ) -> Tuple[float, float]:
    """
    (male_prevalence, female_prevalence) of an X-linked recessive condition
    across a cohort. For colour blindness this is the headline test: males
    ~ q, females ~ q^2 (Deeb 2005).
    """
    if trait == "color_vision":
        males = [k for k in karyotypes if k.sex == "male"]
        females = [k for k in karyotypes if k.sex == "female"]
        mp = np.mean([k.color_vision() == "colorblind" for k in males]) if males else 0.0
        fp = np.mean([k.color_vision() == "colorblind" for k in females]) if females else 0.0
        return float(mp), float(fp)
    raise ValueError(f"no prevalence helper for trait {trait!r}")
