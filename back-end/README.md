# Backend

FastAPI app with LangGraph agents and a Chroma-backed knowledge pipeline.

## Package roles

| Package | Role |
|---|---|
| `api/` | HTTP surface only — thin routes |
| `agents/` | Classifier graph + general/private agents |
| `tools/` | Document search and separate Gmail search/message/thread tools |
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
- `GMAIL_TOKEN_ENCRYPTION_KEY` — dedicated Fernet key managed separately from data

Generate a key once with `python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
and store it in your local `.env` or deployment secret manager. A missing/invalid key
disables Gmail connection; it never falls back to plaintext storage. Back up the key
separately and restrict access. Losing it requires reconnecting Gmail. Never put
this key or the Google client secret in the frontend or commit them.

Frontend GIS Sign-In still uses `front-end/.env` → `VITE_GOOGLE_CLIENT_ID` (can be the same client ID).

## Data directories

- `data/uploads/v2/<owner digest>/` — generated upload storage names; original names are display metadata
- `data/chroma_db/` — active `knowledge_private_v2` collection, with owner/source filters
- `data/oauth/v2/<owner digest>.fernet` — encrypted, owner-bound Gmail credentials (files 0600, directory 0700)
- `fixtures/` — optional sample files checked into git

## Run

```bash
cd src
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Requires Redis (`redis://localhost:6379`) and Ollama for chat + embeddings.

## Authentication and private storage

Sign in with Google before using chat, history, upload, or Gmail status/connection.
Every private route uses the same bearer-token dependency. Tokens must pass Google's
signature, audience, issuer, lifetime and required-claim validation. Anonymous mode
and unsigned-token fallback are removed. `/chat` requires an explicit canonical UUID.
Thread registry creation/updates reserve immutable ownership atomically in Redis;
history and chat reject missing/corrupt ownership metadata. Checkpoints and long-term
memory use owner-scoped v2 namespaces. Foreign thread IDs return 404.

Document ingestion requires trusted identity and forces owner metadata. Reads and
replacement deletes filter by owner; chunk IDs also include the owner namespace.
The document tool receives identity from runnable configuration, outside the model's
argument schema. Live Gmail tools load only that identity's credentials and request
`userId="me"`. Uploaded files use generated IDs, so identical display names never
overwrite another upload.

`POST /auth/gmail/start` takes the bearer token in its header and returns
`{"authorization_url": "..."}`. Fetch it with `credentials: "include"`, then navigate
to the returned URL. State and PKCE live in Redis for ten minutes; `GETDEL` consumes
state once before any code exchange. An HttpOnly, SameSite=Lax cookie binds the
callback to the initiating browser. HTTPS redirect URIs use Secure cookies. The
returned Google account identity must match the initiating signed-in identity before
credentials are saved; account mismatch leaves existing credentials untouched.

For local development, open the frontend at `http://127.0.0.1:5173` when using the
default backend/redirect host `127.0.0.1`; set `FRONTEND_ORIGIN` to the same frontend
URL. Avoid mixing `localhost` and `127.0.0.1`: cross-site cookie rules can prevent
browser binding. Register these exact OAuth origins/redirects in Google Cloud.
For production, use HTTPS and a same-site frontend/backend topology.

