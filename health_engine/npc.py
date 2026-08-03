"""
The NPC: genome + persistent environmental deviates + life state.
=================================================================

What changed from v0.2
----------------------
    v0.2                                v0.3 (this file)
    --------------------------------    --------------------------------
    continuous_genes: Dict[str,float]   genome: Genome            (2 x L alleles)
    discrete_genes:   Dict[str,tuple]   genome: Genome            (same array)
    epigenetic_marks: Dict[str,float]   expression: (L,) ones     <- epigenome hook
    mutation_sigma:   Dict[str,float]   (removed -- see below)
    phenotype() re-rolls randomness     phenotype() is deterministic

`mutation_sigma` is gone. Evolution-Strategy self-adaptive mutation
strength is an excellent *optimiser* device and has no biological
referent: organisms do not carry a heritable per-trait Gaussian step
size. Its job -- "some lineages are more genetically variable" -- is now
done properly by (a) real de novo mutation at the Kong 2012 rate and
(b) drift in allele frequencies. `legacy.py` retains the old operator so
the two can still be compared.

`expression` is an (L,) multiplier in [0,1], all ones for now. It is the
seam where the epigenome (roadmap #15-#20) plugs in: promoter methylation
and repressive histone marks reduce a locus's contribution to every trait
it touches, simultaneously. Session 2 fills it in.

SEX
---
`sex` is currently a plain attribute, not chromosomally determined. It
affects two things already: the meiotic map used to make gametes (female
maps are ~1.6x longer, Kong 2002) and the paternal-age mutation slope.
Real sex chromosomes, X-linked recessives, hemizygosity and X-inactivation
mosaicism are roadmap #2, scheduled for Stage 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .epigenome import Epigenome, germline_transmit
from .genome import Genome, cross, sample_founder_genome
from .loci import N_LOCI
from .medical import MedicalCondition
from .mito import MitoGenome, sample_founder_mito
from .sexchrom import (SexChromosomes, sample_founder_sex_chromosomes,
                       transmit_sex_chromosomes)
from .traits import (ARCHITECTURE, CONTINUOUS_TRAITS, Environment,
                     EnvironmentalDeviates, NEUTRAL_ENVIRONMENT, TRAIT_TABLE,
                     TraitKind, breeding_values, express, liability)


@dataclass
class NPC:
    name: str
    genome: Genome
    deviates: EnvironmentalDeviates
    sex: str = "female"                     # "female" | "male"
    generation: int = 0
    parents: Optional[Tuple[str, str]] = None   # (mother, father)
    age: int = 0
    alive: bool = True

    # Lifetime-dynamic epigenetic state (roadmap #15-#20). `expression` is
    # DERIVED from it via refresh_expression(); it is not set independently.
    epigenome: Epigenome = field(default_factory=Epigenome.default)
    # (L,) per-locus expression multiplier consumed by the trait layer.
    expression: np.ndarray = field(default_factory=lambda: np.ones(N_LOCI))

    birth_environment: Environment = field(default_factory=lambda: NEUTRAL_ENVIRONMENT)
    de_novo_mutations: int = 0
    medical_conditions: List[MedicalCondition] = field(default_factory=list)

    # Gene-regulatory perturbations (roadmap #8): {gene_symbol: cis_activity},
    # 0 = knockout .. 1 = wild type .. >1 = over-expression. Empty by default,
    # so the network is silent and expression stays epigenome-only. Used for
    # in-silico knockout experiments; propagated through NETWORK on refresh.
    grn_perturbation: Dict[str, float] = field(default_factory=dict)

    # Sex chromosomes (roadmap #2): X-linked / hemizygous / X-inactivation
    # inheritance, in a layer parallel to the autosomal genome. Set by
    # random_founder / reproduce; None means the sex-linked layer is inactive
    # (e.g. NPCs built directly in older tests), and `sex` is then just the
    # attribute. When present, `sex` is genetically determined and consistent.
    sex_chromosomes: Optional["SexChromosomes"] = None

    # Mitochondrial genome (roadmap #3): maternally inherited, in its own
    # parallel layer. Carries the maternal-lineage haplogroup marker and the
    # heteroplasmy of a modelled pathogenic variant. None = layer inactive.
    mito: Optional["MitoGenome"] = None

    _phenotype_cache: Optional[Dict[str, object]] = field(default=None, repr=False)

    # -------------------- phenotype --------------------

    def invalidate(self) -> None:
        """Call after mutating `expression` or the epigenome."""
        self._phenotype_cache = None

    def refresh_expression(self) -> None:
        """Recompute the expression multiplier and drop the phenotype cache.
        Called after every epigenome change.

        Composition (roadmap #8): the epigenome sets each locus's cis
        expression; the gene-regulatory NETWORK then applies its trans
        multiplier on top. At a default epigenome with no perturbation both
        factors are exactly 1.0, so this is bit-for-bit identical to the
        pre-GRN engine (see test_grn.test_baseline_is_bit_for_bit)."""
        from .grn import NETWORK
        cis = self.epigenome.expression()
        self.expression = NETWORK.compose(cis, self.grn_perturbation or None)
        self._phenotype_cache = None

    def perturb_gene(self, symbol: str, factor: float) -> None:
        """Set a gene's regulatory activity and re-express (#8). factor=0
        knocks it out, 1 restores wild type, >1 over-expresses. The effect
        propagates through the network to the gene's downstream program."""
        if factor == 1.0:
            self.grn_perturbation.pop(symbol, None)
        else:
            self.grn_perturbation[symbol] = factor
        self.refresh_expression()

    def x_linked_phenotype(self) -> Dict[str, object]:
        """X-linked / sex-limited phenotypes (roadmap #2): colour vision,
        G6PD activity, and manifest androgenetic alopecia. Empty if this NPC
        has no sex-chromosome layer."""
        if self.sex_chromosomes is None:
            return {}
        return self.sex_chromosomes.phenotype()

    def mito_phenotype(self) -> Dict[str, object]:
        """Mitochondrial phenotypes (roadmap #3): maternal haplogroup,
        pathogenic heteroplasmy, OXPHOS capacity, disease manifestation.
        Empty if this NPC has no mitochondrial layer."""
        if self.mito is None:
            return {}
        return self.mito.phenotype()

    def effective_aerobic_capacity(self) -> float:
        """Aerobic capacity (VO2 max) after the mitochondrial gate (#3): the
        nuclear-genetic value scaled by OXPHOS capacity, so a high pathogenic
        heteroplasmy above threshold measurably lowers stamina. Falls back to
        the nuclear value when no mitochondrial layer is present."""
        nuclear = float(self.phenotype()["aerobic_capacity"])
        if self.mito is None:
            return nuclear
        return nuclear * self.mito.oxphos_capacity()

    @property
    def epigenetic_age(self) -> float:
        return self.epigenome.epigenetic_age

    @property
    def epigenetic_age_acceleration(self) -> float:
        """Epigenetic age minus chronological age. Positive = aging fast."""
        return self.epigenome.epigenetic_age - self.age

    def hormone_params(self):
        """Per-individual endocrine constitution (roadmap #25). Recomputed
        on demand from current liabilities; cheap and always current."""
        from .physiology import derive_hormone_priors
        return derive_hormone_priors(self)

    def physiological_state(self, phase_h: float = 8.0):
        """A fresh resting physiological state for this NPC (roadmap #21),
        with pain and sickness pulled from its current conditions."""
        from .physiology import refresh_pain_and_sickness, resting_state
        st = resting_state(self, phase_h=phase_h)
        refresh_pain_and_sickness(self, st)
        return st

    @property
    def inflammation_state(self) -> float:
        """
        The physiological inflammation STATE, in liability units:
        genetic predisposition (inflammation_tone) plus the acquired
        epigenetic load built up by chronic stress over the lifespan.

        A newborn's state equals its predisposition; a chronically
        stressed adult's runs well above it. This is the trait/state
        split the physiological-state vector (#21) will generalise, and
        it is what feeds medical hazards and, eventually, the LLM brain.
        """
        from .epigenome import LOAD_TO_LIABILITY
        return (self.liability("inflammation_tone")
                + LOAD_TO_LIABILITY * self.epigenome.inflammatory_load())

    def phenotype(self) -> Dict[str, object]:
        """
        Deterministic given (genome, deviates, expression). Cached.

        This is the single most important behavioural change from v0.2,
        where every call re-rolled the epigenetic silencing check and the
        same NPC could report brown eyes twice and blue eyes once. That
        was modelling partial penetrance in the wrong place: penetrance is
        a property of a developmental outcome, fixed once, not a coin
        flipped every time an observer looks.
        """
        if self._phenotype_cache is None:
            self._phenotype_cache = {
                name: express(arch, liability(arch, self.genome.dosage,
                                              self.deviates, self.expression))
                for name, arch in ARCHITECTURE.items()
            }
        return self._phenotype_cache

    def liability(self, trait: str) -> float:
        return liability(ARCHITECTURE[trait], self.genome.dosage,
                         self.deviates, self.expression)

    def breeding_value(self, trait: str) -> float:
        """Additive genetic value: the heritable half of this NPC's trait."""
        return float(breeding_values(ARCHITECTURE[trait],
                                     self.genome.dosage[None, :])[0])

    # -------------------- life state --------------------

    def restricted_actions(self) -> List[str]:
        acts: List[str] = []
        for c in self.medical_conditions:
            acts.extend(c.restricted_actions)
        return sorted(set(acts))

    def heterozygosity(self) -> float:
        return self.genome.heterozygosity()

    # -------------------- display --------------------

    def pretty_print(self, traits: Optional[List[str]] = None) -> None:
        lineage = (f"parents: {self.parents[0]} x {self.parents[1]}"
                   if self.parents else "founder")
        print(f"\n--- {self.name} | gen {self.generation} | {self.sex} | "
              f"age {self.age} | {lineage} ---")
        ph = self.phenotype()
        show = traits or list(ph)
        for name in show:
            spec = TRAIT_TABLE[name]
            v = ph[name]
            if spec.kind is TraitKind.CONTINUOUS:
                unit = f" {spec.unit}" if spec.unit and spec.unit != "z" else ""
                print(f"  {name:<32}: {v:>8.2f}{unit}")
            else:
                print(f"  {name:<32}: {v}")
        print(f"  {'genome heterozygosity':<32}: {self.heterozygosity():>8.3f}")
        if self.age > 0 or self.epigenetic_age > 0:
            print(f"  {'epigenetic age':<32}: {self.epigenetic_age:>8.1f}  "
                  f"(accel {self.epigenetic_age_acceleration:+.1f})")
        if self.de_novo_mutations:
            print(f"  {'de novo mutations at birth':<32}: {self.de_novo_mutations:>8d}")
        if self.medical_conditions:
            print(f"  acquired conditions             : {self.medical_conditions}")
            print(f"  action-set restrictions         : {self.restricted_actions()}")


# ======================================================================
# Construction
# ======================================================================

def random_founder(name: str, rng: np.random.Generator,
                   sex: Optional[str] = None,
                   environment: Environment = NEUTRAL_ENVIRONMENT) -> NPC:
    """
    Roadmap #29. Alleles drawn from the catalogue's frequencies under
    Hardy-Weinberg; environmental deviates drawn once, for life.
    """
    if sex is None:
        sex = "female" if rng.random() < 0.5 else "male"
    epigenome = Epigenome.default()
    epigenome.apply_developmental(environment)
    npc = NPC(
        name=name,
        genome=sample_founder_genome(rng),
        deviates=EnvironmentalDeviates.draw(rng, environment),
        sex=sex,
        epigenome=epigenome,
        birth_environment=environment,
    )
    npc.refresh_expression()
    # Sex-chromosome layer (roadmap #2) drawn LAST, so the autosomal genome
    # and environmental deviates above are sampled from the identical RNG
    # positions as before this layer existed -- the calibrated core stays
    # bit-for-bit. Founder X-linked genotypes are Hardy-Weinberg.
    npc.sex_chromosomes = sample_founder_sex_chromosomes(rng, sex)
    # Mitochondrial layer (roadmap #3), also at the tail. Founders are
    # homoplasmic wild-type by default (carrier_prob=0); the haplogroup is a
    # neutral maternal-lineage marker.
    npc.mito = sample_founder_mito(rng)
    return npc


def reproduce(mother: NPC, father: NPC, child_name: str,
              rng: np.random.Generator,
              environment: Environment = NEUTRAL_ENVIRONMENT,
              sex: Optional[str] = None,
              mutation: bool = True,
              map_scale: float = 1.0,
              mutation_rate_scale: float = 1.0) -> NPC:
    """
    One sexual reproduction event.

      1. Meiosis in each parent: crossovers drawn as a Poisson process on
         the centimorgan map, so linked loci co-segregate (roadmap #1).
      2. De novo point mutation at the Kong 2012 rate, with the 4:1
         paternal bias and the paternal-age slope (roadmap #12).
      3. The child draws its own environmental residual and GxE input
         from `environment` -- a reaction-norm intercept, not a fudge
         factor (roadmap #14).

    Note what is NOT here any more: no SBX phenotype blending, no
    heritable mutation sigma. The child's height is not drawn between its
    parents' heights; it is computed from the alleles it actually
    received. Regression to the mean, sibling variance and parent-
    offspring correlation are consequences, not settings.

    Epigenetic inheritance (roadmap #20) is now handled by
    `germline_transmit`: the child's epigenome starts at baseline and
    receives only the rare marks that survived reprogramming (base reset
    0.95, escapers 0.50, fidelity 0.40). The parents' lifetime
    methylation -- smoking, stress, age -- almost never crosses. This
    replaces v0.2's far-too-permissive 60%-fidelity / 30%-reset scheme.
    """
    if mother.sex == father.sex:
        raise ValueError(f"{mother.name} and {father.name} share sex {mother.sex}")
    if mother.sex == "male":
        mother, father = father, mother

    child_genome, n_dn = cross(mother.genome, father.genome, rng,
                               mother_age=mother.age, father_age=father.age,
                               mutation=mutation, map_scale=map_scale,
                               mutation_rate_scale=mutation_rate_scale)
    # Sex determination (roadmap #2): the father transmits his X (-> daughter)
    # or his Y (-> son). We resolve that single Bernoulli(0.5) choice HERE, at
    # the exact RNG position the old coin-flip occupied (one draw when `sex`
    # is None, none when it was supplied), so the germline and deviate draws
    # below -- and hence the autosomal child -- are stream-identical to before.
    # The actual X-linked transmission happens at the tail (see below).
    if sex is None:
        to_daughter = rng.random() < 0.5
        sex = "female" if to_daughter else "male"
    else:
        to_daughter = (sex == "female")

    # Germline: what little epigenetic state escapes reprogramming, then
    # this child's own developmental programming from its birth environment.
    child_epi = germline_transmit(mother.epigenome, father.epigenome, rng)
    child_epi.apply_developmental(environment)

    child = NPC(
        name=child_name,
        genome=child_genome,
        deviates=EnvironmentalDeviates.draw(rng, environment),
        sex=sex,
        epigenome=child_epi,
        generation=max(mother.generation, father.generation) + 1,
        parents=(mother.name, father.name),
        birth_environment=environment,
        de_novo_mutations=n_dn,
    )
    child.refresh_expression()
    # X-linked transmission (roadmap #2), drawn at the tail so it never
    # perturbs the autosomal stream above. The mother contributes a recombined
    # X; the father contributes the X or Y already chosen by `to_daughter`.
    if mother.sex_chromosomes is not None and father.sex_chromosomes is not None:
        child.sex_chromosomes = transmit_sex_chromosomes(
            mother.sex_chromosomes, father.sex_chromosomes, rng,
            transmit_paternal_x=to_daughter)
    # Mitochondrial transmission (roadmap #3): STRICTLY MATERNAL. The child's
    # mtDNA comes only from the mother, resampled through the bottleneck; the
    # father's mitochondria contribute nothing.
    if mother.mito is not None:
        child.mito = mother.mito.transmit(rng)
    return child


# ======================================================================
# Resemblance metrics
# ======================================================================

def continuous_similarity(a: NPC, b: NPC, traits: Optional[List[str]] = None) -> float:
    """
    1.0 = identical, 0.0 = maximally different. Each trait is compared on
    its standardised liability scale, so height (a 9 cm SD) and openness
    (a 0.15 SD) contribute equally rather than height dominating.
    """
    traits = traits or CONTINUOUS_TRAITS
    za = np.array([a.liability(t) for t in traits])
    zb = np.array([b.liability(t) for t in traits])
    # Difference of two independent standard normals has sd sqrt(2); scale
    # so that unrelated individuals score ~0.2 rather than ~0.9.
    rms = float(np.sqrt(np.mean((za - zb) ** 2))) / np.sqrt(2.0)
    return max(0.0, 1.0 - rms)


def genomic_relatedness(a: NPC, b: NPC) -> float:
    """
    Realised additive relatedness from the genotypes themselves (the GCTA
    estimator, Yang et al. 2010):

        A_ab = (1/L) * sum_j  (g_aj - 2p_j)(g_bj - 2p_j) / (2 p_j q_j)

    Expected 0.5 for parent-offspring and full sibs, 0 for unrelated.
    Sibs vary around 0.5 because meiosis is a lottery; parent-offspring
    does not (exactly half the genome, always). Seeing that asymmetry in
    the output is a good sign the recombination model is doing its job.
    """
    from .loci import ALT_FREQ, HETEROZYGOSITY
    xa = a.genome.dosage - 2.0 * ALT_FREQ
    xb = b.genome.dosage - 2.0 * ALT_FREQ
    ok = HETEROZYGOSITY > 0
    return float(np.mean(xa[ok] * xb[ok] / HETEROZYGOSITY[ok]))
