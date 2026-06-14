# corporate-gifting-ai

A WhatsApp conversational assistant that helps corporate buyers find the right gifts for their
team or clients. It chats naturally — asking about occasion, headcount, budget, theme, branding,
and delivery — searches an internal product catalog (structured SQL filters + semantic vector
search), falls back to a web search when the catalog has nothing great for a niche ask, and uses
an LLM to reason over the candidates and present a justified, ranked shortlist over WhatsApp.

```
WhatsApp user <-> Meta WhatsApp Cloud API <-> FastAPI webhook <-> LangGraph agent
                                                  |                    |
                                            Postgres (catalog,    OpenAI GPT (chat +
                                            sessions, audit log)  structured output)
                                                  |                    |
                                              Qdrant (semantic     Tavily (web search
                                              product search)      fallback)
```

One inbound WhatsApp message -> one `graph.ainvoke()` over a compiled LangGraph `StateGraph` ->
zero-or-more outbound WhatsApp sends -> one write of `AgentState` back to
`conversation_sessions.session_state` (JSONB) — which is what makes a stateless webhook capable
of carrying a multi-turn conversation forward.

## Project layout

```
app/
├── main.py            FastAPI app factory + lifespan (wires up all long-lived clients)
├── config.py          Settings (pydantic-settings, loaded from .env)
├── api/               webhook (GET verify / POST inbound), health checks, DI providers
├── whatsapp/          signature verification, inbound parsing, outbound builders, Graph API client
├── db/                SQLAlchemy 2.0 async models + repositories mirroring the existing schema
├── vectorstore/       Qdrant client wrapper + payload schemas
├── search/            hybrid search (SQL filters ∥ Qdrant semantic search + Tavily fallback)
├── agent/             the LangGraph heart — state, slot schema, prompts, nodes, graph, tools
├── services/          session (de)serialization, LLM service, conversation orchestrator
└── jobs/              incremental product-embeddings sync + scheduler

tests/
├── unit/                   pure-logic tests (slots, filters, curation validation, message
│                           builders, inbound parsing, signature verification) — no LLM/DB/network
├── integration/            webhook signature round trip, full agent-graph happy path (fakes at
│                           the NodeDeps/search_for_gifts boundary), session<->JSONB round trip
└── scripted_conversations/ YAML-scripted, end-to-end conversation smoke tests + runner
```

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the keys below
```

Fill in `.env`:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL` | Chat + structured-output reasoning (via `langchain-openai`) |
| `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS` | Product embeddings for semantic search |
| `META_WHATSAPP_TOKEN`, `META_VERIFY_TOKEN`, `META_PHONE_NUMBER_ID`, `META_APP_SECRET` | Meta WhatsApp Cloud API (Graph API + signed webhooks) |
| `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` | Vector store for product embeddings |
| `TAVILY_API_KEY` | Web-search fallback for niche gift ideas (optional — disabled if blank) |
| `DATABASE_URL` | Postgres connection string (`postgresql+asyncpg://...`) — points at the existing, already-populated database in production |
| `SEARCH_*` | Search tuning knobs: budget band tolerance, fallback thresholds, top-k limits |

## Running locally

### With Docker Compose (recommended for a full local stack)

```bash
docker compose up -d postgres qdrant   # dev-convenience Postgres + Qdrant
docker compose up app                  # FastAPI app on :8000
```

`docker-compose.yml` also defines a profile-gated one-shot job:

```bash
docker compose run --rm embeddings-job   # syncs product embeddings into Qdrant
```

### Directly

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Check it's up:

```bash
curl localhost:8000/healthz
curl localhost:8000/readyz   # pings Postgres (hard dependency) + Qdrant (degrades gracefully)
```

`scripts/seed_check.py` is a quick sanity check of DB connectivity and row counts:

```bash
python scripts/seed_check.py
```

## Syncing product embeddings

`app/jobs/embed_products.py` incrementally embeds products that are new or have changed since
their last embedding (comparing `product_embeddings.created_at` to `products.updated_at`),
batches OpenAI embedding calls, and upserts into Qdrant using deterministic UUIDv5 point IDs
(so re-running it is always idempotent — no duplicates).

```bash
python -m app.jobs.embed_products --dry-run   # see what would be embedded, without writing
python -m app.jobs.embed_products             # run for real
```

Set `EMBEDDINGS_SCHEDULE_ENABLED=true` to also run this nightly via an in-process APScheduler job
(`app/jobs/scheduler.py`) — an alternative to wiring up an external cron.

## Connecting a real WhatsApp number (Meta test number + ngrok)

1. Expose your local server: `ngrok http 8000` and copy the `https://...ngrok-free.app` URL.
2. In the Meta App Dashboard (WhatsApp > Configuration), set the webhook callback URL to
   `https://<your-ngrok-domain>/webhook` and the verify token to whatever you set as
   `META_VERIFY_TOKEN` — Meta will hit the `GET /webhook` handshake endpoint to confirm it.
3. Subscribe to the `messages` webhook field.
4. Use Meta's free test number, add your own number as a verified recipient, and start chatting.
5. Tail the app logs (structured JSON, correlated by `whatsapp_number`/`session_id`/`turn_id`)
   and check `/readyz`; query `conversation_sessions`, `recommendation_logs`, and
   `product_embeddings` in Postgres, and `qdrant`'s `scroll`/`count` endpoints, to confirm
   persistence and embedding correctness end to end.

## Tests

```bash
pytest                                  # everything
pytest tests/unit -q                    # fast pure-logic tests, no network/DB
pytest tests/integration -q             # webhook + agent-graph + session round-trip (fakes only)
pytest tests/scripted_conversations -q  # YAML-scripted full-conversation smoke tests
```

All three layers run with **no real OpenAI/Meta/Postgres/Qdrant/Tavily calls** — the seam is
`NodeDeps` (`app/agent/deps.py`): every external dependency is injected per-turn, so tests swap
in fakes for the chat model, repositories, and search/WhatsApp clients while exercising the real
graph wiring, routing, and node logic.

To add a new end-to-end conversation smoke test, drop a YAML file into
`tests/scripted_conversations/fixtures/` describing the turns (what the user says/taps, any
scripted `extracted_slots` / `intent_classification` / `refinement_intent` the LLM should "return"
for that turn, and the expected stage/outbound shape) — see the existing fixtures for the format.
The runner picks it up automatically.

## Linting

```bash
ruff check .
```
