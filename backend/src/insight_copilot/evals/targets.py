"""Every eval target, declared once.

Kept in its own module so a target cannot be relaxed in the same edit that misses it
without the diff showing both, and so a reader can see the whole bar the system is
being held to on one screen.
"""

from __future__ import annotations

ECE_TARGET = 0.10
"""Expected calibration error the system must stay under to claim its tiers mean
anything."""

ATTRIBUTION_MRE_TARGET = 0.20
"""Mean relative error on the named segment's share of the gap."""

DETECTION_RECALL_TARGET = 0.70
"""Recall matters more than precision here: a missed material movement is invisible,
whereas a false positive meets six confidence signals and an abstention path before it
reaches anyone. Set on high-detectability events, because the corpus plants quiet ones
below the noise floor on purpose."""

DETECTION_PRECISION_LIFT_TARGET = 1.0
"""Precision RELATIVE to the share of scanned days that fall inside some event window.

An absolute precision target is meaningless on a corpus this densely planted: with 61%
of days inside an event, a detector that flagged days at random would score 0.61 and
"pass" a 0.50 bar. Lift states the only thing worth claiming — that flagging is better
than not looking — and a lift below 1.0 says plainly that it is not."""

NUMERIC_FIDELITY_TARGET = 1.0
"""Every number in every sentence. Not 99%: one fabricated figure is the whole
product's credibility, which is why the verifier is deterministic."""

CITATION_COVERAGE_TARGET = 0.95
ENTITLEMENT_LEAKAGE_TARGET = 0.0
LATENCY_TARGET_MS = 5000.0
COST_PER_INSIGHT_TARGET_USD = 0.05

ELASTICITY_IMPROVEMENT_TARGET = 1.5
"""How many times closer the DAG-specified marketing elasticity must be to the planted
value than the naive one. The *level* is not identified at national weekly grain on this
world — recorded as a known issue with its measured number — but the *direction of the
improvement* is exactly what the endogeneity demonstration claims, so that is what is
graded."""

MATERIAL_GAP_FLOOR_INR = 1e6
"""A window whose total gap is under ten lakh is one the system would not publish at
all. Share error is only measured above it: the ratio of two near-zero numbers is
arithmetic noise, not a measurement of attribution."""

MIN_DISCRIMINATION_AUC = 0.55
"""A fitted calibration map is only ADOPTED when it discriminates. An isotonic fit on a
score that ranks correct and incorrect calls alike collapses to a constant at the base
rate: technically well calibrated, and useless. Deriving tier boundaries from such a
constant produces bands nothing can enter, which would silence the system on the
strength of a curve that measured nothing. Below this floor the map is reported as
measured-but-not-adopted and the contract's own bands stay in force — the system says
"uncalibrated", which is true, instead of claiming a calibration it has not earned."""

CHANCE_REGIONS = 5
"""Members of the largest gradeable dimension, for the chance baseline the accuracy
number is read against."""
