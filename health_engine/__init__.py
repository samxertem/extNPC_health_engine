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
    physiology.py    physiological state vector, hormones, action bias
    medical.py       acquired, non-heritable conditions
    mating.py        life-partner selection
    legacy.py        v0.2 operators (SBX, n-point crossover) for comparison
    validation.py    Hardy-Weinberg, Haldane, h^2, breeder's equation, PGS
    viz.py           figures

Roadmap status: Stage 0 complete (#1, #7, #9, #10, #29, #32; #12 mostly).
Stage 1 COMPLETE: epigenetics (#15-#20), physiological state vector
(#21-#27), gene-regulatory / omnigenic network (#8, grn.py). Stage 2 in
progress: sex chromosomes (#2, sexchrom.py), mitochondria (#3, mito.py)
and genomic imprinting (#4, imprint.py) done; #13 pending.
See reads/REPORT.md.
"""

from .epigenome import (DEFAULT_GERMLINE_POLICY, Epigenome, GermlineResetPolicy,
                        MarkClass, germline_transmit, locus_class)
from .genetic_map import AUTOSOMES, haldane_recombination_fraction
from .grn import NETWORK, RegulatoryNetwork, network_summary
from .genome import Genome, cross, meiosis, sample_founder_genome
from .imprint import (IMPRINTED, ImprintedLocus, ImprintState, imprint_state,
                      parent_of_origin_report, relax_imprint)
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
    "ARCHITECTURE", "TRAIT_TABLE", "Environment", "OCEAN_TRAITS",
    "CONTINUOUS_TRAITS", "CATEGORICAL_TRAITS",
    "architecture_summary", "loci_for_trait", "traits_touched_by",
    "__version__",
]
