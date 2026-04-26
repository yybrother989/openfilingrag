# Contributing to OpenFilingRAG

Thanks for taking the time to contribute. This is a research-grade RAG prototype for SEC filings — bug fixes, new retrieval intents, new data sources, and UI polish are all welcome.

Quick links: [Quickstart](README.md#quickstart) · [Architecture](README.md#architecture) · [Mock mode](README.md#mock-mode)

## Dev setup (90 seconds)

1. Fork and clone
2. `make install` — installs the package editable with dev extras
3. `cp .env.example .env` — fill in `SEC_EDGAR_USER_AGENT` (your name + email). API keys are **not required** for tests; see [Mock mode](README.md#mock-mode) for what runs offline.

You only need a Supabase project (free tier is fine) when you actually want to run `make api` end-to-end. For pure unit tests, skip it.

## Before opening a PR

```bash
make lint    # ruff + mypy
make test    # pytest in mock mode — no Postgres, no API keys needed
```

For UI changes, also run:

```bash
make api     # terminal 1
make demo    # terminal 2  → http://localhost:3000
```

…and verify the panel(s) you touched. If you can't test the UI in your environment, say so explicitly in the PR — don't claim success.

## Where to put what

| You're adding… | Touch this |
|---|---|
| A new retrieval intent / question type | [`app/graph/policies.py`](app/graph/policies.py) — add to the intent → `RetrievalPolicy` map |
| A new external data source | [`app/data_sources/`](app/data_sources/) — mirror the AlphaVantage / Massive client shape |
| A new graph node | [`app/graph/`](app/graph/) — register it in `workflow.py::build_langgraph` |
| A new HTTP endpoint | [`app/api/`](app/api/) — add a router and include it in [`app/main.py`](app/main.py) |
| A new agent-event UI card | [`frontend/components/ResearchToolUIs.tsx`](frontend/components/ResearchToolUIs.tsx) |
| A schema change | Add a new `00N_<name>.sql` under [`app/db/migrations/`](app/db/migrations/), update the ORM in [`app/db/models.py`](app/db/models.py), and apply via the Supabase SQL editor |

## Style

- Python: ruff + black, line length 100, type hints on public functions
- TypeScript: project ESLint config; prefer named exports
- No comments that just narrate what the code already says — only document the *why* when it's non-obvious
- New files: don't add license headers; the repo-level `LICENSE` covers everything

## Reporting issues

Use the [issue templates](.github/ISSUE_TEMPLATE). Always include:

- Python version (`python --version`)
- Whether you're on Supabase (and which region) or a local Postgres
- Mock mode on or off (`OPENAI_API_KEY` set?)
- The exact failing command and the full error output

## License

By contributing you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
