"""
A stable 2-D genome embedding for the live dot-cloud.
=====================================================

Each individual is placed by the first two principal components of its allele
dosage vector (0/1/2 alt-allele count at each of the ~500 loci). Distance on
the map approximates genetic distance, so lineages that stop interbreeding
visibly drift into separate regions -- the whole point of a genetic PCA.

Two stability problems have to be solved or the cloud is unwatchable:

1. **Sign flips.** A principal component is defined only up to a sign, so a
   fresh SVD each tick can mirror the entire population about an axis. We pin
   each new component's sign to the previous frame's.

2. **Axis drift.** As allele frequencies move, the PCA basis rotates slowly.
   We refit only every `refit_every` ticks and interpolate projected positions
   between refits, so dots glide rather than teleport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class GenomePCA:
    refit_every: int = 4
    mean_: Optional[np.ndarray] = None          # (L,)
    components_: Optional[np.ndarray] = None     # (2, L)
    _fitted_tick: int = -999

    def fit(self, dosages: np.ndarray) -> None:
        """dosages: (n, L) float. Fits mean + top-2 PCs, sign-stabilised."""
        if dosages.shape[0] < 3:
            # too few points for a meaningful PCA; fall back to identity-ish
            self.mean_ = dosages.mean(axis=0) if dosages.size else None
            return
        X = dosages.astype(np.float64)
        mean = X.mean(axis=0)
        Xc = X - mean
        # economy SVD; rows of Vt are the principal axes
        try:
            _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
        except np.linalg.LinAlgError:
            return
        comps = Vt[:2].copy()

        if self.components_ is not None:
            # sign-align each new PC to the corresponding old one
            for k in range(2):
                if np.dot(comps[k], self.components_[k]) < 0:
                    comps[k] = -comps[k]

        self.mean_ = mean
        self.components_ = comps

    def maybe_fit(self, dosages: np.ndarray, tick: int) -> None:
        if self.components_ is None or (tick - self._fitted_tick) >= self.refit_every:
            self.fit(dosages)
            self._fitted_tick = tick

    def transform(self, dosages: np.ndarray) -> np.ndarray:
        """(n, L) -> (n, 2). Returns zeros if not yet fitted."""
        if self.components_ is None or self.mean_ is None:
            return np.zeros((dosages.shape[0], 2))
        Xc = dosages.astype(np.float64) - self.mean_
        return Xc @ self.components_.T

    def transform_one(self, dosage: np.ndarray) -> np.ndarray:
        if self.components_ is None or self.mean_ is None:
            return np.zeros(2)
        return (dosage.astype(np.float64) - self.mean_) @ self.components_.T
