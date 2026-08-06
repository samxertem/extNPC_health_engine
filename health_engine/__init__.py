"""
extNPC Health Engine -- v0.3
============================

A reproduction / inheritance / medical-issues engine for the extNPC
framework (Uludagli et al.), rebuilt on real quantitative genetics.

Layout
------
    genetic_map.py   22 autosomes, physical (Mb) and genetic (cM) maps
    loci.py          ~50 named GWAS genes + ~450 peripheral SNPs
    genome.py        diploid genome, meiosis with crossover, mutation
    traits.py        genotype -> phenotype: A + D + I + GxE + E
    npc.py           the individual: genome + persistent deviates + life
    epigenome.py     lifetime-dynamic methylation, clock, germline firewall
    grn.py           gene-regulatory / omnigenic network (#8)
    sexchrom.py      sex chromosomes: X-linked, X-inactivation, sex-limited (#2)
    mito.py          mitochondria: maternal inheritance, heteroplasmy, bottleneck (#3)
    imprint.py       genomic imprinting: parent-of-origin silencing (#4)
    canalize.py      developmental buffering / cryptic variation (#14b)
    inbreeding.py    Malecot pedigree kinship + inbreeding depression (#31)
    cnv.py           copy-number variants as a gene-dosage multiplier (#12)
    development.py   life-stage-dependent expression: growth, senescence (#13)
    physiology.py    physiological state vector, hormones, action bias
    medical.py       acquired, non-heritable conditions
    mating.py        life-partner selection
    legacy.py        v0.2 operators (SBX, n-point crossover) for comparison
    validation.py    Hardy-Weinberg, Haldane, h^2, breeder's equation, PGS
    viz.py           figures

Roadmap status: THE ENGINE ROADMAP IS CLOSED as of session 11.
Stage 0 (#1, #7, #9, #10, #29, #32), Stage 1 (epigenetics #15-#20,
physiological state vector #21-#27, gene-regulatory network #8),
Stage 2 (sex chromosomes #2, mitochondria #3, imprinting #4,
canalization #14b, structural variants #12, developmental trajectory #13)
and Stage 3 (stable matching #30, inbreeding depression #31) are all done.
What remains is scientific debt and the LLM harness, not roadmap items --
see reads/REPORT.md.
"""

from .epigenome import (DEFAULT_GERMLINE_POLICY, Epigenome, GermlineResetPolicy,
                        MarkClass, germline_transmit, locus_class)
from .genetic_map import AUTOSOMES, haldane_recombination_fraction
from .grn import NETWORK, RegulatoryNetwork, network_summary
from .genome import Genome, cross, meiosis, sample_founder_genome
from .imprint import (IMPRINTED, ImprintedLocus, ImprintState, imprint_state,
                      parent_of_origin_report, relax_imprint)
from .canalize import (CANALIZATION_THRESHOLD, canalization_factor,
                       expected_heritability, is_decanalizing)
from .cnv import (REGIONS, CNVRegion, CopyNumber, birth_prevalence,
                  equilibrium_frequency, expected_de_novo_fraction, induce,
                  predicted_mean_shift, sample_founder_copy_number,
                  transmit_copy_number)
from .development import (GROWTH, MATURATION, REFERENCE_AGE, growth_factor,
                          maturation_offset, peak_height_velocity_age,
                          schedule_summary, stature_fraction)
from .inbreeding import (SPECTRUM, DeleteriousLoad, LoadSpectrum, Pedigree,
                         directional_dominance, excess_mortality,
                         first_cousin_excess_mortality, lethal_equivalents,
                         predicted_depression, realised_inbreeding,
                         sample_founder_load, transmit_load)
from .loci import LOCI, N_LOCI, describe, locus_index, pleiotropic_genes
from .medical import ACTION_IMPACT_MAP, MedicalCondition, simulate_aging
from .mito import (MitoGenome, oxphos_capacity, sample_founder_mito)
from .npc import (NPC, continuous_similarity, genomic_relatedness,
                  random_founder, reproduce)
from .physiology import (ACTION_CLASSES, HormoneParams, PhysiologicalState,
                         derive_hormone_priors, kl_divergence)
from .sexchrom import (SexChromosomes, X_LOCI, sample_founder_sex_chromosomes,
                       transmit_sex_chromosomes, x_linked_prevalence)
from .traits import (ARCHITECTURE, CONTINUOUS_TRAITS, CATEGORICAL_TRAITS,
                     OCEAN_TRAITS, TRAIT_TABLE, Environment,
                     architecture_summary, loci_for_trait, traits_touched_by)

__version__ = "0.5.0"

__all__ = [
    "AUTOSOMES", "haldane_recombination_fraction",
    "NETWORK", "RegulatoryNetwork", "network_summary",
    "Genome", "cross", "meiosis", "sample_founder_genome",
    "LOCI", "N_LOCI", "describe", "locus_index", "pleiotropic_genes",
    "ACTION_IMPACT_MAP", "MedicalCondition", "simulate_aging",
    "NPC", "random_founder", "reproduce", "continuous_similarity",
    "genomic_relatedness",
    "Epigenome", "GermlineResetPolicy", "DEFAULT_GERMLINE_POLICY",
    "MarkClass", "germline_transmit", "locus_class",
    "PhysiologicalState", "HormoneParams", "ACTION_CLASSES",
    "derive_hormone_priors", "kl_divergence",
    "SexChromosomes", "X_LOCI", "sample_founder_sex_chromosomes",
    "transmit_sex_chromosomes", "x_linked_prevalence",
    "MitoGenome", "oxphos_capacity", "sample_founder_mito",
    "IMPRINTED", "ImprintedLocus", "ImprintState", "imprint_state",
    "parent_of_origin_report", "relax_imprint",
    "CANALIZATION_THRESHOLD", "canalization_factor", "expected_heritability",
    "is_decanalizing",
    "SPECTRUM", "DeleteriousLoad", "LoadSpectrum", "Pedigree",
    "directional_dominance", "excess_mortality",
    "first_cousin_excess_mortality", "lethal_equivalents",
    "predicted_depression", "realised_inbreeding", "sample_founder_load",
    "transmit_load",
    "REGIONS", "CNVRegion", "CopyNumber", "birth_prevalence",
    "equilibrium_frequency", "expected_de_novo_fraction", "induce",
    "predicted_mean_shift", "sample_founder_copy_number",
    "transmit_copy_number",
    "GROWTH", "MATURATION", "REFERENCE_AGE", "growth_factor",
    "maturation_offset", "peak_height_velocity_age", "schedule_summary",
    "stature_fraction",
    "ARCHITECTURE", "TRAIT_TABLE", "Environment", "OCEAN_TRAITS",
    "CONTINUOUS_TRAITS", "CATEGORICAL_TRAITS",
    "architecture_summary", "loci_for_trait", "traits_touched_by",
    "__version__",
]
