# Feature Flag Service — curl Cookbook

End-to-end `curl` recipes for every API scenario: health/DB checks, flag CRUD,
evaluation (all rule outcomes), context-payload validation, cache inspection,
and cache-invalidation verification.

All commands assume `jq` is installed for pretty-printing (drop `| jq` if not).

## Setup

Point `BASE` at your target instance:

```bash
# Production
BASE=https://feature-flag-app-mft8n.ondigitalocean.app
# or local
# BASE=http://localhost:8000
```

The admin endpoints (`/admin/*`) require a shared secret sent as the
`x-admin-token` header, matched against the server's `ADMIN_TOKEN`. Export it if
you have it configured:

```bash
ADMIN_TOKEN=your-secret-here
```

### Error envelope

Every error responds with a consistent shape:

```json
{ "error": { "code": "not_found", "message": "flag 'x' not found", "details": null } }
```

Common codes: `not_found` (404), `conflict` (409), `validation_error` (422),
`http_error` (generic HTTP errors, e.g. 401/503), `internal_error` (500).

---

## 1. Health & database checks

```bash
# Liveness — process is up (does NOT touch the DB)
curl -s $BASE/health | jq                      # {"status":"ok"}

# Readiness — verifies the database is reachable (runs SELECT 1)
curl -s $BASE/ready | jq                        # {"status":"ready"}  -> 200
                                                # {"status":"unavailable"} -> 503 if DB down

# Show HTTP status explicitly
curl -s -o /dev/null -w '%{http_code}\n' $BASE/ready
```

```bash
# Landing route (root) — service metadata, avoids a 404 at /
curl -s $BASE/ | jq

# Prometheus metrics (evaluation counters, cache events, latencies)
curl -s $BASE/metrics | grep -E '^feature_flag_'
```

---

## 2. Database inspection (via the API)

The database is the source of truth; these read straight from Postgres.

```bash
# List all flags (+ their rules)
curl -s $BASE/flags | jq

# Pagination (defaults: limit=100, offset=0; limit range 1..500)
curl -s "$BASE/flags?limit=50&offset=0" | jq

# A single flag by key
curl -s $BASE/flags/new-checkout | jq

# Just the keys currently stored
curl -s $BASE/flags | jq -r '.[].key'

# Count of flags in the DB
curl -s $BASE/flags | jq 'length'
```

### Direct psql (raw tables)

Use the `DATABASE_URL` connection string (from `.env` / the deploy secret):

```bash
psql "$DATABASE_URL" -c \
  "SELECT id, key, name, enabled, default_state, updated_at FROM feature_flags ORDER BY updated_at DESC;"

psql "postgresql://USER:PASS@HOST:25060/defaultdb?sslmode=require" -c \
  "SELECT flag_id, priority, attribute, operator, values, outcome, rollout_percentage FROM flag_rules ORDER BY flag_id, priority;"
```

---

## 3. Create flags

`POST /flags` → `201 Created` (or `409` if the key exists, `422` on validation).

```bash
# Minimal: no rules -> always evaluates to default_state
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key": "dark-mode",
  "name": "Dark Mode",
  "enabled": true,
  "default_state": false
}' | jq

# With a targeting rule: premium users ON
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key": "new-checkout",
  "name": "New Checkout",
  "description": "Rolls out the redesigned checkout",
  "enabled": true,
  "default_state": false,
  "rules": [
    { "priority": 0, "attribute": "subscriptionTier", "operator": "eq",
      "values": ["premium"], "outcome": true }
  ]
}' | jq

# Multiple rules (unique priorities; lower priority wins first)
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key": "promo-banner",
  "name": "Promo Banner",
  "enabled": true,
  "default_state": false,
  "rules": [
    { "priority": 0, "attribute": "country", "operator": "in",
      "values": ["US","CA"], "outcome": true },
    { "priority": 1, "attribute": "plan", "operator": "neq",
      "values": ["free"], "outcome": true }
  ]
}' | jq

# Percentage rollout: 50% of EU/UK users (bucketed by userId)
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key": "beta-feature",
  "name": "Beta Feature",
  "enabled": true,
  "default_state": false,
  "rules": [
    { "priority": 0, "attribute": "region", "operator": "in",
      "values": ["EU","UK"], "outcome": true, "rollout_percentage": 50 }
  ]
}' | jq
```

Field reference:

