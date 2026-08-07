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
from .cnv import CopyNumber, sample_founder_copy_number, transmit_copy_number
from .inbreeding import (DeleteriousLoad, derived_rng, sample_founder_load,
                         transmit_load)
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

    # Recessive deleterious load (roadmap #31): rare, partially recessive
    # alleles at 2000 loci that carry no trait weight and are invisible in
    # the outbred phenotype, but become homozygous in proportion to F and so
    # produce inbreeding depression. A parallel layer like the two above;
    # None = inactive. Drawn from a SPAWNED generator, so unlike #2 and #3
    # it costs the caller's RNG stream nothing (see inbreeding.derived_rng).
    load: Optional["DeleteriousLoad"] = None

    # Copy-number state (roadmap #12): how many copies of each recurrent CNV
    # region this individual carries. Feeds the expression multiplier as
    # copy_number/2, so the normal diploid state is exactly 1.0 and inert.
    # None = layer inactive; also drawn from a spawned generator.
    copy_number: Optional["CopyNumber"] = None

    _phenotype_cache: Optional[Dict[str, object]] = field(default=None, repr=False)
    # Parent-of-origin state (roadmap #4). Derived from the genome, so it is
    # built once on first use and never invalidated -- the genome is fixed at
    # conception. Not a constructor argument: nothing should set it directly.
    _imprint_cache: Optional[object] = field(default=None, repr=False)

    # -------------------- phenotype --------------------

    def invalidate(self) -> None:
        """Call after mutating `expression` or the epigenome."""
        self._phenotype_cache = None

    def refresh_expression(self) -> None:
        """Recompute the expression multiplier and drop the phenotype cache.
        Called after every epigenome change.

        Composition, in the order the biology composes:

          1. the epigenome (#16) sets each locus's cis expression;
          2. the gene-regulatory NETWORK (#8) applies its trans multiplier;
          3. gene dosage (#12) scales by copy_number / 2.

        Copy number goes last because it is the crudest and most physical of
        the three: methylation and regulation modulate what a present gene
        does, while a deletion changes how many of it there are. At a default
        epigenome, no perturbation and normal copy number all three factors
        are exactly 1.0, so this is bit-for-bit identical to the pre-GRN
        engine (see test_grn.test_baseline_is_bit_for_bit)."""
        from .grn import NETWORK
        cis = self.epigenome.expression()
        expr = NETWORK.compose(cis, self.grn_perturbation or None)
        if self.copy_number is not None and not self.copy_number.is_normal:
            expr = expr * self.copy_number.dosage_multiplier()
        self.expression = expr
        self._phenotype_cache = None

    def apply_cnv(self, region: str, kind: str = "deletion",
                  parent: str = "maternal") -> None:
        """
        Give this NPC a copy-number variant and re-express (#12).

        The in-silico experiment API, the structural counterpart of
        `perturb_gene`: pathogenic CNVs occur at ~1e-4 per gamete, so waiting
        for one to arise in a simulated village is not a workable way to see
        what one does. `kind` is "deletion" or "duplication"; `parent`
        decides which haplotype carries it, which is recorded because
        15q11-q13 is imprinted.
        """
        from .cnv import REGIONS, CopyNumber, DELETED, DUPLICATED, region_index
        if region not in REGIONS:
            raise KeyError(f"unknown CNV region {region!r}")
        if self.copy_number is None:
            self.copy_number = CopyNumber.normal()
        row = 0 if parent == "maternal" else 1
        self.copy_number.haplotypes[row, region_index(region)] = (
            DELETED if kind == "deletion" else DUPLICATED)
        self.refresh_expression()

    def cnv_variants(self) -> List[Dict[str, object]]:
        """Every non-diploid region this NPC carries (#12). Empty is normal."""
        if self.copy_number is None:
            return []
        return self.copy_number.variants()

    def copies_of_region(self, region: str) -> int:
        """Copy number at one CNV region (#12). 2 is the normal diploid state."""
        if self.copy_number is None:
            return 2
        return self.copy_number.copies_of(region)

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

    def viability(self) -> float:
        """
        Absolute viability from the recessive deleterious load (#31): the
        product over load loci of (1 - s*x). Includes the baseline mutation
        load every individual pays, so it sits well below 1 even for an
        outbred NPC. 1.0 when the layer is inactive.
        """
        if self.load is None:
            return 1.0
        return self.load.viability()

    def mendelian_diagnoses(self) -> List:
        """
        Named recessive disorders this NPC expresses (diseases.py): the
        panel loci of the deleterious load that are homozygous. A pure
        read-out -- the fitness cost of each was already inside
        `viability()` before the locus had a name. Empty if the load layer
        is inactive.
        """
        if self.load is None:
            return []
        from .diseases import diagnoses
        return diagnoses(self.load)

    def mendelian_carrier_of(self) -> List:
        """Named recessive disorders carried heterozygous -- silent but
        transmissible. The visible tip of `load.n_carried`."""
        if self.load is None:
            return []
        from .diseases import carrier_of
        return carrier_of(self.load)

    def relative_viability(self) -> float:
        """
        Viability relative to an average outbred individual -- the number a
        mortality model should use, because the baseline mutation load is
        already inside any demographic rate fitted to real data. 1.0 means
        "an average outbred individual"; below 1 means this NPC carries more
        homozygous load than average, which is what being inbred does to you.
        Can exceed 1 for an unusually lightly-loaded individual.

        Two structurally different mechanisms compose here: the recessive
        deleterious load (#31), which is many alleles of tiny effect, and
        copy-number variants (#12), which are few of large effect. They
        multiply because they are independent causes of death.
        """
        w = 1.0 if self.load is None else self.load.relative_viability()
        # Copy-number variants carry their own fitness cost (#12). Composing
        # here rather than in a separate hazard is what turns the CNV
        # catalogue's de novo rates into an emergent mutation-selection
        # balance instead of a stipulated carrier frequency.
        if self.copy_number is not None:
            w *= self.copy_number.fitness()
        return w

    def realised_inbreeding(self) -> float:
        """
        F measured from this individual's own excess homozygosity rather than
        predicted from its pedigree (#31). See inbreeding.realised_inbreeding
        for why the two differ.
        """
        from .inbreeding import realised_inbreeding
        return realised_inbreeding(self)

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
            imp = self.imprint_state()
            self._phenotype_cache = {
                name: express(arch, liability(arch, self.genome.dosage,
                                              self.deviates, self.expression,
                                              imp, self.canalization(name)))
                for name, arch in ARCHITECTURE.items()
            }
        return self._phenotype_cache

    def phenotype_at_age(self, age: Optional[float] = None
                         ) -> Dict[str, object]:
        """
        The phenotype expressed at a given age (roadmap #13). Defaults to
        this NPC's current age.

        `phenotype()` returns the MATURE phenotype and is deliberately
        age-blind -- Stage 0's heritabilities were solved against that path,
        and published human h2 estimates are themselves measured on adults,
        so inserting an age factor into it would silently decalibrate the
        engine while every reported target stayed the same. The schedule
        therefore acts here, on the output, where it cannot reach the
        calibration.

        At `development.REFERENCE_AGE` this returns `phenotype()` exactly,
        which `validation.developmental_identity` asserts to floating point.
        """
        from .development import REFERENCE_AGE, express_at_age

        a = self.age if age is None else age
        mature = self.phenotype()
        if a == REFERENCE_AGE:
            return dict(mature)
        return {name: express_at_age(name, value, a, self.sex)
                for name, value in mature.items()}

    def height_at_age(self, age: Optional[float] = None) -> float:
        """
        Stature at a given age -- the trait the growth curve is fitted to.

        Goes straight to the one trait rather than through
        `phenotype_at_age`, which would build and discard the whole ~30-trait
        dict. This is called per person per tick by the snapshot buffer.
        """
        from .development import express_at_age

        a = self.age if age is None else age
        return float(express_at_age("height_cm", self.phenotype()["height_cm"],
                                    a, self.sex))

    def life_stage(self, age: Optional[float] = None) -> str:
        """
        A coarse label for the current developmental phase (#13). Boundaries
        are the growth curve's own: puberty opens at the age the fitted
        Preece-Baines curve starts its spurt, which differs by sex.
        """
        from .development import REFERENCE_AGE, peak_height_velocity_age

        a = self.age if age is None else age
        phv = peak_height_velocity_age(self.sex)
        if a < 2:
            return "infant"
        if a < phv - 2.0:
            return "child"
        if a < REFERENCE_AGE:
            return "adolescent"
        if a < 40:
            return "adult"
        if a < 65:
            return "midlife"
        return "senescent"

    def canalization(self, trait: str) -> float:
        """
        Developmental-buffering factor k for one trait (roadmap #14b).

        Keyed off `birth_environment`, not any current environment: Waddington's
        buffer operates DURING development, so it is the environment an
        individual developed in that decides how much cryptic genetic variation
        it expresses. Returns exactly 1.0 in any environment at or below the
        buffering threshold, which includes every calibrated setting.
        """
        from .canalize import canalization_factor
        return canalization_factor(self.birth_environment.stress, trait)

    def imprint_state(self):
        """
        Parent-of-origin state for this genome (roadmap #4). Cached, because
        it is a pure function of the genome and the genome never changes
        after conception.

        Nothing is stored across generations and no random numbers are drawn:
        `Genome.haplotypes[0]` is maternal and `[1]` paternal by construction,
        so germline erasure and re-establishment of imprints -- every egg
        maternally marked, every sperm paternally marked -- is exact and
        automatic. See imprint.py.
        """
        from .imprint import imprint_state
        if self._imprint_cache is None:
            self._imprint_cache = imprint_state(self.genome)
        return self._imprint_cache

    def liability(self, trait: str) -> float:
        return liability(ARCHITECTURE[trait], self.genome.dosage,
                         self.deviates, self.expression, self.imprint_state(),
                         self.canalization(trait))

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
    # ------------------------------------------------------------------
    # DETERMINISM NOTE -- read before adding a layer here.
    #
    # The two layers below (#2 sexchrom, #3 mito) CONSUME from the caller's
    # `rng`. Drawing them at the tail means the autosomal genome and
    # deviates above sit at the same RNG positions they did before those
    # layers existed, so THIS founder is bit-for-bit unchanged. It does not
    # follow that a SEQUENCE of founders is: the extra draws advance the
    # shared stream, so founder #0 is identical and #1 onward is not. Any
    # loop drawing N founders from one generator therefore drifted when
    # sessions 6 and 7 landed. The bit-for-bit claim for #2 and #3 is
    # per-individual, not per-sequence (session-9 audit).
    #
    # The layers after them (#31 load, #12 copy number) do NOT have that
    # caveat: they draw from a SPAWNED sub-generator, which advances the
    # seed sequence without touching the bit-generator state and so costs
    # the caller's stream nothing. See inbreeding.derived_rng. Retrofitting
    # the same call onto the two below would remove the caveat entirely,
    # at the cost of changing every figure and expectation seeded through
    # them -- deliberately not done, because the drift is statistically
    # harmless and the churn is not.
    #
    # Founder X-linked genotypes are Hardy-Weinberg.
    # ------------------------------------------------------------------
    npc.sex_chromosomes = sample_founder_sex_chromosomes(rng, sex)
    # Mitochondrial layer (roadmap #3), also at the tail. Founders are
    # homoplasmic wild-type by default (carrier_prob=0); the haplogroup is a
    # neutral maternal-lineage marker.
    npc.mito = sample_founder_mito(rng)
    # Deleterious-load layer (roadmap #31). Drawn from a SPAWNED generator
    # rather than from `rng`, so it consumes nothing from the caller's stream
    # and every draw above -- and every founder after this one -- is
    # byte-identical to a world without this layer. Founders are outbred by
    # construction: each haplotype is an independent Bernoulli(q).
    npc.load = sample_founder_load(derived_rng(rng))
    # Copy number (roadmap #12). Founders are diploid-normal, so this is a
    # no-op multiplier and refresh_expression above stays valid; see
    # cnv.sample_founder_copy_number for why they start clean.
    npc.copy_number = sample_founder_copy_number(derived_rng(rng))
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
    # Deleterious load (roadmap #31): one meiosis per parent at unlinked
    # loci, plus new mutation. Spawned generator again, so this costs the
    # caller's stream nothing. Requires both parents to carry the layer --
    # a child of NPCs built without it inherits nothing to be depressed by.
    if mother.load is not None and father.load is not None:
        child.load = transmit_load(mother.load, father.load, derived_rng(rng))
    # Copy number (roadmap #12): one haplotype from each parent, plus de novo
    # NAHR. Expression has to be recomputed if anything actually varies --
    # `refresh_expression` above ran before this layer existed on the child.
    # The re-expression is conditional so the overwhelmingly common
    # diploid-normal case costs nothing.
    if mother.copy_number is not None and father.copy_number is not None:
        child.copy_number = transmit_copy_number(
            mother.copy_number, father.copy_number, derived_rng(rng))
        if not child.copy_number.is_normal:
            child.refresh_expression()
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
