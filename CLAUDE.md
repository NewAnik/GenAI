# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> The parent `wrapped-and-more-project/CLAUDE.md` (one level up) describes this repo at a
> workspace level and predates the split documented below — trust this file for anything inside
> `GenAI/`.

## What's actually in this repo

`GenAI/` is **four independent backends against the same Postgres database**, not one app:

| Path | What it is | Runtime | Data access |
| --- | --- | --- | --- |
| `app/` | WhatsApp conversational sales agent (LangGraph) + an older JWT-based storefront API | Long-running FastAPI (uvicorn/Docker) | SQLAlchemy 2.0 async |
| `storefront/` | Current storefront API (auth, cart, catalog, orders, payments) for the public site | AWS Lambda, one function per domain, behind API Gateway REST API (v1) | peewee (raw psycopg2 for a few paths) |
| `admin_api/` | Generic `/resources/{table}/...` CRUD API + bespoke endpoints (dashboard, offers, quotes, campaigns, images) for the internal admin | AWS Lambda, same pattern as `storefront/` | raw psycopg2 (generic resource routes) + peewee (bespoke handlers) |
| `infra/cdk/` | AWS CDK app deploying `storefront/` and `admin_api/` plus their Cognito pools and shared VPC | CDK (Python) | — |

**`app/api/{auth,cart,orders,payments}.py` (the JWT-based storefront API, still mounted in
`app/main.py`) is the *predecessor* of `storefront/`.** `storefront/` is the actively developed
one (Cognito-authenticated via API Gateway's authorizer, no JWT library in the package at all —
see `storefront/handlers/common/auth.py`) and is newer by git history. Don't assume a storefront
task belongs in `app/api/` — check which one the task actually targets, and prefer `storefront/`
unless there's a reason to touch the legacy path specifically. The public site
(`wrapped-and-more/src/lib/orders/api.ts`) is not wired to either yet (still seeded mock data).

All four share one schema: the same Postgres database backs the WhatsApp agent, the storefront
Lambdas, and the admin Lambdas — `admin_api/db/connection.py`'s docstring says this explicitly.
`wrapped-and-more-admin/schema.sql` / `supabase/migrations` is the schema's source of truth;
`app/db/models/`, `storefront/db/models/`, and `admin_api/db/models/` each independently mirror it
in their own ORM (SQLAlchemy async / peewee / peewee).

---

## `app/` — WhatsApp agent + legacy storefront API

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # fill in keys — see table in README.md

uvicorn app.main:app --reload --port 8000     # run directly
docker compose up -d postgres qdrant && docker compose up app   # or via Docker Compose
docker compose run --rm embeddings-job        # one-shot product-embeddings sync job

pytest tests/unit -q                    # pure-logic, no network/DB
pytest tests/integration -q             # webhook + agent-graph + session round-trip (fakes only)
pytest tests/scripted_conversations -q  # YAML-scripted full-conversation smoke tests
pytest tests/unit/test_some_file.py::test_name   # single test

ruff check .                            # lint (repo-wide — also covers storefront/, admin_api/, infra/)
python -m app.jobs.embed_products --dry-run   # preview product embedding sync
python -m app.jobs.embed_products             # sync product embeddings into Qdrant
python scripts/seed_check.py            # sanity-check DB connectivity/row counts
```

`pytest` with no path runs everything under `testpaths = ["tests"]` (set in `pyproject.toml`),
which includes `tests/storefront/` too — see below for that suite's DB-fixture gating.

Buyer chats naturally about occasion/headcount/budget/theme; the app searches an internal catalog
(SQL filters + Qdrant semantic search, Tavily web search as fallback), and an LLM-driven LangGraph
agent reasons over candidates to present a ranked, justified shortlist over WhatsApp.

```
WhatsApp user <-> Meta WhatsApp Cloud API <-> FastAPI webhook <-> LangGraph agent
                                                  |                    |
                                            Postgres (catalog,    OpenAI GPT (chat +
                                            sessions, audit log)  structured output)
                                                  |                    |
                                              Qdrant (semantic     Tavily (web search
                                              product search)      fallback)
