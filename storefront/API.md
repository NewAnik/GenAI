# Storefront API

REST API (API Gateway v1) backing `wrapped-and-more`'s cart/checkout/orders — see
`infra/cdk/storefront_stack/storefront_stack.py` for the CDK that builds it and
`infra/config/functions.yml` for the route table this doc mirrors. **Not yet wired up**: the
site's `src/lib/orders/api.ts` still returns seeded mock data as of this writing — check there
before assuming these endpoints are live in production.

## Base URL

No fixed URL is committed here — API Gateway assigns one per deploy
(`https://{api-id}.execute-api.{region}.amazonaws.com/prod`), and it changes if the stack is
ever destroyed and recreated. Get the live URL from the CDK deploy output, or from
`CfnOutput ApiRegionalDomainName` if a custom domain (`apiDomainName` CDK context) is
configured. All paths below are relative to that base.

## Auth

Every endpoint except the payment webhook and the catalog endpoint requires a Cognito **ID
token** (not access token — the Lambdas read the `email`/custom claims off it) in the
`Authorization` header:

```
Authorization: Bearer <cognito-id-token>
```

The frontend gets this token by calling Cognito directly (SignUp/InitiateAuth via
`amazon-cognito-identity-js` or Amplify Auth) — there is no `/login` or `/signup` endpoint on
this API. API Gateway's `CognitoUserPoolsAuthorizer` verifies the token before the request ever
reaches a Lambda; an invalid/expired/missing token gets a `401` straight from API Gateway
itself (not the JSON error envelope below).

`POST /orders/{order_id}/shipments/create` additionally requires the token's
`cognito:groups` claim to include `admin` — not relevant to the customer-facing storefront UI,
listed here only for completeness.

## Conventions

- **Every route is `POST`**, including reads — a deliberate choice (see
  `infra/config/functions.yml`'s header comment) to keep API Gateway/Cognito wiring uniform.
  There is no cacheability/idempotence implied by this; treat each call as a fresh request.
- **Request/response bodies are JSON**, decoded/encoded with `msgspec` — field names are
  `snake_case`, matching the Python schemas below exactly.
- **Money fields are JSON strings**, not numbers (e.g. `"118.00"`, not `118.00`) — `Decimal`
  round-trips through msgspec as a string to avoid float rounding. Parse with a decimal
  library, not `Number()`/`parseFloat`.
- **Timestamps** (`created_at`, `shipped_at`, `delivered_at`) are ISO 8601 strings or `null`.
- A field typed `| None` in the schemas below serializes as JSON `null` when absent — it is
  always present as a key, just possibly `null` (msgspec does not omit optional fields).

## Errors

Non-2xx responses (other than a 401 from the authorizer itself, which has no body) share one
envelope:

```json
{ "error": { "code": "not_found", "message": "order not found" } }
```

| Status | `code` | When |
| --- | --- | --- |
| 401 | *(no body — from API Gateway)* | missing/invalid/expired bearer token |
| 403 | `forbidden` | authenticated, but missing the required Cognito group (admin routes) |
| 404 | `not_found` | route doesn't exist, or the resource isn't yours/doesn't exist |
| 422 | `validation_error` | request body failed schema validation (wrong type, missing field, `quantity <= 0`, ...) |
| 400 | `empty_cart` | checkout with nothing in the cart |
| 400 | `invalid_address` | checkout with a `shipping_address_id` that isn't yours |
| 409 | `insufficient_stock` | checkout when reserved+requested exceeds on-hand stock (message includes `variant_id`/`requested`/`available`) |
| 409 | `not_cancellable` | cancelling an order past the cancellable status |
| 500 | `internal_error` | unhandled server error |

## Endpoints

### Auth

**`POST /auth/me`** — the logged-in user's local profile (there's no signup/login endpoint;
those go straight to Cognito).

Response `200`:
```ts
{ id: number, email: string | null, first_name: string | null, last_name: string | null,
  role: string | null, organization_id: number | null }
```

**`POST /auth/me/update`** — change the caller's display name. This only ever touches the
local `users` row, never Cognito — first/last name are display fields, not credentials, so
there's nothing to keep in sync on the identity provider side. Both fields are required (send
the full name, not a partial patch) and must be non-empty.

Body: `{ first_name: string, last_name: string }`

Response `200`: same shape as `/auth/me`, reflecting the update. Error: `validation_error`
(422) for an empty `first_name`/`last_name`.

> Note: signup itself doesn't currently collect a name — the Cognito post-confirmation
> trigger only reads `sub`/`email` off the new account, so every new user starts with
> `first_name`/`last_name` both `null` until they call this endpoint.

