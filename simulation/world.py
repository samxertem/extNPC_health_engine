"""
World: the living population and its turnover.
==============================================

This is the orchestrator the health engine never had. It owns every NPC (alive
and dead), advances the population one year per `step()`, and keeps the
sim-only bookkeeping (founder ancestry, screen position, partnerships, birth /
death ticks, deme membership, resource access) in a parallel `PersonMeta` table
so the tested `NPC` dataclass is never modified.

`step()` is a single simulated year:
    1. age every living NPC one year        (engine: simulate_aging)
    1b. migration between demes              (community.choose_migration)
    1c. recompute resource access            (resource_equity)
    2. resolve deaths                        (demography.death_probability)
       + any queued shock (plague / bottleneck)
    3. widowed survivors return to the pool
    4. pair fertile singles WITHIN their deme (Gale-Shapley, roadmap #30)
    5. couples may bear a child              (engine: reproduce)
    6. refit the genome PCA, reposition dots
    7. append a metrics row + narrate the chronicle

It runs inline (called by the Dash interval), so a given seed replays exactly.

Everything session 8 added (demes, migration, resource stratification,
exposures, shocks, F_ST, chronicle) is gated so that at the DEFAULT parameters
-- one deme, no migration, full equity, no exposures, no shocks -- not one
extra RNG draw happens and the world is bit-for-bit identical to session 4's.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from health_engine.medical import simulate_aging
from health_engine.npc import NPC, genomic_relatedness, random_founder, reproduce
from health_engine.traits import Environment, NEUTRAL_ENVIRONMENT

from .demography import (DemographyParams, death_probability, preference_adjuster,
                         stable_matching, wants_child)
from .community import (assign_founder_demes, choose_migration_weighted,
                        deme_label, deme_layout, fst, person_map_offset,
                        territory_radius)
from .events import (Shock, bottleneck_survivor_fraction,
                     famine_fertility_multiplier, famine_prenatal_nutrition,
                     plague_mortality_multiplier)
from .chronicle import Chronicle
from .embedding import GenomePCA
from .snapshots import SnapshotBuffer, capture as snapshot_capture
from .lineage import LineageRegistry
from . import metrics as M

# Given-name pools, one per sex; uniqueness guaranteed by appending a global
# counter. These are the two halves of the single alternating list that came
# before, in the same order, so FOUNDER names are unchanged: `_seed_founders`
# assigns `female if i % 2 == 0` and the old list alternated female/male, so
# index parity already lined up there. Only BIRTHS were mismatched, because a
# newborn's name was drawn before `reproduce()` had determined its sex.
_FEMALE_NAMES = [
    "Elira", "Ines", "Sena", "Mira", "Lena", "Nadia", "Zoe", "Yara",
    "Ada", "Selin", "Leyla", "Nora", "Ceren", "Derya", "Ilay", "Pelin",
]
_MALE_NAMES = [
    "Tomas", "Darius", "Kaan", "Bora", "Arda", "Emre", "Rustam", "Deniz",
    "Kerem", "Onur", "Baris", "Timur", "Efe", "Kaya", "Ozan", "Sarp",
]

# Kept so the interleaved order is still recoverable (and for anything that
# only needs "is this one of ours").
_NAMES = [n for pair in zip(_FEMALE_NAMES, _MALE_NAMES) for n in pair]


@dataclass
class PersonMeta:
    """Sim-only state hung alongside an NPC, keyed by name."""
    ancestry: Dict[str, float]
    birth_tick: int
    color: str = "#888888"
    xy: Tuple[float, float] = (0.0, 0.0)
    partner: Optional[str] = None
    n_children: int = 0
    last_birth_tick: int = -999
    death_tick: Optional[int] = None
    death_cause: str = ""
    # session-8 additions
    deme: int = 0
    resource_access: float = 1.0


class World:
    def __init__(self, n_founders: int = 12, seed: int = 7,
                 params: Optional[DemographyParams] = None,
                 environment: Environment = NEUTRAL_ENVIRONMENT) -> None:
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.params = params or DemographyParams()
        self.environment = environment
        self.tick = 0
        self._id = 0
        # per-sex position in the name pools; the `-N` suffix stays global
        self._name_seq: Dict[str, int] = {"female": 0, "male": 0}

        self.registry = LineageRegistry()
        self.pca = GenomePCA(refit_every=4)
        self.chronicle = Chronicle()
        self.shock_queue: List[Shock] = []
        self._last_migrations = 0

        # spatial world map: settlement coordinates (independent RNG, so the
        # genetic stream is untouched) + a decaying migration-flow matrix.
        self.deme_centers = deme_layout(self.params.n_demes, seed)
        self.territory_radius = territory_radius(self.deme_centers)
        self.migration_flow: Dict[Tuple[int, int], float] = {}

        self.people: Dict[str, NPC] = {}       # name -> NPC (all, alive+dead)
        self.living: List[NPC] = []
        # Full-pedigree Malecot kinship (#31), rebuilt lazily. Invalidated on
        # birth rather than updated in place: `Pedigree.add` drops its memo
        # tables, so adding one child at a time would clear the cache once per
        # birth and recompute every coefficient from scratch. Rebuilding once
        # per tick means all of that tick's F queries share one memo.
        self._pedigree = None
        self.meta: Dict[str, PersonMeta] = {}
        self.history: List[Dict[str, float]] = []
        # per-tick living headcount by dominant founder lineage
        self.lineage_history: List[Dict[str, int]] = []
        # Compact per-tick frames so the dashboard can scrub backwards.
        # `history` holds scalars only, which cannot rebuild a past map --
        # see simulation/snapshots.py for what is and is not retained.
        self.snapshots = SnapshotBuffer()
        # Notable events, for the timeline scrubber's markers:
        # [{"tick": int, "kind": str, "label": str}]
        self.event_log: List[Dict[str, object]] = []

        self._seed_founders(n_founders)
        self._reposition()
        # _record() captures frame 0 (the founding population) as a side
        # effect, so there is exactly one capture point for the whole class.
        self._record(n_births=n_founders, n_deaths=0)

    # -- naming ----------------------------------------------------------

    def _fresh_name(self, sex: str = "female") -> str:
        """
        A given name appropriate to `sex`, made unique by a global counter.

        The counter stays global (not per pool) so every name in the world is
        unique and the `-N` suffix still reads as birth order. Names consume
        no RNG, so this cannot perturb the genetic stream.
        """
        pool = _FEMALE_NAMES if sex == "female" else _MALE_NAMES
        base = pool[self._name_seq.get(sex, 0) % len(pool)]
        self._name_seq[sex] = self._name_seq.get(sex, 0) + 1
        self._id += 1
        return f"{base}-{self._id}"

    # -- environment from the exposure knobs -----------------------------

    def _environment_from_params(self) -> Environment:
        """Build the population-wide Environment from the exposure sliders.

        When every exposure sits at its neutral default we return the shared
        NEUTRAL_ENVIRONMENT object unchanged, so the epigenome/deviate draws are
        bit-for-bit identical to a world that never had exposure knobs."""
        p = self.params
        if (p.exposure_smoking == 0.0 and p.exposure_stress == 0.0
                and p.exposure_prenatal_nutrition == 1.0):
            return NEUTRAL_ENVIRONMENT
        return Environment(
            name="dynamic",
            stress=1.0 + 2.0 * p.exposure_stress,
            exposures={
                "smoking": p.exposure_smoking,
                "psychosocial_stress": p.exposure_stress,
                "prenatal_nutrition": p.exposure_prenatal_nutrition,
            },
        )

    # -- construction ----------------------------------------------------

    def _seed_founders(self, n: int) -> None:
        self.environment = self._environment_from_params()
        demes = assign_founder_demes(n, self.params.n_demes, self.rng)
        # balance the sexes so pairing is possible
        for i in range(n):
            sex = "female" if i % 2 == 0 else "male"
            name = self._fresh_name(sex)
            npc = random_founder(name, self.rng, sex=sex,
                                 environment=self.environment)
            npc.name = name
            # Founders arrive as adults of varied ages, not newborns, so
            # pairing and reproduction can begin immediately and the initial
            # age pyramid is realistic. Ageing them also advances their
            # epigenome and any early medical conditions honestly.
            start_age = int(self.rng.integers(self.params.pairing_age, 36))
            simulate_aging(npc, start_age, self.rng, self.environment)
            self.registry.register_founder(name)
            self.people[name] = npc
            self.living.append(npc)
            self.meta[name] = PersonMeta(
                ancestry=LineageRegistry.founder_ancestry(name),
                birth_tick=0, deme=demes[i],
            )
            self.meta[name].color = self.registry.color_hex(
                self.meta[name].ancestry, alive=True)

    # -- the yearly step -------------------------------------------------

    def step(self) -> Dict[str, float]:
        self.tick += 1
        p = self.params
        self.environment = self._environment_from_params()

        # queued shock for this tick (if any)
        shock = self.shock_queue.pop(0) if self.shock_queue else None
        plague_mult = 1.0
        famine_fert = 1.0
        birth_env = self.environment
        if shock is not None:
            self.log_event(shock.kind, f"{shock.kind} (magnitude "
                                       f"{shock.magnitude:.2f})")
            if shock.kind == "plague":
                plague_mult = plague_mortality_multiplier(shock.magnitude)
                self.chronicle.note_shock(
                    self.tick, f"a plague sweeps the land "
                               f"(hazard ×{plague_mult:.1f})")
            elif shock.kind == "famine":
                famine_fert = famine_fertility_multiplier(shock.magnitude)
                nut = famine_prenatal_nutrition(shock.magnitude)
                birth_env = Environment(
                    name="famine",
                    stress=self.environment.stress + 1.0,
                    exposures={**self.environment.exposures,
                               "prenatal_nutrition": nut})
                self.chronicle.note_shock(
                    self.tick, "a famine year — births collapse and this "
                               "cohort carries a lifelong DOHaD imprint")

        # 1. age everyone one year
        for npc in self.living:
            simulate_aging(npc, 1, self.rng, self.environment)

        # 1b. migration between demes (gene flow)
        self._last_migrations = self._migrate()

        # 1c. resource access under the equity setting
        self._update_resource_access()

        # 2. deaths
        n_alive = len(self.living)
        survivors: List[NPC] = []
        n_deaths = 0
        for npc in self.living:
            meta = self.meta[npc.name]
            prob = death_probability(npc, n_alive, p,
                                     resource_access=meta.resource_access)
            if plague_mult != 1.0:
                prob = 1.0 - (1.0 - prob) ** plague_mult   # exact hazard scaling
            if self.rng.random() < prob:
                self._kill(npc, cause="plague" if plague_mult != 1.0 else "age")
                n_deaths += 1
            else:
                survivors.append(npc)
        self.living = survivors

        # 2b. bottleneck cull (a founder crash)
        if shock is not None and shock.kind == "bottleneck":
            n_deaths += self._bottleneck(shock.magnitude)

        # 3-4. pair fertile singles by stable matching, WITHIN each deme
        self._form_couples()

        # 5. births, less those lost to inbreeding depression (#31)
        n_births, n_infant_deaths = self._reproduce(birth_env, famine_fert)
        n_deaths += n_infant_deaths

        # 6. layout
        self._reposition()

        # 7. metrics + narration
        row = self._record(n_births=n_births, n_deaths=n_deaths,
                           n_infant_deaths=n_infant_deaths)
        self.chronicle.observe(self)
        return row

    # -- death bookkeeping ----------------------------------------------

    def _kill(self, npc: NPC, cause: str = "age") -> None:
        npc.alive = False
        meta = self.meta[npc.name]
        meta.death_tick = self.tick
        meta.death_cause = cause
        meta.color = self.registry.color_hex(meta.ancestry, alive=False)
        # free the widow(er)
        if meta.partner and meta.partner in self.meta:
            pm = self.meta[meta.partner]
            if pm.partner == npc.name:
                pm.partner = None
        meta.partner = None

    def _bottleneck(self, magnitude: float) -> int:
        """Cull the living population down to a random survivor remnant."""
        frac = bottleneck_survivor_fraction(magnitude)
        n = len(self.living)
        k = max(2, int(n * frac))
        if k >= n:
            return 0
        keep_idx = set(self.rng.choice(n, size=k, replace=False).tolist())
        survivors, killed = [], 0
        for i, npc in enumerate(self.living):
            if i in keep_idx:
                survivors.append(npc)
            else:
                self._kill(npc, cause="bottleneck")
                killed += 1
        self.living = survivors
        self.chronicle.note_shock(
            self.tick, f"a bottleneck culls the population to {k} survivors")
        return killed

    # -- migration -------------------------------------------------------

    def _migrate(self) -> int:
        p = self.params
        # decay the flow matrix every year so routes fade when travel stops
        if self.migration_flow:
            self.migration_flow = {k: v * 0.85 for k, v in self.migration_flow.items()
                                   if v * 0.85 > 0.05}
        if p.migration_rate <= 0.0 or p.n_demes <= 1:
            return 0
        count = 0
        for npc in self.living:
            if self.rng.random() < p.migration_rate:
                meta = self.meta[npc.name]
                src = meta.deme
                # isolation by distance: nearer settlements exchange more genes
                dst = choose_migration_weighted(src, self.deme_centers, self.rng)
                meta.deme = dst
                key = (min(src, dst), max(src, dst))
                self.migration_flow[key] = self.migration_flow.get(key, 0.0) + 1.0
                # a migrant leaves their partner behind (mating is within-deme)
                if meta.partner and meta.partner in self.meta:
                    pm = self.meta[meta.partner]
                    if pm.partner == npc.name:
                        pm.partner = None
                    meta.partner = None
                count += 1
        return count

    # -- resource stratification ----------------------------------------

    def _update_resource_access(self) -> None:
        """
        Assign each living individual a resource-access value in [0, ~1.6].

        At full equity (1.0) everyone gets exactly 1.0 -- neutral, so the
        default world is unchanged. Below full equity, access is concentrated
        toward the numerically dominant *lineages* within each deme: a stylized
        family-wealth proxy (bigger established families command more of the
        commons). Access then gates mortality and fertility, producing
        differential survival/reproduction by stratum. This is environmental
        fitness variance / gene-environment correlation (roadmap #28), NOT a
        claim that any gene determines social status.
        """
        eq = self.params.resource_equity
        if eq >= 1.0:
            for npc in self.living:
                self.meta[npc.name].resource_access = 1.0
            return

        by_deme: Dict[int, List[NPC]] = defaultdict(list)
        for npc in self.living:
            by_deme[self.meta[npc.name].deme].append(npc)

        for members in by_deme.values():
            lin_count: Dict[str, int] = defaultdict(int)
            dom_of: Dict[str, str] = {}
            for npc in members:
                dom, _ = self.registry.dominant(self.meta[npc.name].ancestry)
                dom_of[npc.name] = dom
                lin_count[dom] += 1
            statuses = [lin_count[dom_of[npc.name]] for npc in members]
            lo, hi = min(statuses), max(statuses)
            for npc, s in zip(members, statuses):
                norm = (s - lo) / (hi - lo) if hi > lo else 0.5
                status_access = 0.4 + 1.2 * norm            # [0.4, 1.6]
                access = eq * 1.0 + (1.0 - eq) * status_access
                self.meta[npc.name].resource_access = float(access)

    # -- pairing ---------------------------------------------------------

    def _form_couples(self) -> None:
        p = self.params
        adjust = preference_adjuster(p)
        singles = [n for n in self.living
                   if self.meta[n.name].partner is None
                   and n.age >= p.pairing_age]
        # group by deme so mating is within-community (the island model)
        by_deme: Dict[int, List[NPC]] = defaultdict(list)
        for n in singles:
            by_deme[self.meta[n.name].deme].append(n)

        for members in by_deme.values():
            females = [n for n in members if n.sex == "female"]
            males = [n for n in members if n.sex == "male"]
            if not females or not males:
                continue
            for a, b in stable_matching(females, males, adjust=adjust):
                self.meta[a.name].partner = b.name
                self.meta[b.name].partner = a.name

    def _reproduce(self, birth_env: Environment, fertility_mult: float) -> int:
        p = self.params
        n_alive = len(self.living)
        by_name = {n.name: n for n in self.living}
        seen: set = set()
        births = 0
        infant_deaths = 0
        newborns: List[NPC] = []

        for npc in list(self.living):
            meta = self.meta[npc.name]
            partner_name = meta.partner
            if not partner_name or partner_name in seen or partner_name not in by_name:
                continue
            seen.add(npc.name)
            partner = by_name[partner_name]
            mother, father = (npc, partner) if npc.sex == "female" else (partner, npc)
            mmeta = self.meta[mother.name]
            years_since = self.tick - max(mmeta.last_birth_tick,
                                          self.meta[father.name].last_birth_tick)
            # fold resource access and any famine into the effective fertility
            eff_access = float(np.clip(mmeta.resource_access, 0.0, 1.0)) * fertility_mult
            if wants_child(mother, father, mmeta.n_children, years_since,
                           n_alive + births, p, self.rng,
                           resource_access=eff_access):
                child = self._make_child(mother, father, birth_env)
                # A birth happened either way -- the parents' counters and the
                # pedigree record it. Whether the child JOINS the living
                # population is decided by its realised recessive load (#31).
                mmeta.n_children += 1
                mmeta.last_birth_tick = self.tick
                self.meta[father.name].n_children += 1
                self.meta[father.name].last_birth_tick = self.tick
                if self.rng.random() < self._juvenile_survival(child):
                    newborns.append(child)
                    births += 1
                else:
                    self._kill(child, cause="inbreeding")
                    infant_deaths += 1

        self.living.extend(newborns)
        return births, infant_deaths

    def _juvenile_survival(self, child: NPC) -> float:
        """
        Probability a newborn survives to join the population, from its own
        recessive deleterious load (roadmap #31).

        RELATIVE viability, not absolute. The absolute figure carries the
        baseline mutation load every individual pays (~40%), which is already
        inside `death_probability`'s Gompertz-Makeham constants -- those were
        chosen against real life tables, and real life tables already contain
        it. Applying it again would halve every cohort for no biological
        reason. Dividing it out leaves the differential cost of being inbred,
        which is the thing the engine did not previously have.

        Note the residual: because individuals vary in load even at F = 0, and
        a probability cannot exceed 1, the lightly-loaded half of an outbred
        cohort gets no compensating bonus. That leaves a small constant
        juvenile mortality (~5%) at F = 0. It is constant across F, so it
        cannot manufacture a depression signal -- it shifts the intercept of
        ln S, never the slope.
        """
        strength = self.params.inbreeding_depression
        if strength <= 0.0 or child.load is None:
            return 1.0
        w = child.relative_viability()
        return w if strength == 1.0 else float(w ** strength)

    def _make_child(self, mother: NPC, father: NPC,
                    birth_env: Environment) -> NPC:
        # The child is conceived BEFORE it is named, because sex is decided
        # genetically inside `reproduce` (the father's X or Y, roadmap #2) and
        # the namer has to know it. Naming first is what produced female NPCs
        # called Emre and male ones called Nora. `reproduce` uses the name
        # only to populate the dataclass field -- it derives no randomness
        # from it -- so naming afterwards leaves the genetic stream untouched.
        child = reproduce(mother, father, "unnamed", self.rng,
                          environment=birth_env,
                          mutation_rate_scale=self.params.mutation_rate_scale,
                          map_scale=self.params.recombination_scale)
        name = self._fresh_name(child.sex)
        child.name = name
        self.people[name] = child
        ancestry = LineageRegistry.child_ancestry(
            self.meta[mother.name].ancestry, self.meta[father.name].ancestry)
        # a child is born into its mother's deme
        meta = PersonMeta(ancestry=ancestry, birth_tick=self.tick,
                          deme=self.meta[mother.name].deme)
        meta.color = self.registry.color_hex(ancestry, alive=True)
        self.meta[name] = meta
        self.invalidate_pedigree()      # a birth changes the parent map (#31)
        return child

    # -- layout & metrics ------------------------------------------------

    def _reposition(self) -> None:
        if not self.living:
            return
        dos = np.array([n.genome.dosage for n in self.living], dtype=float)
        self.pca.maybe_fit(dos, self.tick)
        xy = self.pca.transform(dos)
        for npc, pos in zip(self.living, xy):
            self.meta[npc.name].xy = (float(pos[0]), float(pos[1]))

    # -- pedigree (#31) ---------------------------------------------------

    def pedigree(self):
        """
        Malecot kinship over everyone who has ever lived here (#31).

        Cached; call `invalidate_pedigree()` after adding people. Founders are
        treated as unrelated, which is exactly true in this engine because
        `sample_founder_genome` draws every founder haplotype independently --
        a luxury real pedigree analysis does not have.
        """
        if self._pedigree is None:
            from health_engine.inbreeding import Pedigree
            self._pedigree = Pedigree.from_npcs(self.people.values())
        return self._pedigree

    def invalidate_pedigree(self) -> None:
        self._pedigree = None

    def inbreeding_of(self, name: str) -> float:
        """Wright's F for one individual, 0.0 for anyone not in the pedigree."""
        if name not in self.people:
            return 0.0
        return self.pedigree().inbreeding(name)

    def living_inbreeding(self) -> List[float]:
        ped = self.pedigree()
        return [ped.inbreeding(n.name) for n in self.living]

    def _mean_couple_relatedness(self) -> float:
        rels = []
        seen = set()
        for npc in self.living:
            partner = self.meta[npc.name].partner
            if partner and partner not in seen and partner in self.people:
                if self.people[partner].alive:
                    rels.append(genomic_relatedness(npc, self.people[partner]))
                    seen.add(npc.name)
        return float(np.mean(rels)) if rels else 0.0

    def _fst(self) -> float:
        if self.params.n_demes <= 1 or len(self.living) < 4:
            return 0.0
        by_deme: Dict[int, List[np.ndarray]] = defaultdict(list)
        for npc in self.living:
            by_deme[self.meta[npc.name].deme].append(npc.genome.dosage)
        blocks = [np.vstack(v) for v in by_deme.values() if len(v) >= 2]
        return fst(blocks)

    def _reproductive_skew(self) -> float:
        vals = [self.meta[n.name].n_children for n in self.living
                if n.age >= self.params.pairing_age]
        return M.gini(vals)

    def _record(self, n_births: int, n_deaths: int,
                n_infant_deaths: int = 0) -> Dict[str, float]:
        n_couples = sum(1 for n in self.living
                        if self.meta[n.name].partner is not None) // 2
        row = M.snapshot(self.tick, self.living, n_births, n_deaths,
                         n_couples, self._mean_couple_relatedness(),
                         fst=self._fst(),
                         reproductive_skew=self._reproductive_skew(),
                         n_migrations=self._last_migrations,
                         inbreeding=self.living_inbreeding(),
                         n_infant_deaths=n_infant_deaths)
        self.history.append(row)
        counts: Dict[str, int] = {}
        for npc in self.living:
            dom, _ = self.registry.dominant(self.meta[npc.name].ancestry)
            counts[dom] = counts.get(dom, 0) + 1
        self.lineage_history.append(counts)
        # Capture AFTER the step has fully settled. Read-only, so the RNG
        # stream is untouched and a default world stays bit-for-bit.
        self.snapshots.append(snapshot_capture(self))
        return row

    # -- timeline events --------------------------------------------------

    def log_event(self, kind: str, label: str) -> None:
        """Record a notable moment for the timeline scrubber's markers."""
        self.event_log.append({"tick": int(self.tick), "kind": kind,
                               "label": label})

    def frame_at(self, tick: Optional[int] = None) -> Optional[dict]:
        """Snapshot for `tick`, or the live frame when `tick` is None."""
        return self.snapshots.at(tick)

    # -- shock scheduling (called by the dashboard) ---------------------

    def queue_shock(self, kind: str, magnitude: float = 0.6) -> None:
        self.shock_queue.append(Shock(kind, magnitude))

    # -- helpers for the chronicle --------------------------------------

    def _dominant_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for npc in self.living:
            dom, _ = self.registry.dominant(self.meta[npc.name].ancestry)
            counts[dom.split("-")[0]] += 1
        return counts

    def dominant_lineage_name(self) -> Optional[str]:
        counts = self._dominant_counts()
        return max(counts, key=counts.get) if counts else None

    def living_lineage_set(self) -> Set[str]:
        return set(self._dominant_counts())

    # -- queries for the dashboard --------------------------------------

    def deme_summary(self) -> List[dict]:
        """Per-deme headcount + mean heterozygosity, for the community panel."""
        by_deme: Dict[int, List[NPC]] = defaultdict(list)
        for npc in self.living:
            by_deme[self.meta[npc.name].deme].append(npc)
        out = []
        for d in range(max(1, self.params.n_demes)):
            members = by_deme.get(d, [])
            het = float(np.mean([m.heterozygosity() for m in members])) if members else 0.0
            out.append({"deme": d, "label": deme_label(d),
                        "n": len(members), "heterozygosity": het})
        return out

    def map_demes(self) -> List[dict]:
        """Settlement records for the world-map panel: centre, radius, name,
        population, colour."""
        summ = {d["deme"]: d for d in self.deme_summary()}
        out = []
        for d in range(max(1, self.params.n_demes)):
            cx, cy = self.deme_centers[d]
            s = summ.get(d, {"n": 0, "heterozygosity": 0.0})
            out.append({"deme": d, "label": deme_label(d),
                        "x": float(cx), "y": float(cy),
                        "radius": self.territory_radius,
                        "n": s["n"], "heterozygosity": s["heterozygosity"]})
        return out

    def map_flows(self) -> List[dict]:
        """Active migration routes (src, dst endpoints + weight + distance)."""
        out = []
        for (i, j), w in self.migration_flow.items():
            xi, yi = self.deme_centers[i]
            xj, yj = self.deme_centers[j]
            out.append({"x0": float(xi), "y0": float(yi),
                        "x1": float(xj), "y1": float(yj),
                        "weight": float(w),
                        "distance": float(np.hypot(xi - xj, yi - yj))})
        return out

    def living_frame(self) -> List[dict]:
        """A plain-dict record per living NPC for the scatter + hover + map."""
        out = []
        for npc in self.living:
            meta = self.meta[npc.name]
            ph = npc.phenotype()
            dom, purity = self.registry.dominant(meta.ancestry)
            cx, cy = self.deme_centers[min(meta.deme, len(self.deme_centers) - 1)]
            ox, oy = person_map_offset(npc.name, self.territory_radius)
            out.append({
                "name": npc.name,
                "x": meta.xy[0], "y": meta.xy[1],
                "map_x": float(cx + ox), "map_y": float(cy + oy),
                "color": meta.color,
                "sex": npc.sex,
                "age": npc.age,
                "generation": npc.generation,
                "lineage": dom,
                "purity": round(purity, 2),
                "partner": meta.partner or "-",
                "children": meta.n_children,
                "deme": meta.deme,
                "deme_label": deme_label(meta.deme),
                "resource_access": round(meta.resource_access, 2),
                "height_cm": round(ph["height_cm"], 1),
                "bmi": round(ph["bmi"], 1),
                "epi_accel": round(npc.epigenetic_age_acceleration, 1),
                "conditions": len(npc.medical_conditions),
            })
        return out

    def history_columns(self) -> Dict[str, List[float]]:
        """History transposed to column arrays for plotting."""
        if not self.history:
            return {}
        keys = self.history[0].keys()
        return {k: [row[k] for row in self.history] for k in keys}