```

One inbound WhatsApp message → one `graph.ainvoke()` over a compiled LangGraph `StateGraph` →
zero-or-more outbound WhatsApp sends → one write of `AgentState` back to
`conversation_sessions.session_state` (JSONB). No LangGraph checkpointer is attached (see
`app/agent/graph.py`) — that JSONB column is the durable cross-turn store; the compiled graph only
manages state *within* one turn.

```
app/
├── main.py       FastAPI app factory + lifespan (constructs/tears down all long-lived clients:
│                 WhatsApp, Qdrant, OpenAI, Tavily; wires the ConversationOrchestrator)
├── config.py     Settings (pydantic-settings, from .env) — single source for every tunable
├── api/          FastAPI routers: webhook (WhatsApp GET verify / POST inbound), health,
│                 auth, cart, orders, payments (the legacy JWT storefront API — see above)
├── whatsapp/     signature verification, inbound parsing, outbound builders, Graph API client
├── db/
│   ├── models/       SQLAlchemy 2.0 async models, one module per domain area
│   └── repositories/ one repo per aggregate — the only layer that issues queries
├── vectorstore/  Qdrant client wrapper + payload schemas
├── search/       hybrid search: SQL filters ∥ Qdrant semantic search, Tavily fallback when the
│                 catalog comes up short
├── agent/        the LangGraph heart
│   ├── state.py, slot_schema.py, schemas.py   AgentState + structured-output schemas
│   ├── prompts.py                             LLM prompts
│   ├── nodes/                                 one module per graph node; each node file also
│   │                                           defines its own `route_after_*` for testability
│   ├── graph.py                                wires nodes into the compiled StateGraph (read
│   │                                           this file first to see the full turn flow)
│   ├── deps.py                                NodeDeps — the DI seam every node/tool goes through
│   └── tools/                                  catalog search, campaign lookups, Tavily web search
├── services/     session (de)serialization, LLM service, conversation orchestrator, auth/order/
│                 inventory services (legacy API business logic)
└── jobs/         incremental product-embeddings sync (`embed_products.py`) + APScheduler
                  (`scheduler.py`, gated by `EMBEDDINGS_SCHEDULE_ENABLED`)
```

All three `app/` test layers run with **no real OpenAI/Meta/Postgres/Qdrant/Tavily calls**. The
seam is `NodeDeps` (`app/agent/deps.py`): every external dependency is injected per-turn, so tests
swap in fakes while exercising the real graph wiring, routing, and node logic. To add an
end-to-end conversation test, drop a YAML fixture into `tests/scripted_conversations/fixtures/` —
the runner picks it up automatically.

`app/jobs/embed_products.py` embeds only products new or changed since their last embedding
(`product_embeddings.created_at` vs `products.updated_at`) and upserts into Qdrant using
deterministic UUIDv5 point IDs — safe to re-run, never duplicates.

---

## `storefront/` — storefront Lambda API (current)

```bash
cd storefront   # every import here is bare (`from config import ...`) — must run from storefront/, not repo root

DB_HOST=localhost DB_PORT=5432 DB_NAME=corporate_gifting DB_USER=postgres DB_PASSWORD=postgres \
    python -m local.run_local --route "POST /cart/items" \
    --body '{"gift_box_slug": "first-light", "quantity": 2}' --sub some-cognito-sub
```

`local/run_local.py` builds a synthetic API Gateway proxy-integration event via
`local/fake_event.py` and calls a handler's `lambda_handler` in-process — no SAM, no container
emulation. `tests/storefront/` uses the same `build_event()` helper, so local dev and tests
exercise the identical code path.

```bash
# from the repo root — same pytest run as app/
pytest tests/storefront/unit -q          # no DB needed
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/storefront_test \
    pytest tests/storefront/integration -q   # gated on TEST_DATABASE_URL (tests/storefront/integration/conftest.py)
