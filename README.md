# Knowledge AI Assistant

Private knowledge assistant: React frontend + FastAPI backend with LangGraph routing, Chroma RAG, Gmail tools, and Redis conversation memory.

## Layout

```text
knowledge_ai/
  front-end/          React + Vite UI
  back-end/
    src/
      api/            HTTP routes (/chat, /upload, /auth/gmail, /threads)
      agents/         LangGraph classifier + agent factories
      tools/          search_private_knowledge, search_gmail
      knowledge/      load → chunk → ingest → retrieve → Chroma
      services/gmail/ Gmail OAuth + API (tokens stay server-side)
      llm/            Local model client (Ollama)
      memory/         Redis checkpointer + thread registry
      core/           Settings / Google ID-token verify
    data/             Runtime only (gitignored): chroma_db/, uploads/, oauth/
    fixtures/         Sample text for local experiments
    requirements.txt
    .env.example
  README.md
```

## Run locally

**Backend** (from `back-end/src`, with Redis + Ollama available):

```bash
cp back-end/.env.example back-end/.env   # fill Google OAuth web client values
cd back-end/src
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend:**

```bash
cd front-end
cp .env.example .env   # VITE_GOOGLE_CLIENT_ID
npm install
npm run dev
```

## Notes

- **New Chat** creates a fresh `thread_id` (empty agent memory). Previous chats remain in Redis and are selectable.
- Uploaded files, Chroma, and Gmail OAuth tokens live under `back-end/data/` and are **not** committed.
- Sign in with Google, then **Connect Gmail** for mailbox search. Retrieved emails are auto-ingested into Chroma.
- `.env` files are gitignored — keep secrets out of the repo.
