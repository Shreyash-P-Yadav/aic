"""Shared fixtures for the integration tests.

The generated world is expensive (~35 s) and read-only, so it is built once per
session and shared. No test mutates it.
"""

from __future__ import annotations

import pytest

from insight_copilot.datagen.pipeline import GeneratedWorld, generate_world

SEED = 20260329


@pytest.fixture(scope="session")
def world() -> GeneratedWorld:
    """Truth, eleven source extracts, the full defect catalog and the corpus."""
    return generate_world(seed=SEED)


@pytest.fixture(scope="session")
def clean_world() -> GeneratedWorld:
    """The same world with the defect catalog switched off.

    Used to prove a defect is *injected* rather than incidental: if a pathology is
    present with the injectors disabled, it was never the injector's doing.
    """
    return generate_world(seed=SEED, apply_defects=False)
