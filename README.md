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
      tools/          search_private_knowledge, search_gmail, read_email, read_email_thread
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
cp back-end/.env.example back-end/.env   # fill Google OAuth values and a dedicated Fernet key
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
- Chat, history, uploads and Gmail require verified Google sign-in. Active storage
  is owner-scoped; Gmail credentials are encrypted and OAuth is browser/account-bound.
  See [authentication and legacy cutover](back-end/README.md#authentication-and-private-storage)
  before using existing runtime data. Legacy data is inaccessible until an explicit
  backed-up migration or purge; public deployment still needs release acceptance.
- Sign in with Google, then **Connect Gmail** for live mailbox search. The agent
  searches metadata, selects relevant candidates, and reads only chosen messages
  or the latest messages of a Gmail thread. Live retrieval does not embed or
  automatically archive emails in Chroma.
- Gmail handles live email; Chroma document search is restricted to uploads.
  See [backend Gmail retrieval details](back-end/README.md#gmail-retrieval) for
  schemas, pagination, timezone configuration, and limits.
- `.env` files are gitignored — keep secrets out of the repo.