| Field | Required | Constraints |
|---|---|---|
| `key` | yes | slug `^[a-z0-9]+([-_][a-z0-9]+)*$`, ≤128 chars |
| `name` | yes | 1–256 chars |
| `description` | no | ≤1024 chars |
| `enabled` | no | default `true` (kill-switch: `false` ⇒ always OFF) |
| `default_state` | no | default `false` (result when no rule matches) |
| `rules[].priority` | no | ≥0, unique per flag, lower evaluates first |
| `rules[].attribute` | yes | 1–128 chars |
| `rules[].operator` | yes | `eq`, `neq`, `in`, `not_in`, `contains` |
| `rules[].values` | yes | non-empty; `eq`/`neq` require exactly one |
| `rules[].outcome` | no | default `true` |
| `rules[].rollout_percentage` | no | 0–100 |

---

## 4. Update & delete

```bash
# Update scalar fields (partial update; omitted fields unchanged)
curl -s -X PUT $BASE/flags/new-checkout -H 'content-type: application/json' -d '{
  "enabled": false
}' | jq

# Replace the ENTIRE rule set (passing "rules" overwrites all existing rules)
curl -s -X PUT $BASE/flags/new-checkout -H 'content-type: application/json' -d '{
  "rules": [
    { "priority": 0, "attribute": "subscriptionTier", "operator": "in",
      "values": ["premium","enterprise"], "outcome": true }
  ]
}' | jq

# Delete a flag
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE $BASE/flags/new-checkout   # 204
```

---

## 5. Evaluate flags — every outcome (reason)

Single evaluation: `POST /flags/{key}/evaluate`. The `reason` explains the result.

Setup a flag to demonstrate all reasons:

```bash
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key": "demo",
  "name": "Demo",
  "enabled": true,
  "default_state": false,
  "rules": [
    { "priority": 0, "attribute": "subscriptionTier", "operator": "eq",
      "values": ["premium"], "outcome": true }
  ]
}' | jq
```

```bash
# RULE_MATCH — a rule matched (enabled = rule.outcome)
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"subscriptionTier":"premium"}}' | jq
# -> { "flag_key":"demo","enabled":true,"reason":"RULE_MATCH","matched_rule_priority":0 }

# DEFAULT — no rule matched, falls back to default_state
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"subscriptionTier":"free"}}' | jq
# -> { "flag_key":"demo","enabled":false,"reason":"DEFAULT","matched_rule_priority":null }

# FLAG_DISABLED — kill-switch off; always OFF regardless of rules
curl -s -X PUT $BASE/flags/demo -H 'content-type: application/json' -d '{"enabled":false}' >/dev/null
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"subscriptionTier":"premium"}}' | jq
# -> { ... "reason":"FLAG_DISABLED" }
curl -s -X PUT $BASE/flags/demo -H 'content-type: application/json' -d '{"enabled":true}' >/dev/null
```

### ROLLOUT_IN / ROLLOUT_OUT (deterministic percentage)

Bucketing uses `userId` / `user_id` / `id` from the context. Same identifier ⇒
same bucket every time. Without an identifier, a rollout rule always excludes.

```bash
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key": "rollout-demo", "name": "Rollout Demo", "enabled": true, "default_state": false,
  "rules": [
    { "priority": 0, "attribute": "region", "operator": "eq",
      "values": ["EU"], "outcome": true, "rollout_percentage": 50 }
  ]
}' | jq

# Try several userIds; each is deterministically IN or OUT of the 50% bucket
for u in u-1 u-2 u-3 u-4 u-5; do
  echo -n "$u -> "
  curl -s -X POST $BASE/flags/rollout-demo/evaluate -H 'content-type: application/json' \
    -d "{\"context\":{\"region\":\"EU\",\"userId\":\"$u\"}}" | jq -c '.reason,.enabled'
done
# reason is ROLLOUT_IN (enabled=outcome) or ROLLOUT_OUT (enabled=!outcome)

# No identifier -> cannot bucket -> ROLLOUT_OUT
curl -s -X POST $BASE/flags/rollout-demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"region":"EU"}}' | jq
```

### Operator reference

```bash
# eq / neq  (exactly one value)
-d '{"context":{"tier":"premium"}}'      # operator "eq",   values ["premium"]
# in / not_in  (membership in the list)
-d '{"context":{"country":"US"}}'        # operator "in",   values ["US","CA"]
# contains  (actual contains any listed value; substring or list membership)
-d '{"context":{"roles":["admin","qa"]}}' # operator "contains", values ["admin"]
-d '{"context":{"email":"a@corp.com"}}'   # operator "contains", values ["@corp.com"]
```

### Batch evaluation

Evaluates many flags against one context. Unknown keys resolve to a safe
OFF/`DEFAULT` instead of failing the whole request.

