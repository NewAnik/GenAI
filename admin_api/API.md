# Admin API

REST API (API Gateway v1) backing `wrapped-and-more-admin` — see
`infra/cdk/admin_api_stack/admin_api_stack.py` for the CDK that builds it and
`infra/config/admin_functions.yml` for the route table this doc mirrors. This is an internal
tool's API, not the public storefront's (`storefront/API.md`) — different Cognito User Pool,
different authorization model, not meant to be called from any public site.

## Base URL

No fixed URL is committed here — API Gateway assigns one per deploy
(`https://{api-id}.execute-api.{region}.amazonaws.com/prod`). Get the live URL from the CDK
deploy output, or `CfnOutput AdminApiRegionalDomainName` if a custom domain (`apiDomainName` CDK
context) is configured.

## Auth

Every endpoint requires a Cognito **ID token** from the **Admin User Pool**
(`admin_cognito_stack.py` — a separate pool from the storefront's customer pool; a storefront
token never authenticates here) in the `Authorization` header:

```
Authorization: Bearer <cognito-id-token>
```

There is no `/login` endpoint — staff accounts are provisioned by an administrator
(`wrapped-and-more-admin/scripts/provision-staff.mjs`; self-signup is disabled on this pool), and
the client calls Cognito's `InitiateAuthCommand` directly. API Gateway's
`CognitoUserPoolsAuthorizer` verifies the token before the request ever reaches a Lambda; an
invalid/expired/missing token gets a `401` straight from API Gateway itself (not the JSON error
envelope below).

Beyond "is this a verified Cognito identity," every route additionally requires the caller to
have a **local staff profile row** (`public.users`, keyed by `cognito_sub`) with a role in one of
the four Cognito groups the pool defines: `super_admin`, `admin`, `ops`, `sales`. A verified
identity with no such row is rejected — this API never auto-provisions one (unlike the storefront
API's `resolve_user`); see `services/auth_service.py`. Individual resources/operations may require
a narrower group still — see `config/resources.yml`'s `*_groups` lists for the generic endpoints
below, and each bespoke handler for its own.

## Conventions

- **Every route is `POST`**, including reads — see `infra/config/admin_functions.yml`'s header
  comment for why.
- **Request/response bodies are JSON.**
- **Errors** share one envelope (except a bodyless 401 from the authorizer itself):
  ```json
  { "error": { "code": "not_found", "message": "no such resource 'foo'" } }
  ```
  | Status | `code` | When |
  | --- | --- | --- |
  | 401 | *(no body — from API Gateway)*, or `unauthorized` | missing/invalid/expired bearer token, or a verified identity with no local staff row |
  | 403 | `forbidden` | authenticated staff, but missing the required Cognito group for this operation |
  | 404 | `not_found` | route doesn't exist, resource table isn't declared in `resources.yml`, or the record doesn't exist |
  | 422 | `validation_error`, `check_violation`, `not_null_violation` | request body failed validation |
  | 409 | `unique_violation`, `foreign_key_violation`, `not_convertible` | the write conflicts with current data |
  | 500 | `internal_error` | unhandled server error |

## Generic resource endpoints — `/resources/{table}/...`

One family of endpoints serves every table declared in `config/resources.yml` (see that file's
header comment for the allow-list design: a table absent from it is a `404` here, full stop).
`offer_products` and `offer_categories` (composite primary keys) are **not** declared there — use
the bespoke `/offers/{offer_id}/scope/...` endpoints below instead.

**`POST /resources/{table}/list`** — paginated, sorted, filtered, searched list.
```ts
{ page: number, pageSize: number, sort?: { column: string, ascending: boolean },
  search?: string, filters?: Record<string, string|number|boolean|(string|number)[]>,
  ranges?: Record<string, { from?: string, to?: string }> }
```
Response: `{ rows: object[], total: number }`. An array filter value (e.g.
`{ variant_id: [1,2,3] }`) matches any of the given values (`= ANY(...)`).

**`POST /resources/{table}/detail`** — `{ id }` → the row, or `404`.

**`POST /resources/{table}/related`** — backs a detail page's child tables.
`{ foreignKey, parentId, orderBy?, limit? }` → `{ rows: object[] }`. `foreignKey` must be in the
*child* table's own `filterable` list.

**`POST /resources/{table}/lookup`** — relation-picker options.
`{ labelColumn, secondaryColumn? }` → `object[]` (each with `id` + the requested columns), up to
1000 rows.

**`POST /resources/{table}/create`** — body is the new row's writable fields → the created row
(`201`).

**`POST /resources/{table}/{id}/update`** — body is the fields to change → the updated row.

**`POST /resources/{table}/{id}/delete`** — no body → `{ ok: true }`.

Every declared `relations` entry for a resource is always included in `list`/`detail`/`related`
responses as a nested object (e.g. `row.category = { id, name }`) — there is no per-request embed
selection.

## Bespoke endpoints

**`POST /auth/me`** — the caller's local staff profile.
Response: `{ id, email, first_name, last_name, role, organization_id, is_active }`.

**`POST /dashboard/summary`** — the dashboard's KPI aggregation (revenue, order count,
12-week revenue/order buckets, orders-by-status, active offer count, open quote count, low-stock
inventory, recent audit activity) computed server-side. See `dashboard_handler.py` for the exact
response shape.

**`POST /quotes/{quote_id}/convert`** — converts a quote into a confirmed order in one atomic
transaction (copies line items, stamps GST at 18%, marks the quote `converted`).
Response `201`: `{ id, order_number, total_amount }`. Error: `not_convertible` (409) if the quote
is already `converted`/`rejected`/`expired`.

**`POST /orders/{order_id}/status`** — the only way `orders.status` should change (replaces a raw
write through the generic `/resources/orders/{id}/update`). Body: `{ status: string, note?:
string }`. Validates the transition against a fixed graph (mirrors
`wrapped-and-more-admin/src/lib/enums.ts`'s `orderTransitions`), writes an `order_status_history`
row, records an audit entry, and enqueues a customer-facing status-change email.
Response `200`: `{ id, status }`. Error: `invalid_transition` (409) if `status` isn't a legal next
step from the order's current status.

**`POST /offers/{offer_id}/match-count`** — how many catalogue products/gift boxes this offer
currently matches. Response: `{ count: number }`.

**`POST /offers/{offer_id}/scope/list`** — `{ kind: 'products'|'categories' }` → the products or
categories currently attached to the offer. Response: `{ rows: object[] }`.

**`POST /offers/{offer_id}/scope/attach`** / **`.../scope/detach`** — `{ kind, targetId }` →
`{ ok: true }`. Composite-PK writes on `offer_products`/`offer_categories`.

**`POST /campaigns/{campaign_id}/recipients/import`** — bulk-inserts pre-parsed CSV rows (parsing
itself stays client-side). Body: `{ rows: Array<{ employee_name, employee_email?, address?, city?, state?, pincode? }> }`.
Response `201`: `{ imported: number }`.

**`POST /images/presign-upload`** — `{ prefix: 'products'|'gift-boxes', ownerId: number, contentType: string }`
→ `{ uploadUrl: string, objectKey: string }`. The client `PUT`s the (already resized/WebP-encoded)
image bytes straight to `uploadUrl`, then stores `objectKey` as the image row's `image_url`. The
object key is always generated server-side.

**`POST /images/delete`** — `{ objectKey: string }` → `{ ok: true }`. Rejects a key that doesn't
match the expected `{prefix}/{ownerId}/{uuid}.webp` pattern.
