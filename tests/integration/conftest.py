"""Integration-test fixtures.

The expensive shared fixtures — the generated world and the ingested warehouse — live
in the root ``tests/conftest.py`` so the statistical gates can read the same warehouse
the integration gates built, rather than paying for a second historical load.
"""

from __future__ import annotations