```

There's no FastAPI here — `handlers/common/router.py`'s `dispatch()` replaces FastAPI's routing
and exception handling, matching on `f"{httpMethod} {resource}"` (API Gateway REST API's
`event["resource"]` is the exact route template CDK registered, e.g.
`/cart/items/{item_id}/update` — not the resolved path, so no manual path-parsing is needed).
`handlers/common/http.py` (msgspec-backed `decode_body`/`json_response`) replaces FastAPI's
request validation and `response_model=` serialization.

**Auth**: API Gateway's native `CognitoUserPoolsAuthorizer` verifies the bearer token *before* the
Lambda runs; claims land flat under `event["requestContext"]["authorizer"]["claims"]`
(`handlers/common/auth.py`). No JWT library, no `JWT_SECRET` — Cognito is the identity source of
truth. `require_role()` enforces `cognito:groups` membership inside the handler; API Gateway itself
only checks that the token is valid, not which groups it's in.

**DB**: one module-scope `PooledPostgresqlDatabase` (peewee) per Lambda execution environment,
`max_connections=1` — each concurrent Lambda execution environment is its own process, so this
isn't a traditional server connection pool (`storefront/db/database.py`). At meaningful
concurrency this can approach RDS's connection limit before Lambda's own concurrency limits do;
mitigated today via conservative reserved concurrency per function in
`infra/config/functions.yml`, with RDS Proxy as a known future follow-up.

**Config** (`storefront/config.py`): `DB_USER`/`DB_PASSWORD` come from Secrets Manager at cold
start when `DB_SECRET_ARN` is set (what CDK wires in production — RDS's own managed
master-user-password secret, username/password only); `DB_HOST`/`DB_PORT`/`DB_NAME` are always
plain env vars. Local dev/tests set all five directly — no AWS credentials needed to run tests.

```
storefront/
├── config.py, db/{database.py, models/, repositories/}   peewee models + one repo per aggregate
├── handlers/       one module per Lambda: auth, cart, catalog, orders, payments — each defines
│   │               its own `ROUTES = {"METHOD /path": fn}` dict and a `lambda_handler`
│   └── common/      router (dispatch), http (msgspec req/resp), auth (Cognito claims),
│                    cognito_trigger, signature (payment webhook HMAC), errors
├── services/       auth_service, inventory_service, order_service — business logic
├── schemas/        msgspec Structs for request/response bodies
└── local/          fake_event.py, run_local.py, interactive_cli.py — local dev without AWS
```

The payment webhook (`handlers/payments_handler.py`) is the one `auth: none` route — it verifies
its own HMAC signature (`handlers/common/signature.py`) against `PAYMENT_WEBHOOK_SECRET` instead
of going through Cognito.

Which Lambdas exist, their routes, memory/timeout/concurrency, and VPC placement are declared in
`infra/config/functions.yml`, not in code — `infra/cdk/storefront_stack/storefront_stack.py` loops
over it to build the Lambdas + API Gateway routes (`infra/cdk/functions_config.py` is the typed
parser). Adding an endpoint means adding an entry there, not new CDK code. Every route is `POST`
by design (uniform Cognito-authorizer wiring, every request body-driven) — where an original
design wanted two verbs on one path (e.g. list vs. create), one got an explicit action suffix
instead, to avoid colliding on the same `POST <path>` routeKey.

---

## `admin_api/` — admin Lambda API

Same Lambda/dispatch/msgspec pattern as `storefront/` (see above) — the differences worth knowing:

- **Generic resource CRUD**: `handlers/resource_handler.py` backs `POST /resources/{table}/...`
  (list/detail/related/lookup/create/update/delete) for every admin-editable table, mirroring
  `wrapped-and-more-admin`'s `ResourceConfig` pattern (one descriptor per table, generic screens
  render from it) — but server-side, as the authorization/SQL-generation layer that frontend's
  direct-to-PostgREST access doesn't have. `services/resource_service.py` owns authorization
  (`resolve_staff_user` + `require_group` against the table's `ResourceSpec`), SQL orchestration,
  and Postgres-constraint-error translation; `services/resource_registry.py` is the allow-list of
  tables/columns/relations/group requirements. `resource_handler.py` itself is a thin HTTP adapter.
- **Why raw psycopg2 here instead of peewee**: `db/query_builder.py`'s docstring — a truly generic
  table/column/join builder in peewee means synthesizing `Model` subclasses per request or
  dropping to its low-level `Table` helper, neither safer nor simpler than composing SQL directly.
  Peewee stays the right tool for the bespoke handlers (`dashboard`, `quotes`, `offers`,
  `campaigns`), where the table set touched is small and fixed.
- **Injection discipline in `query_builder.py` (read before touching it)**: every identifier
  (table/column/alias) is resolved only via a `ResourceSpec`/`ColumnSpec`/`RelationSpec` already
  validated against `resource_registry.py`'s allow-list, never a raw request string, and always
  wrapped in `sql.Identifier(...)`. A client-sent filter/sort/search *key* is only ever used to
  look up the allow-listed identifier (`resource_service.py` does that lookup, raising
  `ValidationError` first) — it's never spliced into SQL text. Every *value* is bound via `%s` in
  the params list, never string-interpolated, including inside `ILIKE` patterns — structurally
  ruling out the class of bug that needed manual sanitizing in
  `wrapped-and-more-admin/src/lib/queries.ts`'s old PostgREST `.or()` filter string building.
- **Bespoke, non-generic screens** (dashboard aggregates, offer live-match-count, quote→order
  conversion support, campaign CSV import, catalog images) each get their own handler module and
  use peewee directly, same as `storefront/`.

Route/function config lives in `infra/config/admin_functions.yml`, parsed by
`infra/cdk/admin_functions_config.py`, deployed by
`infra/cdk/admin_api_stack/admin_api_stack.py` — parallel to the storefront's, minus
storefront-only fields (GST rate, warehouse default, payment webhook secret). Route-level
`groups:` in the YAML is documentation only, same caveat as `storefront/`: real authorization is
table/operation-scoped (`resource_registry.py`'s `*_groups`) or enforced inside each bespoke
handler's `require_role`, never by API Gateway itself.

No dedicated `tests/admin_api/` suite exists yet — if adding one, follow `tests/storefront/`'s
shape (`unit/` collection-safe with env placeholders, `integration/` gated behind a
`TEST_DATABASE_URL`-style env var).

---

## `infra/cdk/` — AWS CDK app

```bash
cd infra/cdk
pip install -r requirements.txt    # separate from the app/ venv — aws-cdk-lib, constructs, PyYAML
cdk synth                          # render CloudFormation without deploying
cdk deploy --all                   # deploy every stack — confirm with the user before running
pytest                             # infra/cdk/tests — stack-shape assertions (fine-grained CDK assertions)
```

`app.py` wires five stacks in dependency order: `NetworkStack` (shared VPC + DB security group) →
`CognitoStack` (storefront user pool) → `StorefrontStack` (depends on the VPC + storefront pool) →
`AdminCognitoStack` (separate admin user pool) → `AdminApiStack` (depends on the VPC + admin pool).
Storefront and admin have **separate Cognito user pools** — a storefront customer and an admin
staff member are not interchangeable identities even though both APIs sit on the same database and
VPC.

There's no NAT gateway on the shared VPC, so a Lambda placed in it (`vpc: true`, the default in
both `functions.yml`/`admin_functions.yml`) has no outbound internet access, only what's reachable
in-VPC or via VPC endpoints. Set `vpc: false` only for a function that doesn't need Postgres but
does need the public internet (a payment gateway callout, WhatsApp Cloud API, etc.) — every
function in both YAML configs currently needs Postgres via `DB_SECRET_ARN`, so today that's none
of them.
