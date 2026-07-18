#!/usr/bin/env bash
# Exercise the feature-flag flow end-to-end against a running instance.
#
# Usage:
#   scripts/smoke_test.sh [BASE_URL]
#   BASE_URL defaults to http://localhost:8000
#
# Verifies: health -> readiness -> create flag -> get -> evaluate (rule match)
# -> evaluate (default) -> delete. Exits non-zero on the first failure.
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
KEY="smoke-checkout"

pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }

# $1 = expected HTTP status, $2 = method, $3 = path, $4 = optional JSON body
req() {
  local expected="$1" method="$2" path="$3" body="${4:-}"
  local args=(-sS -o /tmp/smoke_body -w '%{http_code}' -X "$method" "${BASE_URL}${path}")
  [[ -n "$body" ]] && args+=(-H 'content-type: application/json' -d "$body")
  local code
  code="$(curl "${args[@]}")"
  if [[ "$code" != "$expected" ]]; then
    fail "$method $path -> $code (expected $expected): $(cat /tmp/smoke_body)"
  fi
}

echo "Smoke testing ${BASE_URL}"

req 200 GET /health;                                        pass "GET /health"
req 200 GET /ready;                                         pass "GET /ready (database reachable)"

# Clean up any leftover flag from a previous run (ignore result).
curl -sS -o /dev/null -X DELETE "${BASE_URL}/flags/${KEY}" || true

req 201 POST /flags '{
  "key": "'"${KEY}"'", "name": "Smoke Checkout",
  "enabled": true, "default_state": false,
  "rules": [
    { "priority": 0, "attribute": "subscriptionTier", "operator": "eq",
      "values": ["premium"], "outcome": true }
  ]
}';                                                         pass "POST /flags (create)"

req 200 GET "/flags/${KEY}";                                pass "GET /flags/${KEY}"

req 200 POST "/flags/${KEY}/evaluate" \
  '{ "context": { "userId": "u-1", "subscriptionTier": "premium" } }'
grep -q '"reason":"RULE_MATCH"' /tmp/smoke_body \
  || grep -q '"reason": "RULE_MATCH"' /tmp/smoke_body \
  || fail "expected RULE_MATCH, got: $(cat /tmp/smoke_body)"
pass "evaluate matches rule (RULE_MATCH)"

req 200 POST "/flags/${KEY}/evaluate" \
  '{ "context": { "userId": "u-2", "subscriptionTier": "free" } }'
grep -q 'DEFAULT' /tmp/smoke_body || fail "expected DEFAULT, got: $(cat /tmp/smoke_body)"
pass "evaluate falls through to default (DEFAULT)"

req 204 DELETE "/flags/${KEY}";                             pass "DELETE /flags/${KEY}"

echo "All smoke checks passed."