```bash
curl -s -X POST $BASE/evaluate/batch -H 'content-type: application/json' -d '{
  "flag_keys": ["demo","rollout-demo","does-not-exist"],
  "context": { "subscriptionTier": "premium", "region": "EU", "userId": "u-1" }
}' | jq
```

---

## 6. Validation checks

### Flag / rule validation (expect `422`, or `409` for duplicates)

```bash
# Invalid key (not a slug) -> 422
curl -s -X POST $BASE/flags -H 'content-type: application/json' \
  -d '{"key":"Invalid Key","name":"X"}' | jq

# Missing required name -> 422
curl -s -X POST $BASE/flags -H 'content-type: application/json' \
  -d '{"key":"nameless"}' | jq

# Rule operator without values -> 422
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key":"bad-rule","name":"Bad",
  "rules":[{"priority":0,"attribute":"tier","operator":"eq","values":[]}]
}' | jq

# eq with more than one value -> 422
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key":"bad-eq","name":"Bad",
  "rules":[{"priority":0,"attribute":"tier","operator":"eq","values":["a","b"]}]
}' | jq

# Duplicate rule priorities within a flag -> 422
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key":"dup-prio","name":"Dup",
  "rules":[
    {"priority":0,"attribute":"a","operator":"eq","values":["x"]},
    {"priority":0,"attribute":"b","operator":"eq","values":["y"]}
  ]
}' | jq

# rollout_percentage out of range (0..100) -> 422
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key":"bad-rollout","name":"Bad",
  "rules":[{"priority":0,"attribute":"a","operator":"eq","values":["x"],"rollout_percentage":150}]
}' | jq

# Duplicate key (create twice) -> 409 conflict
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{"key":"dup","name":"Dup"}' >/dev/null
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{"key":"dup","name":"Dup"}' | jq

# Unknown flag -> 404 not_found
curl -s $BASE/flags/does-not-exist | jq
```

### Evaluation context-payload validation (expect `422`)

The evaluation context is attacker-influenced input on the hot path, so it is
validated strictly. Limits: ≤64 attributes, key ≤128 chars, string value ≤1024
chars, list ≤100 items, values must be scalars (or lists of scalars).

```bash
# Nested object as a value (only scalars / lists of scalars allowed) -> 422
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"user":{"id":1}}}' | jq

# List containing a non-scalar -> 422
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"tags":[{"x":1}]}}' | jq

# Too many attributes (> 64) -> 422
python3 - <<'PY' | curl -s -X POST $BASE/flags/demo/evaluate \
  -H 'content-type: application/json' -d @- | jq
import json
print(json.dumps({"context": {f"k{i}": i for i in range(65)}}))
PY

# Context key too long (> 128 chars) -> 422
python3 - <<'PY' | curl -s -X POST $BASE/flags/demo/evaluate \
  -H 'content-type: application/json' -d @- | jq
import json
print(json.dumps({"context": {"k"*129: "v"}}))
PY

# String value too long (> 1024 chars) -> 422
python3 - <<'PY' | curl -s -X POST $BASE/flags/demo/evaluate \
  -H 'content-type: application/json' -d @- | jq
import json
print(json.dumps({"context": {"note": "x"*1025}}))
PY

# List too long (> 100 items) -> 422
python3 - <<'PY' | curl -s -X POST $BASE/flags/demo/evaluate \
  -H 'content-type: application/json' -d @- | jq
import json
print(json.dumps({"context": {"ids": list(range(101))}}))
PY

# A well-formed context (scalars + list of scalars) -> 200
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"userId":"u-1","subscriptionTier":"premium","tags":["a","b"],"age":30,"beta":true}}' | jq
```

---

## 7. Cache inspection

The cache is a **process-local, in-memory TTL cache** (default TTL 30s). It is
per-instance and ephemeral (cleared on restart/redeploy). Two ways to observe it:

### a) Admin endpoint (requires `ADMIN_TOKEN` configured on the server)

```bash
# Full cache contents: ttl, size, and per-entry key/enabled/rules/remaining-ttl/expired
curl -s $BASE/admin/cache -H "x-admin-token: $ADMIN_TOKEN" | jq

# Auth behavior:
curl -s -o /dev/null -w '%{http_code}\n' $BASE/admin/cache                          # 401 (no token)
curl -s -o /dev/null -w '%{http_code}\n' $BASE/admin/cache -H 'x-admin-token: nope' # 401 (wrong)
# If the server has no ADMIN_TOKEN configured, the endpoint is disabled -> 503
```

### b) Prometheus counters (always available)

```bash
curl -s $BASE/metrics | grep '^feature_flag_cache_events_total'
# events: hit / miss / expired / invalidate / stale
```

---

