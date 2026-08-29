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
