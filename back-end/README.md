# Backend

FastAPI app with LangGraph agents and a Chroma-backed knowledge pipeline.

## Package roles

| Package | Role |
|---|---|
| `api/` | HTTP surface only — thin routes |
| `agents/` | Classifier graph + general/private agents |
| `tools/` | Tool functions the agent may call (`search_private_knowledge`, `search_gmail`) |
| `knowledge/` | Document load, chunk, ingest, retrieve, vector store |
| `services/` | External APIs (Gmail) — tokens stay here, not in LangGraph/Redis/Chroma |
| `llm/` | Chat model client |
| `memory/` | Redis checkpointer + conversation thread registry |
| `core/` | Settings / env |

## Environment

Copy `.env.example` to `.env` and fill Google OAuth values:

- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — Web application client
- `GOOGLE_REDIRECT_URI` — must match Cloud Console (default `http://127.0.0.1:8000/auth/gmail/callback`)
- `FRONTEND_ORIGIN` — Vite origin for post-OAuth redirect

Gmail OAuth tokens are stored under `data/oauth/` (gitignored). Never put the client secret in the frontend.

Frontend GIS Sign-In still uses `front-end/.env` → `VITE_GOOGLE_CLIENT_ID` (can be the same client ID).

## Data directories

- `data/uploads/` — saved uploads (gitignored)
- `data/chroma_db/` — vector index (gitignored)
- `data/oauth/` — Gmail refresh tokens per Google `sub` (gitignored)
- `fixtures/` — optional sample files checked into git

## Run

```bash
cd src
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Requires Redis (`redis://localhost:6379`) and Ollama for chat + embeddings.

## CI production checks

`.github/workflows/production_check.yml` runs on pull requests and pushes to
`main`/`master`. It checks Python/TypeScript lint, formatting, and types; clean
dependency installation; tests; frontend production build; static security
analysis; workflow syntax; and backend Docker build/startup/API registration.
Checks report existing findings and do not automatically rewrite source files.
Python installs currently use unpinned runtime requirements; a successful clean
install does not establish reproducibility until dependencies are locked.

The container smoke check verifies startup and API routes only. It does not
prove Redis, Ollama, Google OAuth, authenticated chat, or persistent storage work
in a hosted deployment. Deployment hosting and continuous monitoring remain to
be configured.

Weekly Mondays at 09:17 UTC, and on manual runs, the workflow provisions isolated
Ollama models and evaluates routing, synthetic document retrieval, grounded
answers, and abstention. Results are uploaded as an `ai-evaluation` artifact.
These CPU evaluations may be slow; model tags currently follow the application
defaults and are not immutable digests. No real Gmail account or private files
are used. Extend the initial fixtures and establish latency budgets before using
this small suite as a release gate.

Optional deployment probes run weekly, manually, and after successful GitHub
deployment-status events once repository variable `DEPLOYMENT_HEALTH_URL` is
set. Until then, a workflow notice reports that monitoring is pending. The URL
must be a public HTTPS readiness endpoint returning HTTP 200 with JSON
`{"status":"ok"}` or `{"status":"ready"}`. The eventual deploy workflow must
publish deployment-status events; this workflow does not deploy the application.
Enable GitHub Actions failure notifications separately.

Useful local commands, run from the repository root after installing CI tools:

```bash
pylint back-end/src --rcfile=back-end/.pylintrc
ruff format --check --line-length 100 back-end/src tests scripts
pyright --project pyrightconfig.ci.json
python -m pytest -q
python scripts/evaluate_ai.py  # PYTHONPATH=back-end/src; needs application Ollama models
```

Frontend formatting uses Prettier 3.5.3; Python formatting uses Ruff 0.11.13,
and Python types use Pyright 1.1.403. Exact invocation commands are in the workflow.
