# DocMind API guide

Everything a client needs to authenticate, call and recover from errors in the DocMind
HTTP API. The base URL for all requests is `https://api.docmind.example/v1`.

## Authentication

Requests are authenticated with a bearer token:

```
Authorization: Bearer dm_live_xxxxxxxxxxxxxxxx
```

Access tokens expire 60 minutes after they are issued. Refresh them with
`POST /auth/refresh` using the long-lived refresh token; do not cache access tokens
beyond their expiry. A request made with an expired token returns HTTP 401 with the
error code `token_expired`.

Service accounts use a separate credential type (`dm_svc_...`) that does not expire but is
scoped to a single workspace and a fixed set of permissions.

### API keys

Workspace API keys do not expire by default, which is why they must be treated as secrets.
Keys are shown once at creation time and are stored only as a hash. If a key leaks, follow the
rotation procedure in the operations runbook — rotation is immediate and the old key is
rejected within 5 seconds.

## Idempotency

All `POST` endpoints that create resources (documents, uploads, members, exports) accept an
`Idempotency-Key` header. Send a UUIDv4 per logical operation; retrying with the same key
replays the original response instead of creating a duplicate.

`GET`, `PATCH` and `DELETE` requests are already idempotent and ignore the header.
Idempotency records are retained for 24 hours. Keys reused with a *different* request body
return HTTP 409 `idempotency_conflict`.

## Rate limits

Limits are enforced per token with a sliding window:

| Plan | Requests / minute | Burst |
| --- | --- | --- |
| Free | 60 | 20 |
| Team | 600 | 100 |
| Enterprise | 6,000 | 500 |

Every response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining` and
`X-RateLimit-Reset` headers. Exceeding the limit returns HTTP 429 with a `Retry-After`
header in seconds.

### Handling 429 responses

When you receive a 429 you should retry with exponential backoff and jitter — for example
wait 0.5s, 1s, 2s, 4s plus a random 0–250ms, up to a maximum of 5 attempts. Never retry in a
tight loop: that turns a temporary throttle into a sustained outage. Honour the `Retry-After`
value when it is present, and queue non-urgent work instead of retrying it immediately.

## Pagination

List endpoints use cursor pagination:

```
GET /documents?limit=50&cursor=eyJpZCI6MTIzfQ
```

The response contains `data`, `next_cursor` (null on the last page) and `has_more`.
Cursor pagination is stable across inserts, unlike offset pagination.

## Errors

Errors use a consistent envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "field 'title' is required",
    "request_id": "req_01H..."
  }
}
```

| Status | Meaning | Retryable |
| --- | --- | --- |
| 400 | malformed request | no |
| 401 | missing/expired credentials | re-authenticate |
| 403 | insufficient scope | no |
| 404 | unknown resource | no |
| 409 | conflict (duplicate or idempotency clash) | no |
| 422 | validation error | no |
| 429 | rate limited | yes, with backoff |
| 500 / 503 | server error | yes, with backoff |

Always log `request_id`; support can trace any request with it.

## Search and retrieval endpoints

`POST /search` runs hybrid retrieval: dense embeddings plus BM25 keyword scoring, fused and
diversified with maximal marginal relevance. Request body:

```json
{ "query": "how do I rotate a key", "top_k": 5, "filters": { "source": "runbook.md" } }
```

`POST /answer` performs retrieval and then generation, returning `answer`, `citations[]` and
per-stage `timings`. Pass `"stream": true` to receive Server-Sent Events: one `retrieved`
event with the citation list, then `token` events, then `done`.

## Webhooks

Register endpoints with `POST /webhooks`. Deliveries are signed with HMAC-SHA256 in the
`X-DocMind-Signature` header over the raw body plus the timestamp; reject timestamps older
than 5 minutes to prevent replay. Failed deliveries are retried 8 times over 24 hours with
exponential backoff, then parked in a dead-letter queue visible in the dashboard.
