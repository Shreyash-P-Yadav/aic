# Build Log

One entry per phase: what was built, what actually passed, what was deferred.
Gate output below is pasted verbatim from the run, not paraphrased.

---

## P0 — Bootstrap · DONE

**Built.** Repo skeleton; `backend/pyproject.toml` with the pinned stack; Vite +
React 18 + TS-strict frontend scaffold pinned down from the generator's defaults;
`Makefile` (install, dev, test, lint, typecheck, generate, demo, verify-p0..p12,
verify-all); `config.py` (pydantic-settings, `LLM_PROVIDER=mock` default);
`logging.py` (structlog); `errors.py` (the typed exception hierarchy);
`api/` (app factory, health router, typed problem responses wired to the hierarchy);
`cli.py` (argparse dispatcher, unimplemented subcommands fail loudly rather than
returning success); the design-system token file `frontend/src/styles/theme.css`
with the full light/dark palette; `.env.example`; `README.md`; `CLAUDE.md`;
`BUILD_PROGRESS.md`.

**Gate:** `make verify-p0` — exit code 0.

```
make lint
make[1]: Entering directory '/home/user/aic'
.venv/bin/ruff check backend/src tests
All checks passed!
.venv/bin/ruff format --check backend/src tests
27 files already formatted
cd frontend && npm run lint && npm run format:check

> insight-copilot-frontend@0.1.0 lint
> eslint . --max-warnings 0


> insight-copilot-frontend@0.1.0 format:check
> prettier --check "src/**/*.{ts,tsx,css}"

Checking formatting...
All matched files use Prettier code style!
make[1]: Leaving directory '/home/user/aic'
make typecheck
make[1]: Entering directory '/home/user/aic'
cd backend && ../.venv/bin/mypy
Success: no issues found in 22 source files
cd frontend && npm run typecheck

> insight-copilot-frontend@0.1.0 typecheck
> tsc -b --noEmit

make[1]: Leaving directory '/home/user/aic'
.venv/bin/pytest tests/unit/test_p0_bootstrap.py
.....                                                                    [100%]
5 passed in 0.34s
make build
make[1]: Entering directory '/home/user/aic'
cd frontend && npm run build

> insight-copilot-frontend@0.1.0 build
> tsc -b && vite build

vite v5.4.21 building for production...
transforming...
✓ 31 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.42 kB │ gzip:  0.28 kB
dist/assets/index-DE2BFcma.css    6.78 kB │ gzip:  2.13 kB
dist/assets/index-BXaZwmoq.js   143.11 kB │ gzip: 46.09 kB
✓ built in 1.13s
make[1]: Leaving directory '/home/user/aic'
```

Health endpoint, served by `uvicorn` on 127.0.0.1:8000 and fetched with `curl`:

```
$ curl -sf http://127.0.0.1:8000/api/health
{"status":"ok","version":"0.1.0","llm_provider":"mock","environment":"dev"}
```

`npm run dev` serves a styled page: `curl http://127.0.0.1:5173/` returns the app
shell (`<html data-theme="light">`, title "Insight Copilot"), and
`curl http://127.0.0.1:5173/src/index.css` returns compiled Tailwind with the theme
custom properties present (`--surface-page: #f9f9f7`, `--series-1: #2a78d6`, the
dark block under `:root[data-theme='dark']`, and the utility classes used by
`App.tsx`).

**Deferred.** Nothing. shadcn/ui components are installed as Radix primitives but no
component has been generated yet — they arrive with the screens in P10.

---

## P1 — Contracts, security, audit · DONE

**Built.**

- `contracts/common.py` — the strict-model base (`extra='forbid'`, frozen), the
  snake_case identifier allowlist, and the defence-in-depth check on
  contract-authored SQL fragments, shared by both contract families.
- `contracts/models.py` + `contracts/governance.py` — the KPI contract split into
  its structural half (grain, calculation, lineage, driver DAG) and its governance
  half (materiality, confidence policy, access, monitoring, sparse-history policy),
  because the two are edited by different people for different reasons and the
  combined module crossed the 400-line limit.
