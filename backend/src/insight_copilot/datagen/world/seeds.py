"""Content-addressed randomness — the single most important function in the data layer.

To compute "what would have happened without event E", the simulator is re-run with
E removed and everything else identical. That only works if **removing an event does
not perturb any other random draw**. A single sequential RNG stream fails this: drop
one event and every subsequent draw shifts, so the "counterfactual" is contaminated
by noise differences that look exactly like a causal effect — and every ground-truth
number in the submission would be quietly wrong.

The fix is to address every draw by a stable *content key* rather than by stream
position::

    eps = rng_for("demand_noise", sku, region, channel).normal()

**On vector draws.** Constructing a Generator per scalar draw would cost ~1.15 M
constructions for a 36-month panel. Instead a key addresses a whole *cell* and the
draw is a vector over the full history, indexed by day offset from a fixed epoch::

    noise = rng_for("demand_noise", sku, region, channel).normal(size=n_days_total)

This is still content-addressed, because the index is a **date**, not a consumption
order. Two rules keep it honest, and both are enforced by the determinism test:

1. The vector always spans the *whole* configured history, never a window. A windowed
   counterfactual draws the full vector and slices it, so the same day always gets
   the same draw whatever window is being simulated.
2. A key is never reused for two different quantities. Add a leading label.
"""

from __future__ import annotations

from hashlib import blake2b
from typing import Protocol

import numpy as np

Key = str | int | float | bool | None
"""Key parts must have a stable ``repr``. Floats are permitted but discouraged."""

_DIGEST_BYTES = 8
"""64 bits of seed material. Collisions across the ~10^5 keys used here are
negligible (birthday bound ~10^-9), and a wider digest buys nothing measurable."""


class RNGSource(Protocol):
    """What every stochastic component depends on. Injected, never imported."""

    def __call__(self, *keys: Key) -> np.random.Generator: ...


class SeedBook:
    """Content-addressed RNG factory bound to one master seed.

    WHY a class rather than only a module function: tests must be able to run the
    whole generator under a *different* master seed to prove that the outputs move,
    and dependency injection is what makes that a one-line change rather than a
    monkeypatch of global state.
    """

    def __init__(self, seed: int) -> None:
        self._seed = seed

    @property
    def seed(self) -> int:
        """The master seed every key is combined with."""
        return self._seed

    def __call__(self, *keys: Key) -> np.random.Generator:
        """Return the generator addressed by ``keys``. Pure: same keys, same stream."""
        digest = blake2b(repr((self._seed, *keys)).encode(), digest_size=_DIGEST_BYTES).digest()
        return np.random.default_rng(int.from_bytes(digest, "big"))

    def integers(self, *keys: Key, low: int, high: int) -> int:
        """One integer in ``[low, high)``, addressed by ``keys``."""
        return int(self(*keys).integers(low, high))

    def normal(self, *keys: Key, size: int) -> np.random.Generator | np.ndarray:
        """A standard-normal vector addressed by ``keys``. See the module note."""
        return self(*keys).standard_normal(size)


def rng_for(*keys: Key, seed: int) -> np.random.Generator:
    """Free-function form of :class:`SeedBook`, for call sites that hold no book.

    The seed is required rather than read from settings, because a draw whose seed
    depends on ambient configuration is not content-addressed.
    """
    return SeedBook(seed)(*keys)
