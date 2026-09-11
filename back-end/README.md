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