## 8. Cache invalidation checks

The read-through cache is populated on the first evaluation and invalidated on
any create/update/delete of that flag. These recipes prove the behavior.

### Populate, then confirm a cache hit

```bash
# Ensure a clean flag
curl -s -X DELETE $BASE/flags/cache-demo >/dev/null
curl -s -X POST $BASE/flags -H 'content-type: application/json' -d '{
  "key":"cache-demo","name":"Cache Demo","enabled":true,"default_state":false,
  "rules":[{"priority":0,"attribute":"tier","operator":"eq","values":["premium"],"outcome":true}]
}' >/dev/null

# First eval = cache miss (loads from DB and caches)
curl -s -X POST $BASE/flags/cache-demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"tier":"premium"}}' >/dev/null
# Second eval = cache hit
curl -s -X POST $BASE/flags/cache-demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"tier":"premium"}}' >/dev/null

# Watch miss/hit counters go up:
curl -s $BASE/metrics | grep '^feature_flag_cache_events_total'
# If admin is enabled, see the cached entry directly:
curl -s $BASE/admin/cache -H "x-admin-token: $ADMIN_TOKEN" | jq '.entries[] | select(.key=="cache-demo")'
```

### Invalidation on UPDATE (the key check)

```bash
# Cached result currently ON
curl -s -X POST $BASE/flags/cache-demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"tier":"premium"}}' | jq '.enabled'   # true

# Disable the flag; the write MUST invalidate the cached snapshot immediately
curl -s -X PUT $BASE/flags/cache-demo -H 'content-type: application/json' -d '{"enabled":false}' >/dev/null

# Next eval reflects the change right away (not after TTL) -> FLAG_DISABLED
curl -s -X POST $BASE/flags/cache-demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"tier":"premium"}}' | jq '{enabled, reason}'
# -> { "enabled": false, "reason": "FLAG_DISABLED" }

# invalidate counter incremented:
curl -s $BASE/metrics | grep 'feature_flag_cache_events_total{event="invalidate"}'
```

### Invalidation on DELETE

```bash
curl -s -X DELETE $BASE/flags/cache-demo >/dev/null
# Entry removed from cache; evaluating now -> 404 not_found (single eval)
curl -s -o /dev/null -w '%{http_code}\n' -X POST $BASE/flags/cache-demo/evaluate \
  -H 'content-type: application/json' -d '{"context":{"tier":"premium"}}'   # 404
# Confirm it's gone from the admin cache view (if enabled):
curl -s $BASE/admin/cache -H "x-admin-token: $ADMIN_TOKEN" | jq '[.entries[].key] | index("cache-demo")'  # null
```

### TTL expiry (bypassing explicit invalidation)

Change a flag directly in the DB (via `psql`) so the API does NOT invalidate the
cache, then observe the API keep serving the stale cached value until the TTL
(default 30s) elapses — proof the read path is cache-backed.

```bash
# 1) evaluate to prime the cache (via API)
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"subscriptionTier":"premium"}}' | jq '.enabled'

# 2) flip enabled directly in Postgres (no API call -> no invalidation)
psql "$DATABASE_URL" -c "UPDATE feature_flags SET enabled = NOT enabled WHERE key='demo';"

# 3) within the TTL window the API still returns the OLD value (served from cache)
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"subscriptionTier":"premium"}}' | jq '.enabled'

# 4) wait for the TTL to lapse, then it reloads from the DB and reflects the change
sleep 31
curl -s -X POST $BASE/flags/demo/evaluate -H 'content-type: application/json' \
  -d '{"context":{"subscriptionTier":"premium"}}' | jq '.enabled'
```

> Note: the cache is per-instance. With more than one running instance, cache
> hits/entries and TTL-expiry timing are observed per instance, so repeated
> requests may land on different caches.

---

## 9. Quick reference

| Scenario | Command |
|---|---|
| Liveness | `curl $BASE/health` |
| DB reachable | `curl $BASE/ready` |
| List flags (DB) | `curl $BASE/flags` |
| Get flag | `curl $BASE/flags/{key}` |
| Create flag | `POST $BASE/flags` |
| Update flag | `PUT $BASE/flags/{key}` |
| Delete flag | `DELETE $BASE/flags/{key}` |
| Evaluate | `POST $BASE/flags/{key}/evaluate` |
| Batch evaluate | `POST $BASE/evaluate/batch` |
| Cache contents | `curl $BASE/admin/cache -H "x-admin-token: $ADMIN_TOKEN"` |
| Cache counters | `curl $BASE/metrics \| grep cache_events` |
| Metrics | `curl $BASE/metrics` |