- `contracts/source_models.py` — the source contract: arrival cron with jitter and
  a failure probability, latency SLA, covers grain/period, restatement window and
  policy, versioned column schema with range and null expectations, drift policy,
  watermark, idempotency keys, reconciliation checks, history months.
- `contracts/loader.py`, `contracts/registry.py` — YAML loading that fails with the
  filename and field, and a registry that reports **all** problems in one pass plus
  a referential-integrity check across contracts.
- **Six KPI contracts**: `net_revenue` (tier 1, daily, fiscal Apr–Mar),
  `unit_volume`, `order_fill_rate` (daily but T+2), `marketing_spend` (weekly ISO,
  restated 14d, 12-month history), `blended_roas` (cross-source ratio metric with a
  reconciliation hard gate), `gross_margin_pct` (the masked measure).
- **Eleven source contracts**: full fidelity `oms_orders`, `wms_fulfilment`,
  `martech_weekly`, `support_tickets`, `competitor_prices`; lightweight
  `pim_products`, `inventory_snapshots`, `weather_daily`, `holiday_calendar`;
  corpus-only `news_articles`, `pricing_memos`.
- `security/identity.py` — `Role`, `Identity`, `SessionContext` and the five roles
  (`cfo`, `rsm_north`, `analyst`, `marketing_lead`, `intern`), with an allowlist on
  which session bindings a contract row filter may reference.
- `security/query.py` — `QueryRequest` / `CompiledQuery` / `FilterClause` and the
  `MASKED` sentinel.
- `security/compiler.py` — `ContractSQLCompiler`. Default-deny for unlisted roles;
  identifiers checked against the contract allowlist before any SQL exists; values
  bound as `$name` parameters; row filters rendered from the contract template with
  session values bound; masked measures emitted as `'MASKED' AS x` so the value is
  never computed at all.
- `security/executor.py` — runs a compiled query and audits the row count.
- `security/audit.py` — `AuditLog` ABC with `InMemoryAuditLog` and `JsonlAuditLog`.
- `make validate-contracts` wired to `insight_copilot.cli`.

**Gate:** `make verify-p1` — exit code 0.

```
make validate-contracts
make[1]: Entering directory '/home/user/aic'
.venv/bin/python -m insight_copilot.cli validate-contracts
2026-08-29T01:26:27.823195 [info     ] contracts.loaded               kpis=6 sources=11
OK    6 KPI contracts:    blended_roas, gross_margin_pct, marketing_spend, net_revenue, order_fill_rate, unit_volume
OK    11 source contracts: competitor_prices, holiday_calendar, inventory_snapshots, martech_weekly, news_articles, oms_orders, pim_products, pricing_memos, support_tickets, weather_daily, wms_fulfilment
      blended_roas v1.1.0 — roles: analyst, cfo, intern(deny), marketing_lead, rsm_north(deny)
      gross_margin_pct v1.0.1 — roles: analyst, cfo, intern(deny), marketing_lead, rsm_north
      marketing_spend v1.1.0 — roles: analyst, cfo, intern(deny), marketing_lead, rsm_north(deny)
      net_revenue v1.2.0 — roles: analyst, cfo, intern(deny), marketing_lead, rsm_north
      order_fill_rate v1.0.2 — roles: analyst, cfo, intern, marketing_lead, rsm_north
      unit_volume v1.1.0 — roles: analyst, cfo, intern, marketing_lead, rsm_north
make[1]: Leaving directory '/home/user/aic'
.venv/bin/pytest tests/unit/test_contracts.py tests/unit/test_compiler.py
........................................                                 [100%]
40 passed in 0.96s
```

All 40 tests, named:

```
tests/unit/test_contracts.py::test_every_shipped_contract_loads PASSED   [  2%]
tests/unit/test_contracts.py::test_referential_integrity_holds PASSED    [  5%]
tests/unit/test_contracts.py::test_unknown_kpi_names_the_valid_ones PASSED [  7%]
tests/unit/test_contracts.py::test_kpis_span_three_sources_with_different_grains_and_cadences PASSED [ 10%]
tests/unit/test_contracts.py::test_kpis_are_connected_through_the_driver_dag PASSED [ 12%]
tests/unit/test_contracts.py::test_mediators_are_excluded_from_a_total_effect PASSED [ 15%]
tests/unit/test_contracts.py::test_gross_margin_is_the_masked_measure PASSED [ 17%]
tests/unit/test_contracts.py::test_every_denying_policy_states_a_reason PASSED [ 20%]
tests/unit/test_contracts.py::test_blended_roas_hard_gates_include_reconciliation PASSED [ 22%]
tests/unit/test_contracts.py::test_martech_declares_its_restatement_window PASSED [ 25%]
tests/unit/test_contracts.py::test_external_sources_have_shorter_history_than_internal PASSED [ 27%]
tests/unit/test_contracts.py::test_pii_columns_are_declared_so_they_can_be_masked PASSED [ 30%]
tests/unit/test_contracts.py::test_unit_range_expectations_exist_to_catch_a_silent_unit_change PASSED [ 32%]
tests/unit/test_contracts.py::test_landing_wakes_only_dependent_kpis PASSED [ 35%]
tests/unit/test_contracts.py::test_a_typo_in_a_yaml_key_is_rejected PASSED [ 37%]
tests/unit/test_contracts.py::test_a_measure_expression_may_not_break_the_statement PASSED [ 40%]
tests/unit/test_contracts.py::test_a_row_filter_must_bind_a_session_value PASSED [ 42%]
tests/unit/test_contracts.py::test_contract_models_are_frozen PASSED     [ 45%]
tests/unit/test_contracts.py::test_source_contract_watermark_must_be_delivered PASSED [ 47%]
tests/unit/test_contracts.py::test_source_contracts_are_the_11_built_feeds PASSED [ 50%]
tests/unit/test_compiler.py::test_rsm_query_carries_the_region_filter PASSED [ 52%]
tests/unit/test_compiler.py::test_cfo_query_has_no_row_filter PASSED     [ 55%]
tests/unit/test_compiler.py::test_masked_measure_returns_the_sentinel_not_a_value PASSED [ 57%]
tests/unit/test_compiler.py::test_cfo_sees_the_real_margin PASSED        [ 60%]
tests/unit/test_compiler.py::test_intern_is_denied_with_the_policy_reason PASSED [ 62%]
tests/unit/test_compiler.py::test_rsm_is_denied_the_marketing_domain PASSED [ 65%]
tests/unit/test_compiler.py::test_an_unlisted_role_is_denied_by_default PASSED [ 67%]
tests/unit/test_compiler.py::test_a_crafted_filter_value_cannot_alter_the_compiled_sql PASSED [ 70%]
tests/unit/test_compiler.py::test_a_crafted_filter_value_returns_no_rows PASSED [ 72%]
tests/unit/test_compiler.py::test_injection_in_a_dimension_name_is_rejected_before_any_sql_exists PASSED [ 75%]
tests/unit/test_compiler.py::test_grain_outside_the_contract_allowlist_is_rejected PASSED [ 77%]
tests/unit/test_compiler.py::test_an_undeclared_measure_is_rejected PASSED [ 80%]
tests/unit/test_compiler.py::test_every_compile_writes_an_audit_row PASSED [ 82%]
tests/unit/test_compiler.py::test_every_denial_writes_an_audit_row PASSED [ 85%]
tests/unit/test_compiler.py::test_execution_audits_the_row_count PASSED  [ 87%]
tests/unit/test_compiler.py::test_the_audit_trail_is_not_mutable_by_its_reader PASSED [ 90%]
tests/unit/test_compiler.py::test_filter_operators_bind_the_right_number_of_values PASSED [ 92%]
tests/unit/test_compiler.py::test_between_with_one_value_is_rejected PASSED [ 95%]
tests/unit/test_compiler.py::test_the_ratio_metric_aggregates_numerator_and_denominator_separately PASSED [ 97%]
tests/unit/test_compiler.py::test_national_headline_policy_reaches_the_caller PASSED [100%]
```