Credentials use Fernet authenticated encryption, bind their payload to the owner,
and commit with a private temporary file plus atomic replacement. Legacy plaintext
credentials are not loaded. OAuth query strings are removed from the ASGI scope at
response start so Uvicorn access logs omit codes/state/rejected legacy token URLs;
responses also use `no-store` and `no-referrer`. Configure the upstream proxy to omit
OAuth query strings too. Current implementation references: [Google OAuth flow](https://googleapis.dev/python/google-auth-oauthlib/latest/reference/google_auth_oauthlib.flow.html),
[Redis GETDEL](https://redis.io/docs/latest/commands/getdel/), and
[Fernet](https://cryptography.io/en/stable/fernet/).

## Legacy data cutover

This version intentionally does not read the old shared `knowledge` collection,
unscoped checkpoints/registry, `ltm:user:*` memory, plaintext OAuth JSON, or original
upload paths. Old registry IDs cannot be claimed by a new user. No existing private
data is deleted or automatically assigned an owner.

Before rollout, stop old-version writes and take access-restricted backups of the
entire `data/` directory and the Redis database. Verify an isolated restore and
record the backup inventory/checksums without publishing contents. Choose an
explicit migration or purge policy for those backups and legacy stores.

The simplest supported cutover is verified users re-uploading their own documents,
reconnecting Gmail, and starting new conversations. If retaining old history or
memory is necessary, independently establish each resource's owner and implement a
reviewed offline migration into the v2 namespaces. Old `user_sub` metadata came from
an unsigned fallback and is insufficient evidence of ownership. Never assign
unowned documents or anonymous chats to whichever user signs in first. Purge legacy
stores only after backup/restore verification and an explicit retention decision.
These operational migration/purge steps remain required before public release.

## Gmail retrieval

The private agent plans Gmail-native queries itself, evaluates candidate metadata,
then reads selected messages before generating an answer. The earlier optimizer
and embedding-rerank helpers are not invoked by live retrieval. Gmail search has
no imports from the Chroma/embedding/ingestion pipeline and makes no archival writes.
The application still needs its model, Redis, and document-store setup to run chat.

- `search_gmail`: structured filters and/or native `raw_query`; returns `gmail_live`
  evidence with IDs, thread IDs, sender, recipients, subject, snippet, canonical
  timestamp, original Date header, labels, List-Id and Auto-Submitted. No body field.
  `max_results` controls a candidate batch (default 10, maximum 50). Each invocation
  scans at most 50 metadata records and 5 API pages, refilling after people filtering.
- `read_email`: one chosen message ID from the authorized mailbox, with at most
  6,000 body characters and `body_truncated`, plus attachment descriptors. Attachment
  data is not downloaded. Gmail access tokens never enter tool results.
- `read_email_thread`: a Gmail thread ID, distinct from an application chat ID.
  Fetches thread metadata, then bodies for the latest N messages (default 5, maximum
  10), presented oldest-to-newest. Returns total count, truncation, and partial errors.
  Gmail has no thread-message pagination; large threads still require their metadata
  response before body selection. Body limits apply to model-visible text, not the
  size of Google's full-message response or parsing allocation.

Search returns `next_page_token`, `search_complete`, scan/page counts, errors, and
an explicit `timestamp_desc_within_batch` order. Continue with `page_token` and the
same filters for more candidates. A sorted batch does not prove globally newest
results; finish pagination or disclose a bounded search. Read failures and deleted
messages are reported without discarding other evidence. Empty people-filter results
remain empty. No automatic retry changes sender, recipient, dates, subject,
attachments, direction or native query terms. The agent must ask before relaxing
an explicit user constraint; name ambiguity may still require clarification.

`internalDate` is preferred for chronological ordering; the Date header is preserved
and used only when that timestamp is unavailable. `GMAIL_TIMEZONE` accepts an IANA
timezone (default `UTC`, e.g. `America/New_York`). Calendar dates are converted to
epoch boundaries because Gmail date strings use PST. `time_range="yesterday"` and
`"today"` use calendar days; `"last_week"` means the previous Monday-to-Monday week.
`newer_than="7d"` is rolling seven days. Per-user timezone preferences are not yet
implemented; clarify the timezone when the server default differs from user intent.

Google HTTP calls have a 20-second socket timeout and one transient API retry;
credential refresh uses a timeout and restores persisted expiry. The private agent
allows 16 total tool calls per run, with at most 4 searches, 10 individual reads,
and 2 thread reads. These limits bound retrieval, but a full conversation-context
budget and end-to-end latency targets remain future work.

Uploaded-document retrieval filters both the verified owner and `source_type="upload"`.
Legacy entries need the explicit cutover above. Archived email is excluded from this
tool; no archival API is exposed. P0 enforcement has API regression coverage, while
legacy cutover and acceptance against controlled Google accounts and the deployment's
compatible Redis checkpointer remain pending. Public release is still blocked by
those checks and the remaining reliability/deployment tasks.

Reference: [Gmail API search and timezone behavior](https://developers.google.com/workspace/gmail/api/guides/filtering).

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

The P0 API suite also requires `redis-server` on PATH. It launches disposable Redis
with a private temporary Unix socket, no TCP listener, and no persistence. Chroma
uses temporary directories and deterministic embeddings. JWTs are locally signed;
Google certificate transport, inference, OAuth and mailbox responses are synthetic.
The actual application routes, auth validation, graph/tool routing, Redis Lua/state,
Chroma filtering and encrypted file store run normally. Checkpoints use LangGraph's
in-memory saver, so these tests do not establish hosted Redis module compatibility
or real Google acceptance. CI installs Redis before running the suite.

```bash
pylint back-end/src --rcfile=back-end/.pylintrc
ruff format --check --line-length 100 back-end/src tests scripts
pyright --project pyrightconfig.ci.json
python -m pytest -q
python scripts/evaluate_ai.py  # PYTHONPATH=back-end/src; needs application Ollama models
```

Frontend formatting uses Prettier 3.5.3; Python formatting uses Ruff 0.11.13,
and Python types use Pyright 1.1.403. Exact invocation commands are in the workflow.
