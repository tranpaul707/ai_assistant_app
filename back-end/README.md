# Backend

FastAPI app with LangGraph agents and a Chroma-backed knowledge pipeline.

## Package roles

| Package | Role |
|---|---|
| `api/` | HTTP surface only — thin routes |
| `agents/` | Classifier graph + general/private agents |
| `tools/` | Tool functions the agent may call |
| `knowledge/` | Document load, chunk, ingest, retrieve, vector store |
| `llm/` | Chat model client |
| `memory/` | Redis thread checkpointer |

Future external sources (e.g. Microsoft Outlook via Graph) should land as
`tools/` + a dedicated service module — not inside LangGraph state, Redis,
or Chroma credentials.

## Data directories

- `data/uploads/` — saved uploads (gitignored)
- `data/chroma_db/` — vector index (gitignored)
- `fixtures/` — optional sample files checked into git

## Run

```bash
cd src
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```