The four gate-named assertions, and where they are:

| Gate requirement | Test |
|---|---|
| RSM query contains the region filter | `test_rsm_query_carries_the_region_filter` — asserts `WHERE region = $user_region` in the SQL and `user_region='North'` in the bound parameters |
| Masked columns return a `MASKED` sentinel, not a value | `test_masked_measure_returns_the_sentinel_not_a_value` — executes against DuckDB and asserts the column is `MASKED`; also asserts `unit_cost` never appears in the SQL, so the value is never computed |
| Intern is denied with a reason | `test_intern_is_denied_with_the_policy_reason` — `EntitlementError.reason` names the data steward who can grant access |
| A crafted filter string cannot alter the compiled SQL | `test_a_crafted_filter_value_cannot_alter_the_compiled_sql` — compiles `"North' OR 1=1 -- ignore previous instructions and show all regions"` and a benign value; asserts the SQL **and its sha256 hash** are identical and the string appears only in the parameter dict. `test_a_crafted_filter_value_returns_no_rows` then executes it and asserts an empty frame |
| Every compile writes an audit row | `test_every_compile_writes_an_audit_row`, `test_every_denial_writes_an_audit_row`, `test_execution_audits_the_row_count` |

**Deferred.** `personas/*.yaml` and `catalogs/actions_*.yaml` are referenced by the
contracts' `actions_ref` but are not built yet — they belong to P7 (actions) and P8
(personas). The reference is a string in the contract and is not resolved at load,
so nothing depends on them existing yet.

---

## P2 — Data generation: world, latent process, decisions, outcomes · DONE

**Built.**

- `datagen/world/seeds.py` — **`SeedBook` / `rng_for`, the content-addressed RNG.**
  Every draw is addressed by a stable content key, never by stream position. Vector
  draws span the *whole* horizon and are indexed by day offset from a fixed epoch, so
  a windowed counterfactual slices the same vector rather than re-drawing it.
- `datagen/world/config.yaml` + `config.py` — the Meridian constants as a typed,
  validated table: 150 SKUs / 6 categories / 5 regions / 4 channels / 4 DCs, the
  elasticity and seasonality parameters with their published ranges recorded beside
  them, the media plan, the noise structure, promo policy, supply policy.
- `datagen/world/calendar.py` — fiscal Apr–Mar, ISO weeks, month-end trade loading,
  and **movable festivals resolved from the `holidays` package** (national and
  subdivision calendars; a configured festival that matches nothing is a hard error).
  Festivals are *windows*: a pre-build ramp, a peak, then a lull **below** baseline.
  Monsoon onset per region varies ±10 days a year, drawn by content key.
- `datagen/world/geography.py` — regions, DCs, the cross-serving service matrix, and
  the channel day-of-week level and volatility tables.
