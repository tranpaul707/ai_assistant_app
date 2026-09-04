# Knowledge AI Assistant

Private knowledge assistant: React frontend + FastAPI backend with LangGraph routing, Chroma RAG, and Redis conversation memory.

## Layout

```text
knowledge_ai/
  front-end/          React + Vite UI
  back-end/
    src/
      api/            HTTP routes (/chat, /upload)
      agents/         LangGraph classifier + agent factories
      tools/          LangChain tools (RAG today; more later)
      knowledge/      load → chunk → ingest → retrieve → Chroma
      llm/            Local model client (Ollama)
      memory/         Redis checkpointer
    data/             Runtime only (gitignored): chroma_db/, uploads/
    fixtures/         Sample text for local experiments
    requirements.txt
  README.md
```

## Run locally

**Backend** (from `back-end/src`, with Redis + Ollama available):

```bash
cd back-end/src
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend:**

```bash
cd front-end
npm install
npm run dev
```

## Notes

- Uploaded files and the Chroma vector store live under `back-end/data/` and are **not** committed.
- Re-upload documents after a fresh clone to rebuild the knowledge base.
- `.env` is gitignored — keep secrets out of the repo.