### Cart

All cart endpoints operate on the caller's one active cart — there's no cart ID in the URL.

**`POST /cart`** — get (or lazily create) the active cart.

**`POST /cart/items`** — add an item. Body:
```ts
{ variant_id: number, quantity: number }  // quantity must be > 0, and >= the product's min_order_quantity
```

**`POST /cart/items/{item_id}/update`** — set an item's quantity. Body: `{ quantity: number }`.

**`POST /cart/items/{item_id}/remove`** — remove one item. No body.

**`POST /cart/clear`** — empty the cart. No body.

All four cart-mutation endpoints return the same shape as `/cart` (`200`, or `201` for add):
```ts
{ id: number, status: string | null, subtotal: string,  // Decimal-as-string, see Conventions
  items: Array<{ id: number, variant_id: number | null, sku: string | null,
                 quantity: number | null, unit_price: string | null, line_total: string | null }> }
```

### Orders

**`POST /checkout`** — atomically create an order from the active cart and reserve stock.
Body: `{ shipping_address_id: number }`.

Response `201`:
```ts
{ order_id: number, order_number: string, total_amount: string }
```
Errors: `empty_cart` (400), `invalid_address` (400), `insufficient_stock` (409).

**`POST /orders`** — list the caller's orders. No body.

Response `200`: `Array<OrderSummary>` where
```ts
type OrderSummary = { id: number, order_number: string | null, status: string | null,
  payment_status: string | null, total_amount: string | null, created_at: string | null }
```

**`POST /orders/{order_id}`** — full order detail. No body.

Response `200`:
```ts
type OrderDetail = OrderSummary & {
  shipping_address_id: number | null,
  items: Array<{ id: number, product_id: number | null, variant_id: number | null,
                 quantity: number | null, unit_price: string | null }>,
  invoice: { id: number, invoice_number: string | null, invoice_url: string | null,
             gst_amount: string | null, total_amount: string | null } | null,
  shipments: Array<{ id: number, courier_name: string | null, tracking_number: string | null,
                      shipment_status: string | null, shipped_at: string | null,
                      delivered_at: string | null }>,
}
```

**`POST /orders/{order_id}/cancel`** — cancel (idempotent — cancelling twice is a no-op `200`,
not an error). No body. Response `200`: `OrderSummary`. Error: `not_cancellable` (409).

**`POST /orders/{order_id}/invoice`** — the order's invoice. No body. Response `200`:
```ts
{ id: number, invoice_number: string | null, invoice_url: string | null,
  gst_amount: string | null, total_amount: string | null }
```

**`POST /orders/{order_id}/shipments`** — list shipments for the order. No body. Response
`200`: `Array<Shipment>` (same shape as `OrderDetail.shipments` items).

**`POST /orders/{order_id}/shipments/create`** *(admin only)* — record a shipment against the
order, fulfilling the reservation. Body: `{ courier_name: string, tracking_number: string }`.
Response `201`: a single `Shipment`.

### Payments

**`POST /orders/{order_id}/payments`** — record a payment attempt against an order (the actual
charge happens with your payment provider client-side/server-side first — this just logs the
reference; the order flips to `paid` only once the provider's webhook confirms it
server-to-server, not from this call). Body:
```ts
{ payment_method: string, transaction_reference: string, amount: string }  // amount must be > 0
```

Response `201`:
```ts
{ id: number, order_id: number | null, payment_method: string | null,
  payment_status: string | null, transaction_reference: string | null, amount: string | null }
```

**`POST /webhooks/payments`** — **not called by the frontend.** Server-to-server only, HMAC-signed
(`X-Signature-256`) by the payment provider; one of only two routes with `auth: none` (the other
is the catalog endpoint below). Listed here only so its existence in the route table isn't a
surprise.

### Catalog

**`POST /catalog/gift-boxes`** — `auth: none`, the only other unauthenticated route. Backs the
public site's product grid (replaces `wrapped-and-more/src/content/products.ts`'s hardcoded
array). No body. Only returns boxes with both a `slug` and a `collection` set — a box missing
either is treated as not catalog-ready and left out.

Response `200`: `Array<GiftBoxSummary>` where
```ts
type GiftBoxSummary = {
  slug: string, name: string, collection: string, occasions: string[],
  selling_price: string,  // Decimal-as-string, see Conventions
  moq: number | null, description: string | null,
  contents: string,       // joined from gift_box_items, e.g. "1 x Cashew jar, 2 x Clay diya"
  image_url: string | null,  // already a full CDN URL, never a bare object key
  alt_text: string | null,
}
```
