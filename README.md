# Insight Copilot

A KPI intelligence-to-action engine. It watches business KPIs, detects genuine
anomalies, explains them with rigorous statistics, narrates them differently for
different job roles, **refuses to answer when the evidence is weak**, and recommends
actions tied to owners — with every number traceable to a computation and every
model call metered.

> **All data in this repository is simulated.** The company — Meridian Consumer
> Brands, an India-based home & personal care business — is fictional, and so are its
> products, customers, campaigns, incidents and documents. Every figure the
> application displays comes from a structural simulation, not from a real business.

## The principle

**Statistics decide; the model narrates.** Every number originates from SQL, NumPy,
or statsmodels. A language model may never produce, alter, or infer a numeric value,
a threshold, a confidence, or an action — enforced structurally, not by prompt: the
LLM cannot emit SQL, and a deterministic verifier checks every number in every
generated sentence against the computed evidence bundle before a human sees it.

## Status

Under construction, phase by phase. See `BUILD_PROGRESS.md` for what is built and
what is not, and `BUILD_LOG.md` for each phase's actual gate output.

## Quick start

```bash
make install          # python venv + npm install
make verify-p0        # lint, typecheck, tests, frontend build
make dev              # backend on :8000, frontend on :5173
```

The application runs **entirely offline with no API key**: `LLM_PROVIDER=mock` is the
default, and a zero-LLM template narrator exists for every persona and confidence
tier. Copy `.env.example` to `.env` only if you want to change something.

## Make targets

| Target | What it does |
|---|---|
| `make install` | Create `.venv`, install the backend editable with dev extras, `npm install` |
| `make lint` | ruff check + ruff format --check; eslint + prettier |
| `make typecheck` | `mypy --strict` on the backend; `tsc -b` on the frontend |
| `make test` | pytest + vitest |
| `make dev` | Backend (:8000) and frontend (:5173) together |
| `make build` | Production frontend build |
| `make generate` | Generate the simulated world, events, sources and corpus |
| `make demo` | One command: generate, backfill, ingest, run, pre-warm, serve |
| `make demo-reset` | Restore the pristine demo state |
| `make validate-contracts` | Validate every KPI and source contract |
| `make verify-pN` | The gate for build phase N |
| `make verify-all` | Every gate, in order |

Sections still to be written as the phases land: the architecture diagram, the four
scenario walkthroughs, role switching, the demo controls, the LLM-vs-computed
boundary table, and known limitations.

## Documentation

- `docs/CLAUDE-CODE-BUILD-PROMPT.md` — the build specification (authoritative)
- `docs/InsightCopilotv2FinalArchitecture.md` — the analytical architecture
- `docs/InsightCopilotDataLayerDesign.md` — data generation and intake design
- `docs/PRISMRound2Blueprint.md` — the governance, contract and persona design