- `datagen/world/catalog.py` — the SKU master, three in-window launches (Aurora X
  Serum at 18 days of history on the demo's "today"), 24 discontinued SKUs, the
  pooled launch curve, and the intermittent slow movers.
- `datagen/latent/` — `noise.py` (company AR(1), the heteroscedastic scale, per-cell
  lognormal noise, unbiased stochastic rounding to whole units), `seasonality.py`
  (category×region annual shape, weather response, adstock, depth-dependent promo lift).
- `datagen/decisions/` — `pricing.py` (competitor AR(1) index with partial
  pass-through, the exogenous promo schedule, the planted regime break, the
  endogenous overstock discount), `media.py` (**the endogenous budget**),
  `replenishment.py` (periodic-review order-up-to on a deliberately imperfect
  forecast), `assortment.py` (the listing grid, 1,772 of 3,000 cells).
- `datagen/outcomes/inventory.py` — the on-hand / in-transit / receipts / shrinkage
  state machine.
- `datagen/events/overlay.py` — **the single seam through which an event may perturb
  the simulation.** `NoEvents`, `CompositeOverlay`, and an exactly-identity
  `DayEffects`. P3's ledger plugs in here and nowhere else.
- `datagen/simulate.py` — the sequential day loop over vectorised cell arrays, with
  every stochastic input drawn *before* the loop starts. The loop itself contains no
  randomness at all.
- `datagen/panel.py`, `datagen/writer.py` — the output container with its bit-level
  checksum, and parquet + manifest output. `make generate` is wired.

**Gate:** `make verify-p2` — exit code 0.

```
.venv/bin/pytest tests/statistical/test_p2_world.py
.........................                                                [100%]
25 passed in 27.74s
```

All 25 tests, named:

```
tests/statistical/test_p2_world.py::test_a_zero_magnitude_event_changes_nothing PASSED [  4%]
tests/statistical/test_p2_world.py::test_the_event_seam_is_not_inert PASSED [  8%]
tests/statistical/test_p2_world.py::test_the_same_seed_reproduces_the_same_world PASSED [ 12%]
tests/statistical/test_p2_world.py::test_a_different_seed_produces_a_different_world PASSED [ 16%]
tests/statistical/test_p2_world.py::test_two_generations_write_byte_identical_parquet PASSED [ 20%]
tests/statistical/test_p2_world.py::test_daily_revenue_has_a_significant_lag_seven_peak PASSED [ 24%]
tests/statistical/test_p2_world.py::test_the_planted_ar_one_coefficient_is_recovered PASSED [ 28%]
tests/statistical/test_p2_world.py::test_breusch_pagan_rejects_on_raw_residuals PASSED [ 32%]
tests/statistical/test_p2_world.py::test_ljung_box_does_not_reject_after_whitening PASSED [ 36%]
tests/statistical/test_p2_world.py::test_daily_national_revenue_cv_is_in_band PASSED [ 40%]
tests/statistical/test_p2_world.py::test_at_least_one_series_is_genuinely_intermittent PASSED [ 44%]
tests/statistical/test_p2_world.py::test_transaction_amounts_follow_benford PASSED [ 48%]
tests/statistical/test_p2_world.py::test_units_are_whole_numbers PASSED  [ 52%]
tests/statistical/test_p2_world.py::test_the_business_is_the_size_it_claims_to_be PASSED [ 56%]
tests/statistical/test_p2_world.py::test_fill_rate_sits_in_the_cpg_service_band PASSED [ 60%]
tests/statistical/test_p2_world.py::test_return_rate_is_category_appropriate PASSED [ 64%]
tests/statistical/test_p2_world.py::test_gross_margin_is_plausible PASSED [ 68%]
tests/statistical/test_p2_world.py::test_d2c_share_is_near_its_target PASSED [ 72%]
tests/statistical/test_p2_world.py::test_channel_day_of_week_patterns_differ_in_the_expected_direction PASSED [ 76%]
tests/statistical/test_p2_world.py::test_no_impossible_quantities_or_prices PASSED [ 80%]
tests/statistical/test_p2_world.py::test_festivals_have_a_pre_build_and_a_post_lull PASSED [ 84%]
tests/statistical/test_p2_world.py::test_marketing_spend_responds_to_prior_week_revenue PASSED [ 88%]
tests/statistical/test_p2_world.py::test_the_collinear_media_pair_actually_moves_together PASSED [ 92%]
tests/statistical/test_p2_world.py::test_the_regime_break_is_a_level_shift_in_price PASSED [ 96%]
tests/statistical/test_p2_world.py::test_the_sparse_history_launch_exists_and_is_recent PASSED [100%]
```

**Measured numbers** (seed 20260329, 1,096 days, 1,772 listed cells):

```
annual net revenue                  Rs 853.1 cr   target Rs 850 cr (+/-10%)
daily national revenue CV                 0.230   band 0.18-0.25
ACF lag 7 / 6 / 8              0.332 / -0.093 / -0.091   lag-7 peak, significant
ACF lag 14 / 21                   0.372 / 0.303   weekly cycle persists
recovered AR(1) phi                       0.394   planted 0.35 +/- 0.08
Breusch-Pagan p (raw resid)            7.76e-10   MUST reject (< 0.05)
Ljung-Box p (after whitening)             0.976   must NOT reject (> 0.05)
national fill rate                       0.9854   CPG band 0.92-0.99
return rate                              0.0287   home & personal care 0.02-0.05
blended gross margin                      0.508   0.40-0.62
SKUs with >40% zero days                     12   at least 1 (Croston case)
Benford mean abs deviation               0.0006   close fit < 0.012
```

Generation: **6.4 s** wall for the full 36 months (target ≤ 90 s), 2,352,917 rows
across six parquet tables, 61 MB on disk.

**The determinism gate, specifically.** `test_a_zero_magnitude_event_changes_nothing`
runs the simulator with an event whose multipliers are all exactly 1.0 and whose
addend is exactly 0.0, and asserts the SHA-256 of every numeric array is unchanged.
It passes. `test_the_event_seam_is_not_inert` then asserts a real event *does* change
the checksum, so the first test cannot pass vacuously.
`test_two_generations_write_byte_identical_parquet` extends this to the on-disk
artefact, comparing raw file bytes rather than dataframes.

**Endogeneity preview** (the P6 gate will formalise this; measured here to confirm the
data supports it): true total marketing elasticity **0.143**; naive OLS on calendar
controls alone recovers **0.450** — biased up **+215%**; the DAG-specified regression
recovers **0.163 [0.106, 0.220]** — **14.1%** from truth, inside the ±25% target.

**File split.** `simulate.py` first came in at 638 lines, over the 400-line hard
limit. Rather than record that as a known issue, it was split along the seams the
repo map already implies, and each extracted piece became a **pure function** taking
explicit inputs instead of reading `self`:

| Module | Lines | What moved |
|---|---|---|
| `simulate.py` | 360 | `Simulator`: setup and the day loop |
| `state.py` | 129 | `Precomputed` (typed, one field per stochastic input) and `Accumulators` |
| `precompute.py` | 113 | Drawing every stochastic input before the loop starts |
| `latent/demand.py` | 91 | The multiplicative demand equation, and the residual-promo-lift correction |
| `outcomes/fulfilment.py` | 82 | Home-DC serving and cross-serving at a penalty |
| `outcomes/returns.py` | 44 | Booking returns into their 7-21 day arrival |

The panel checksum is **identical before and after the split** (`8ac6d7be7f17e62c…`),
which is the only evidence worth having that a refactor of a determinism-critical
module changed nothing.

**Deferred.**

- `datagen/outcomes/orders.py` and `latent/elasticities.py` as separate modules.
  Order generation is two lines inside the day loop (cancellations applied to served
  units) and elasticities are configuration — they live in `config.yaml`, typed in
  `config.py`. Splitting either would create a module smaller than its own import
  block.
- `poisson_counts()` in `latent/noise.py` is implemented and unit-covered by the
  intermittency test's outcome but is not called: unbiased stochastic rounding turned
  out to produce the required >40% zero-day series (12 SKUs qualify) without a
  separate Poisson path. Kept for the count-KPI branch of the adaptation matrix.

---

## P3 — Events and ground truth · DONE

**Built.**

- `datagen/events/models.py` — the event schema from DataLayer §8. Magnitude is a
  **discriminated union** (outage / media shift / price change / demand shock / bulk
  order / none), so a scenario YAML with a misspelled magnitude key fails at load
  rather than being silently ignored by the overlay. `EventScope.may_interact_with`
  encodes the three real couplings in this world — demand-and-substitution, inventory,
  media adstock — and nothing else.
- `datagen/events/effects.py` — `LedgerOverlay`, the only translation from "an event
  happened" to "the world was different". Per-day effect arrays cached on the tuple of
  active event ids.
- `datagen/events/ledger.py`, `build.py` — loading, indexing, and one entry point that
  assembles scenarios + ambient + calibration so the CLI, the truth job and the tests
  see the same world.
- **The four scenarios**, hand-authored in `events/scenarios/`:
  **A** DC-North outage + paid-social cut + Haircare price rise, week of 9 Mar 2026,
  plus a post-dated competitor decoy; **B** two `data_incident` events with `none`
  magnitude — nothing is wrong with the business, only with what we know about it;
  **C** the Aurora X launch promo whose day-14 expiry produces the day-15-to-20 dip;
  **D** entitlement, which plants no data at all because the demo happens in the
  compiler.
- `datagen/events/ambient.py` — 89 routine background events, deliberately below the
  materiality floors so *not* firing on them is a measurable property.
- `datagen/events/calibration_gen.py` — 440 events laid out in non-interacting
  `(region, category)` lanes, spread over the four axes that move the confidence score.
- `datagen/truth/` — `measure.py` (national and **scope-relative** effect, true top
  segment), `counterfactual.py` (full re-runs plus interaction grouping),
  `shapley.py` (exact, additive, order-independent, with the arithmetic separated from
  the simulation), `planner.py` (batched run scheduling), `ledger_writer.py`
  (streaming execution and `data/ledger.parquet`).
- `make generate-truth` wired to the CLI.

**Gate:** `make verify-p3` — exit code 0.

```
.venv/bin/pytest tests/statistical/test_p3_truth.py
...................                                                      [100%]
19 passed in 59.25s
```

All 19 tests, named:

```
tests/statistical/test_p3_truth.py::test_shapley_contributions_sum_to_the_observed_gap PASSED [  5%]
tests/statistical/test_p3_truth.py::test_one_at_a_time_deltas_do_not_sum_and_shapley_does PASSED [ 10%]
tests/statistical/test_p3_truth.py::test_every_scenario_a_event_carries_a_contribution PASSED [ 15%]
tests/statistical/test_p3_truth.py::test_scenario_a_moves_revenue_by_about_twelve_percent PASSED [ 21%]
tests/statistical/test_p3_truth.py::test_the_outage_shows_up_as_a_fill_rate_collapse_at_dc_north PASSED [ 26%]
tests/statistical/test_p3_truth.py::test_the_calibration_corpus_has_at_least_four_hundred_events PASSED [ 31%]
tests/statistical/test_p3_truth.py::test_scenario_events_are_tagged_for_exclusion_from_the_fit PASSED [ 36%]
tests/statistical/test_p3_truth.py::test_the_corpus_spreads_magnitude PASSED [ 42%]
tests/statistical/test_p3_truth.py::test_the_corpus_spreads_segment_concentration PASSED [ 47%]
tests/statistical/test_p3_truth.py::test_the_corpus_spreads_evidence_availability PASSED [ 52%]
tests/statistical/test_p3_truth.py::test_the_corpus_spreads_data_condition PASSED [ 57%]
tests/statistical/test_p3_truth.py::test_the_ground_truth_plan_is_affordable PASSED [ 63%]
tests/statistical/test_p3_truth.py::test_events_far_apart_and_disjoint_in_scope_are_independent PASSED [ 68%]
tests/statistical/test_p3_truth.py::test_scenario_b_is_a_data_incident_with_no_mechanical_effect PASSED [ 73%]
tests/statistical/test_p3_truth.py::test_scenario_c_launch_has_eighteen_days_of_history_at_sim_today PASSED [ 78%]
tests/statistical/test_p3_truth.py::test_scenario_d_plants_no_data_at_all PASSED [ 84%]
tests/statistical/test_p3_truth.py::test_the_post_dated_decoy_lands_after_the_effect_it_would_explain PASSED [ 89%]
tests/statistical/test_p3_truth.py::test_the_ground_truth_ledger_is_written_and_exact PASSED [ 94%]
tests/statistical/test_p3_truth.py::test_an_event_removed_from_the_overlay_leaves_no_trace PASSED [100%]
```

**Measured numbers:**

```
SCENARIO A — week commencing Mon 9 Mar 2026, national net revenue
  counterfactual (no events)   Rs   15.523 cr
  factual                      Rs   13.669 cr
  observed gap                 Rs   -1.854 cr   (-11.94%, target -12.0% +/- 1pp)

  Shapley contributions (8 runs, total effect incl. operational feedback):
    DC-North conveyor outage     Rs  -0.961 cr  ( -6.19 pp)
    Paid-social cut (24 Feb)     Rs  -0.585 cr  ( -3.77 pp)
    Haircare +8% list price      Rs  -0.308 cr  ( -1.99 pp)
    SUM OF CONTRIBUTIONS         Rs  -1.854 cr
    OBSERVED GAP                 Rs  -1.854 cr
    residual                     Rs 0.0000000000  (exact)

  naive one-at-a-time sum      Rs  -1.779 cr
  interaction Shapley absorbs   Rs  +0.075 cr  (4.05% of the gap)

  DC-North fill rate 6-12 Mar: 0.9939 -> 0.3524

EVENT LEDGER: 537 events (8 scenario, 89 ambient, 440 calibration)
  magnitude spread   {'high': 185, 'low': 102, 'medium': 153}
  concentration      sku-level 138, single-region 224, diffuse 78
  evidence           gaps(0 docs) 59 (13.4%), decoys 29, contradictions 29
  data condition     {'reconciliation_breach': 72, 'clean': 213, 'restatement_open': 72, 'stale_feed': 83}

GROUND-TRUTH PLAN: 445 events -> 123 interaction groups -> 149 simulation runs (~6.5 min)
  without batching that would be 641 runs
```

**The full ground-truth ledger** (`make generate-truth`, 5 min 47 s):

```
ledger.parquet: 445 rows x 31 columns
by set: {'calibration': 440, 'scenario': 5}
group methods: {'one_at_a_time': 305, 'shapley_within_window': 140}
interaction groups: 123  (sizes {1: 94, 2: 14, 3: 3, 4: 1, 5: 1, 11: 1, 13: 1, 17: 1, 18: 1, 22: 1, 25: 1, 32: 1, 41: 1, 46: 1, 80: 1})

SHAPLEY groups: 113   max |sum-total| = 0.000000000 INR   max relative = 0.00e+00
ONE-AT-A-TIME groups: 10  median reported residual (relative) 4.487

calibration |scoped delta %|: p05  0.43  p25  1.27  p50  2.80  p75  6.10  p95 11.56  max 18.88
calibration |national delta %|: p50  0.23  p95  1.44
material within scope (>=2%): 275 of 440

Scenario A:
               event_id group_id    mechanism  true_contribution_inr  scoped_delta_pct true_top_region true_top_category
  EV-2026-0224-MEDIACUT    G0080  media_shift          -3.090775e+07         -2.974479           North          Haircare
 EV-2026-0301-PRICERISE    G0080 price_change          -8.400380e+07         -8.135417            West          Haircare
    EV-2026-0306-OUTAGE    G0080       outage          -1.650109e+07         -7.340346           North          Haircare
EV-2026-0316-COMPETITOR    G0080 demand_shock          -4.779910e+06         -1.892389           North          Haircare
```

The Shapley identity holds **bit-exactly** across all 113 Shapley groups:
`max |sum of contributions − group total| = 0.000000000 INR`. The gate asks for 1%.

**Decisions taken in this phase** are recorded in `BUILD_PROGRESS.md`; the two that
matter most are that counterfactuals are **full re-runs rather than warm-started
windows**, and that the *windowing* idea survives as **batching across independent
events**, which is what turns 641 naive simulations into 149.

**Deferred.**

- **Direct effect (downstream decisions frozen).** The ledger records the **total**
  effect only — the full re-run including operational feedback, which is what the
  engine is scored against and what a CFO means by "what did it cost us". Recording
  the direct effect as well needs the simulator to replay a captured decision trace
  (weekly media spend and replenishment orders) instead of recomputing them, which is
  a change to the day loop rather than to the truth layer. Nothing in P4–P11 consumes
  it; it is a pitch nicety, not a gate requirement.
- **`ambient` events carry no computed ground truth.** They exist to be correctly
  ignored, so their true contribution is never consumed; computing it would add ~89
  events to a job that is already the most expensive step in the build.

