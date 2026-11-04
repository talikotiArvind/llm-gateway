# Part 03 — Persistence, Redis and Config

Names follow `00_contract.md`. New names added here: `TenantScopedRepository`, `DbTransaction`, `TenantId`, `*Record` dataclasses, `RateLimiter`, `ConcurrencyLimiter`, `CacheKeyBuilder`, `CacheEligibility`.
Postgres = money and tenant truth (FR-74, NFR-15). Redis = coordination only (limits, breaker, cache). Money is `NUMERIC(18,8)` in SQL and `Decimal` in Python. Timestamps are `TIMESTAMPTZ` (UTC).

## 1. Postgres schema

### Global rules
| Rule | How |
|---|---|
| Tenant composite keys | Every child table has `UNIQUE (tenant_id, id)`. Every FK to a tenant-owned row is composite `(tenant_id, x_id) → parent (tenant_id, id)`, so a row can never point to another tenant's row (FR-67) |
| IDs | `UUID DEFAULT gen_random_uuid()` (PG ≥ 13), except append-only tables use `BIGINT GENERATED ALWAYS AS IDENTITY` |
| Enums | `TEXT` + `CHECK (col IN (...))` (simpler Alembic diffs than PG `ENUM`) |
| Roles | `switchyard_owner` owns schema and runs migrations. `switchyard_app` is the runtime role: `SELECT, INSERT, UPDATE, DELETE` on mutable tables; only `SELECT, INSERT` on `ledger` and `audit_events` |
| Append-only | `REVOKE UPDATE, DELETE, TRUNCATE ON ledger, audit_events FROM switchyard_app` **and** trigger `sy_forbid_mutation()` (`BEFORE UPDATE OR DELETE ... FOR EACH ROW` and `BEFORE TRUNCATE ... FOR EACH STATEMENT` → `RAISE EXCEPTION 'append-only table %', TG_TABLE_NAME`). Two layers: the grant stops the app, the trigger stops the owner role by mistake |

### tenants
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| slug | TEXT NOT NULL UNIQUE | `^[a-z0-9-]{3,63}$` CHECK |
| name | TEXT NOT NULL | |
| status | TEXT NOT NULL DEFAULT 'active' | `active, suspended` |
| rpm_limit / tpm_limit / concurrency_limit | INTEGER NOT NULL | CHECK > 0; defaults from `Settings` |
| log_unredacted | BOOLEAN NOT NULL DEFAULT false | FR-71 opt-in |
| created_at / updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### api_keys
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants(id) |
| key_prefix | TEXT NOT NULL | non-secret, e.g. `sy_` + 8 chars; display only |
| key_hash | BYTEA NOT NULL UNIQUE | HMAC-SHA-256 (32 bytes, CHECK `octet_length = 32`) |
| hmac_key_id | TEXT NOT NULL | which server HMAC key made the hash (HMAC key rotation) |
| name | TEXT NOT NULL | |
| status | TEXT NOT NULL DEFAULT 'active' | `active, revoked` (expiry is computed from `expires_at`) |
| expires_at | TIMESTAMPTZ NULL | |
| revoked_at | TIMESTAMPTZ NULL | CHECK `(status='revoked') = (revoked_at IS NOT NULL)` |
| rotated_from_id | UUID NULL | composite FK `(tenant_id, rotated_from_id)` → api_keys |
| created_at | TIMESTAMPTZ NOT NULL | |
Indexes: `UNIQUE (key_hash)` (auth lookup), `(tenant_id, status)`.

### policies (versioned, one active per tenant)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants |
| version | INTEGER NOT NULL | `UNIQUE (tenant_id, version)`; monotonic per tenant |
| document | JSONB NOT NULL | validated `PolicyDocument` (routes + execution) |
| source_sha256 | BYTEA NOT NULL | hash of the applied YAML (audit, no-op apply detection) |
| is_active | BOOLEAN NOT NULL DEFAULT false | |
| created_by | TEXT NOT NULL | CLI actor |
| created_at / activated_at | TIMESTAMPTZ | |
Indexes: `UNIQUE (tenant_id) WHERE is_active` (partial — one active per tenant), `(tenant_id, version DESC)`. Rows are immutable after insert except `is_active`/`activated_at` (enforced by repository; only invalid policies are never inserted, FR-94).

### budgets
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants |
| period_kind | TEXT NOT NULL | `monthly, daily` (OQ-02) |
| period_key | TEXT NOT NULL | `2026-11` or `2026-11-04` (UTC) |
| enforcement | TEXT NOT NULL | `hard, soft` |
| limit_usd / spent_usd / reserved_usd | NUMERIC(18,8) NOT NULL | spent/reserved DEFAULT 0, CHECK ≥ 0 |
| soft_alert_ratio | NUMERIC(5,4) NOT NULL DEFAULT 0.8 | OQ-07 |
| updated_at | TIMESTAMPTZ NOT NULL | |
Indexes: `UNIQUE (tenant_id, period_kind, period_key)`. No CHECK `spent ≤ limit`: settlement of real usage must never fail; the reservation guard is the control (see §2).

### reservations
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | |
| budget_id | UUID NOT NULL | composite FK `(tenant_id, budget_id)` → budgets |
| request_id | UUID NOT NULL | `UNIQUE (tenant_id, request_id, budget_id)` — one row per budget hit |
| amount_usd | NUMERIC(18,8) NOT NULL | CHECK > 0 |
| actual_usd | NUMERIC(18,8) NULL | set on commit |
| state | TEXT NOT NULL DEFAULT 'reserved' | `reserved, committed, released, expired` |
| policy_version | INTEGER NOT NULL | copied to expiry ledger marker |
| expires_at | TIMESTAMPTZ NOT NULL | `now() + deadline_ms + 5 min` (OQ-03) |
| created_at / finalized_at | TIMESTAMPTZ | CHECK `(state='reserved') = (finalized_at IS NULL)` |
Indexes: `(expires_at) WHERE state = 'reserved'` (expiry worker), `(tenant_id, request_id)`.
Transitions only `reserved → committed | released | expired` (FR-77): every UPDATE has `AND state = 'reserved'`; trigger `sy_reservation_transition()` rejects any UPDATE where `OLD.state <> 'reserved'`.

### ledger (append-only)
| Column | Type | Notes |
|---|---|---|
| id | BIGINT IDENTITY PK | `UNIQUE (tenant_id, id)` |
| tenant_id | UUID NOT NULL | FK → tenants |
| request_id | UUID NOT NULL | settlement idempotency key (FR-78), unique per `entry_kind` |
| entry_kind | TEXT NOT NULL | `settlement, expired, late_settlement` |
| attempt_ids | UUID[] NOT NULL DEFAULT '{}' | FR-81, all billable attempts |
| route_id | TEXT NULL | |
| provider / model_id | TEXT NULL | CHECK NOT NULL when `entry_kind='settlement' AND cache_status <> 'hit'` |
| input_tokens / output_tokens / cached_input_tokens / reasoning_tokens | INTEGER NOT NULL DEFAULT 0 | summed over attempts |
| cost_usd | NUMERIC(18,8) NOT NULL | CHECK ≥ 0 |
| reserved_usd | NUMERIC(18,8) NOT NULL | total released by this entry |
| pricing_version | TEXT NULL | NOT NULL when cost_usd > 0 |
| policy_version | INTEGER NOT NULL | FR-96 |
| usage_source | TEXT NOT NULL | `reported, estimated` (`UsageSource`) |
| cache_status | TEXT NOT NULL DEFAULT 'bypass' | `hit, miss, bypass` |
| terminal_state | TEXT NOT NULL | `COMPLETED, FAILED, CANCELLED, REJECTED` or `EXPIRED` |
| trace_id | TEXT NULL | NFR-16 correlation |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
Indexes: `UNIQUE (request_id, entry_kind)`, CHECK `entry_kind <> 'settlement'` OR no `expired` row exists (enforced in the settle tx, not a constraint), `(tenant_id, created_at DESC)`, `(tenant_id, entry_kind) WHERE entry_kind='expired'`. Append-only per global rules.

### idempotency_keys
| Column | Type | Notes |
|---|---|---|
| tenant_id | UUID NOT NULL | PK part 1; FK → tenants |
| key | TEXT NOT NULL | PK part 2; CHECK `length BETWEEN 1 AND 255` |
| request_hash | BYTEA NOT NULL | SHA-256 of canonical body (same canonical JSON as §7, all fields) |
| request_id | UUID NOT NULL | original request |
| status | TEXT NOT NULL | `in_progress, completed, failed` |
| response_ref | UUID NULL | = ledger.request_id of the original (replay audit) |
| response_body | JSONB NULL | stored `CanonicalResponse` for replay; NULL while in progress |
| http_status | SMALLINT NULL | replayed status |
| lease_expires_at | TIMESTAMPTZ NOT NULL | `now() + deadline_ms + 30 s`; stale `in_progress` past lease may be taken over |
| expires_at | TIMESTAMPTZ NOT NULL | `created_at + 24 h` (OQ-03) |
| created_at / updated_at | TIMESTAMPTZ | |
PK `(tenant_id, key)` (scoped by tenant, FR-83). Indexes: `(expires_at)` (cleanup worker). Retryable failures (5xx class) are stored `failed` and **not** replayed: next call with same key re-executes; non-retryable 4xx results are replayed.

### audit_events (append-only)
| Column | Type | Notes |
|---|---|---|
| id | BIGINT IDENTITY PK | |
| tenant_id | UUID NULL | NULL only for `auth_failed` with an unknown key; FK → tenants when set |
| event_type | TEXT NOT NULL | `key_created, key_rotated, key_revoked, key_expired_used, auth_failed, policy_applied, policy_activated, policy_rejected, reservation_expired, late_settlement_applied` |
| api_key_id | UUID NULL | composite FK `(tenant_id, api_key_id)` → api_keys (MATCH SIMPLE) |
| key_prefix | TEXT NULL | never the secret |
| actor | TEXT NOT NULL | `api`, `cli:<user>`, `worker:<name>` |
| request_id | UUID NULL | |
| details | JSONB NOT NULL DEFAULT '{}' | redacted by `Redactor` before insert |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
Indexes: `(tenant_id, created_at DESC)`, `(event_type, created_at DESC)`.

## 2. Money SQL (all `READ COMMITTED`; row locks give the atomicity)

### Reserve (BudgetRepository.reserve, one tx) — FR-75/76
```sql
-- :keys = current period keys for the tenant, :n = number of budget rows those keys match (list_current)
UPDATE budgets SET reserved_usd = reserved_usd + :amt, updated_at = now()
WHERE tenant_id = :t AND period_key = ANY(:keys)
  AND (enforcement = 'soft' OR spent_usd + reserved_usd + :amt <= limit_usd)
RETURNING id, enforcement, limit_usd, spent_usd, reserved_usd;
-- rows < :n → ROLLBACK → BudgetExceededError (402). This one conditional UPDATE is the overspend guard (NFR-05).
INSERT INTO reservations (tenant_id, budget_id, request_id, amount_usd, policy_version, expires_at)
SELECT :t, id, :r, :amt, :pv, now() + :ttl FROM unnest(:returned_ids) AS id;
COMMIT;
```
Soft rows with `(spent+reserved)/limit ≥ soft_alert_ratio` come back flagged → `BudgetService` emits the alert (FR-80). `:amt` = `CostEstimator.estimate_reservation` = `input_tokens_est × in_price × max_attempts + max_tokens × out_price` (retries happen only before the first token, so output is reserved once), taking the highest-priced candidate model in the route (see 02 §6). A tenant with no budget rows gets no reservation, but the ledger row is still written.

### Settle (LedgerRepository.append + BudgetRepository.settle in one `DbTransaction`) — FR-78/79
```sql
BEGIN;
SELECT id FROM reservations WHERE tenant_id = :t AND request_id = :r FOR UPDATE;  -- serialises settle vs expiry
INSERT INTO ledger (tenant_id, request_id, entry_kind, attempt_ids, route_id, provider, model_id,
  input_tokens, output_tokens, cached_input_tokens, reasoning_tokens, cost_usd, reserved_usd,
  pricing_version, policy_version, usage_source, cache_status, terminal_state, trace_id)
VALUES (:t, :r, 'settlement', ...)
ON CONFLICT (request_id, entry_kind) DO NOTHING RETURNING id;
-- (guarded: only attempted when the locked reservation is still 'reserved' or there is no reservation)
-- no row → already settled → COMMIT, SettlementResult(applied=False)
UPDATE budgets b SET spent_usd = b.spent_usd + :cost, reserved_usd = b.reserved_usd - r.amount_usd, updated_at = now()
FROM reservations r
WHERE r.tenant_id = :t AND r.request_id = :r AND r.state = 'reserved'
  AND b.tenant_id = r.tenant_id AND b.id = r.budget_id;
UPDATE reservations SET state = CASE WHEN :cost > 0 THEN 'committed' ELSE 'released' END,
  actual_usd = :cost, finalized_at = now()
WHERE tenant_id = :t AND request_id = :r AND state = 'reserved';
COMMIT;
```
`:cost` is added to every budget the request reserved against (each period counts the spend). A cache hit, or a request rejected before any attempt, settles with cost 0 → `released`. **Late settle after expiry (real usage is never dropped):** if the locked reservation is already `expired`, the tx instead inserts `entry_kind='late_settlement'` with the real cost (`ON CONFLICT (request_id, entry_kind) DO NOTHING`, so it stays idempotent) and does `spent_usd += :cost` on each reserved budget (no `reserved_usd` change; expiry already released it). This may push `spent` over `limit` — allowed, because there is no CHECK, and flagged with a `late_settlement_applied` audit event + `switchyard_late_settlements_total` metric + an alert. TTL = deadline + 5 min, so this only happens after a crash or stall. Ledger reads for a request: `late_settlement` supersedes `expired`.

### Expire (BudgetRepository.expire_due — WORKER-ONLY, one statement) — FR-82
```sql
WITH due AS (
  SELECT id FROM reservations WHERE state = 'reserved' AND expires_at < now()
  ORDER BY expires_at, id LIMIT :batch FOR UPDATE SKIP LOCKED),
exp AS (
  UPDATE reservations r SET state = 'expired', finalized_at = now() FROM due
  WHERE r.id = due.id AND r.state = 'reserved'
  RETURNING r.tenant_id, r.budget_id, r.request_id, r.amount_usd, r.policy_version),
rel AS (
  UPDATE budgets b SET reserved_usd = b.reserved_usd - s.amt, updated_at = now()
  FROM (SELECT tenant_id, budget_id, sum(amount_usd) AS amt FROM exp GROUP BY 1, 2) s
  WHERE b.tenant_id = s.tenant_id AND b.id = s.budget_id)
INSERT INTO ledger (tenant_id, request_id, entry_kind, cost_usd, reserved_usd, policy_version,
                    usage_source, terminal_state)
SELECT tenant_id, request_id, 'expired', 0, sum(amount_usd), max(policy_version), 'estimated', 'EXPIRED'
FROM exp GROUP BY tenant_id, request_id
ON CONFLICT (request_id) DO NOTHING
RETURNING tenant_id, request_id, reserved_usd;
```
The worker loops until 0 rows are returned. It emits `switchyard_reservations_expired_total` and one `reservation_expired` audit event per row.

### Idempotency acquire (IdempotencyRepository.acquire)
`INSERT ... (status='in_progress') ON CONFLICT (tenant_id, key) DO NOTHING RETURNING request_id` → inserted ⇒ `ACQUIRED`. Otherwise `SELECT ... FOR UPDATE`: hash differs ⇒ `MISMATCH` (422); `completed` or non-retryable `failed` ⇒ `REPLAY`; `in_progress` with a live lease ⇒ `IN_PROGRESS` (409); lease past, or retryable `failed` ⇒ `UPDATE` to the new request_id + lease ⇒ `ACQUIRED`.

## 3. Repositories (`switchyard.infrastructure.repositories`)
All methods are `async`. `TenantId = NewType("TenantId", UUID)`. Records are frozen `@dataclass(slots=True)` in `repositories/records.py`. Every SQL statement filters `tenant_id = :t` unless marked otherwise.
`Database.transaction() -> AsyncContextManager[DbTransaction]` wraps `AsyncSession.begin()`. Methods that take `tx` join the caller's tx; the others open their own.

| Class | Method signature | Notes |
|---|---|---|
| `TenantScopedRepository` (base) | `__init__(self, database: Database) -> None`; `_require_tenant(tenant_id: TenantId) -> None` | raises `ValueError` on nil UUID; base of all below |
| `TenantRepository` | `get(tenant_id: TenantId) -> TenantRecord \| None` | |
| | `get_limits(tenant_id: TenantId) -> TenantLimits` | rpm/tpm/concurrency/log_unredacted |
| | `create(slug: str, name: str, limits: TenantLimits) -> TenantRecord` | **ADMIN/CLI-ONLY** (no tenant yet) |
| `ApiKeyRepository` | `find_by_hash(key_hash: bytes) -> ApiKeyRecord \| None` | **AUTH-BOOTSTRAP-ONLY**: no tenant_id (this call resolves it) |
| | `create(tenant_id: TenantId, record: NewApiKey, tx: DbTransaction) -> ApiKeyRecord` | |
| | `rotate(tenant_id: TenantId, old_key_id: UUID, new: NewApiKey, tx: DbTransaction) -> ApiKeyRecord` | sets old `expires_at = now() + grace` |
| | `revoke(tenant_id: TenantId, key_id: UUID, at: datetime, tx: DbTransaction) -> bool` | |
| | `list(tenant_id: TenantId) -> list[ApiKeyRecord]` | sorted by created_at, id |
| `PolicyRepository` | `get_active(tenant_id: TenantId) -> PolicyRecord \| None` | LKG source |
| | `get_version(tenant_id: TenantId, version: int) -> PolicyRecord \| None` | |
| | `insert_and_activate(tenant_id: TenantId, document: PolicyDocument, source_sha256: bytes, actor: str) -> PolicyRecord` | one tx: lock tenant row `FOR UPDATE`, version = max+1, flip `is_active` |
| | `activate(tenant_id: TenantId, version: int, actor: str) -> PolicyRecord` | rollback to an older version |
| | `list_versions(tenant_id: TenantId, limit: int = 20) -> list[PolicyRecord]` | version DESC, limit ≤ 100 |
| `BudgetRepository` | `list_current(tenant_id: TenantId, at: datetime) -> list[BudgetRecord]` | |
| | `reserve(tenant_id: TenantId, request_id: UUID, amount: Decimal, period_keys: list[str], expected_rows: int, policy_version: int, ttl: timedelta) -> ReservationOutcome` | `ReservationOutcome(accepted, budgets, soft_alerts)` |
| | `settle(tenant_id: TenantId, request_id: UUID, cost: Decimal, tx: DbTransaction) -> SettledReservations` | budget + reservation updates from §2 |
| | `upsert_budget(tenant_id: TenantId, spec: BudgetSpec) -> BudgetRecord` | ADMIN/CLI |
| | `expire_due(now: datetime, batch: int) -> list[ExpiredReservation]` | **WORKER-ONLY**, cross-tenant (`ReservationExpiryWorker`) |
| `LedgerRepository` | `append(tenant_id: TenantId, entry: LedgerEntry, tx: DbTransaction) -> bool` | `False` = conflict (already settled) |
| | `get(tenant_id: TenantId, request_id: UUID) -> LedgerEntry \| None` | |
| | `list_recent(tenant_id: TenantId, since: datetime, limit: int = 100) -> list[LedgerEntry]` | created_at DESC, id DESC |
| `IdempotencyRepository` | `acquire(tenant_id: TenantId, key: str, request_hash: bytes, request_id: UUID, lease: timedelta, ttl: timedelta) -> IdempotencyAcquireResult` | `(outcome: IdempotencyOutcome, record)`; outcomes `ACQUIRED, REPLAY, IN_PROGRESS, MISMATCH` |
| | `complete(tenant_id: TenantId, key: str, request_id: UUID, response: CanonicalResponse, http_status: int) -> None` | guarded by `WHERE request_id = :r` |
| | `fail(tenant_id: TenantId, key: str, request_id: UUID, retryable: bool, http_status: int) -> None` | |
| | `delete_expired(now: datetime, batch: int) -> int` | **WORKER-ONLY** (`IdempotencyCleanupWorker`) |
| `AuditRepository` | `record(tenant_id: TenantId \| None, event: AuditEvent, tx: DbTransaction \| None = None) -> None` | `None` only for unknown-key `auth_failed` |
| | `list(tenant_id: TenantId, since: datetime, limit: int = 100) -> list[AuditEvent]` | |

`BudgetService.settle()` owns the tx: `async with db.transaction() as tx:` → `applied = await ledger.append(t, e, tx)` → if `applied`: `await budgets.settle(t, r, cost, tx)`.

## 4. Alembic
| Item | Choice |
|---|---|
| Layout | `alembic.ini` at repo root; `src/switchyard/infrastructure/db/migrations/{env.py,script.py.mako,versions/}`; async `env.py`, URL from `Settings.database_url`, `target_metadata = switchyard.infrastructure.db.metadata` |
| File name | `versions/NNNN_<snake_slug>.py`, e.g. `0004_budget_ledger.py`; `revision = "NNNN"` (pre-assigned, not random hex) |
| History | Strictly linear. CI checks `alembic heads` = 1, then runs `upgrade head` → `downgrade base` → `upgrade head` on a clean PG |
| Raw SQL | Triggers, grants and partial indexes via `op.execute()`; every migration has a working `downgrade()` |

| Rev | Branch (milestone) | Adds | down_revision |
|---|---|---|---|
| 0001 | feat/persistence-foundation (M3) | roles + grants, `sy_forbid_mutation()`, `tenants` | None |
| 0002 | feat/policy-versioning (M3) | `policies` + partial unique index | 0001 |
| 0003 | feat/tenant-auth (M5) | `api_keys`, `audit_events` + append-only trigger/revoke | 0002 |
| 0004 | feat/budget-ledger (M6) | `budgets`, `reservations` (+ transition trigger), `ledger` (+ append-only) | 0003 |
| 0005 | feat/idempotency-keys (M6) | `idempotency_keys` | 0003 in its worktree; rewritten to **0004** at the explicit group-O merge (both are group O; keeps history linear) |

## 5. Redis (`RedisClient`; scripts loaded with `SCRIPT LOAD`, called by `EVALSHA`, reload on `NOSCRIPT`)
`{...}` in key names is a Redis Cluster hash tag: all keys of one tenant (or one model) share a slot, so multi-key Lua stays legal on ElastiCache cluster mode.

| Key | Type | Fields / members | TTL | Owner |
|---|---|---|---|---|
| `sy:{tenant}:rl:rpm` | HASH | `tokens`, `ts_ms` | `PEXPIRE` 2 × 60 s, refreshed on every call | `RateLimiter` (`AdmissionService`) |
| `sy:{tenant}:rl:tpm` | HASH | `tokens`, `ts_ms` | 2 × 60 s, refreshed | `RateLimiter` |
| `sy:{tenant}:rl:conc` | ZSET | member `attempt lease id`, score `lease_expiry_ms` | `deadline_ms` + 60 s, refreshed on acquire | `ConcurrencyLimiter` |
| `sy:breaker:{model}` | HASH | `state` (closed/open/half_open), `opened_at_ms`, `probes_in_flight` | 1 h, refreshed on write | `CircuitBreaker` |
| `sy:breaker:{model}:fail` | ZSET | member `attempt_id`, score `ts_ms` | `rolling_window_s` × 2 | `CircuitBreaker` (rolling failure count) |
| `sy:{tenant}:cache:{policy_version}:{sha256}` | STRING | JSON `{"v":1,"response":CanonicalResponse,"stored_at":...}` | route `cache.ttl_s` (default 3600, OQ-06) | `CacheService` |
Time comes from `redis.call('TIME')` inside scripts, not from the replica clock, so 3 replicas agree (NFR-09 ±5%). TPM debits `input_est + max_tokens` at admission and credits back `estimate − actual` at settle (negative cost, capped at capacity).

**Token bucket** (`KEYS[1]` = rpm or tpm key; `ARGV` = capacity, refill_per_s, cost):
```
now_ms = TIME(); b = HMGET(KEYS[1], tokens, ts_ms)
tokens = b.tokens or capacity; ts = b.ts_ms or now_ms
tokens = min(capacity, tokens + (now_ms - ts) * refill_per_s / 1000)
if cost <= tokens: tokens -= cost; allowed = 1; retry_ms = 0
else: allowed = 0; retry_ms = ceil((cost - tokens) * 1000 / refill_per_s)
HSET(KEYS[1], tokens, tokens, ts_ms, now_ms); PEXPIRE(KEYS[1], 2 * ceil(capacity / refill_per_s) * 1000)
return {allowed, floor(tokens), retry_ms}       -- allowed=0 → RateLimitedError(retry_after_s = ceil(retry_ms/1000))
```
RPM and TPM run in one script call (`KEYS[1..2]`): both are checked before either is debited, so a TPM denial does not burn RPM.

**Concurrency semaphore** (`KEYS[1]` = conc key; `ARGV` = limit, lease_id, lease_ms):
```
now_ms = TIME(); ZREMRANGEBYSCORE(KEYS[1], -inf, now_ms)            -- drop leases of crashed replicas
if ZCARD(KEYS[1]) < limit: ZADD(KEYS[1], now_ms + lease_ms, lease_id); PEXPIRE(KEYS[1], lease_ms + 60000); return {1, 0}
oldest = ZRANGE(KEYS[1], 0, 0, WITHSCORES); return {0, oldest.score - now_ms}
release: ZREM(KEYS[1], lease_id)     -- in `finally` of the request; lease_ms = deadline_ms + 5 s
```

**Redis loss** (NFR-15, `failure-modes.md`): limits, breaker state and cache are lost; nothing else.
| Lost | Behaviour while Redis is down / after it returns |
|---|---|
| RPM/TPM/concurrency counters | Fail-open with `switchyard_redis_degraded` metric + alert; Postgres budget reservation still caps money. Buckets restart full |
| Breaker state | Each replica falls back to a process-local `CircuitBreaker` (same thresholds); shared state rebuilds from new failures |
| Exact cache | Every lookup = `miss` (or `bypass` on error), never an error (FR-92); entries refill naturally |
| Not lost | Tenants, keys, policies, budgets, reservations, ledger, idempotency, audit (all Postgres) |

## 6. Config shapes (YAML holds no secrets; secrets only via Secrets Manager references)

### `config/models.yaml` → `CapabilityRegistry` (loaded into `ModelSpec`; invalid file fails startup, FR-24)
| Field | Type | Rule |
|---|---|---|
| `registry_version` | str | required, e.g. `2026-11-01` |
| `models.<model_id>` | map key | `^(openai\|anthropic\|google)/[a-z0-9.-]+$`; this is the logical ID routes use |
| `.provider` | `openai \| anthropic \| gemini` | must match an `AdapterRegistry` entry; base URL is fixed in code (FR-22) |
| `.provider_model_id` | str | the ID sent upstream |
| `.capabilities` | `{streaming, tools, parallel_tools, structured_output}: bool` | all four required |
| `.context_window` / `.max_output_tokens` | int > 0 | `max_output_tokens ≤ context_window` |
| `.pricing` | `{input_per_mtok, output_per_mtok, cached_input_per_mtok}` | parsed as `Decimal` from strings, ≥ 0 |
| `.pricing_version` | str (date) | stamped into ledger |
| `.status` | `active \| deprecated \| disabled` | `disabled` never routable (FR-26) |

OQ-01 defaults (prices are placeholders: pin from provider price pages at M2 and set `pricing_version`):
| model_id | provider_model_id | ctx / max_out | in / out / cached per Mtok |
|---|---|---|---|
| `openai/gpt-4o` | `gpt-4o` | 128000 / 16384 | 2.50 / 10.00 / 1.25 |
| `openai/gpt-4o-mini` | `gpt-4o-mini` | 128000 / 16384 | 0.15 / 0.60 / 0.075 |
| `anthropic/claude-sonnet` | latest Sonnet ID (confirm M2) | 200000 / 64000 | 3.00 / 15.00 / 0.30 |
| `anthropic/claude-haiku` | latest Haiku ID (confirm M2) | 200000 / 64000 | 1.00 / 5.00 / 0.10 |
| `google/gemini-pro` | `gemini-2.5-pro` | 1048576 / 65536 | 1.25 / 10.00 / 0.31 |
| `google/gemini-flash` | `gemini-2.5-flash` | 1048576 / 65536 | 0.30 / 2.50 / 0.075 |
All six: `streaming, tools, parallel_tools, structured_output: true`, `status: active`.

### `config/policies/<tenant_slug>.yaml` → `PolicyDocument` (applied by `switchyard policy apply`)
| Path | Type | Default / rule |
|---|---|---|
| `tenant` | str | slug; must exist |
| `default_route` | str | must be a key of `routes` |
| `routes.<route_id>.strategy` | `RoutingStrategy` value | `fallback \| cheapest_capable \| lowest_latency \| weighted` |
| `routes.<route_id>.chain` | list[model_id] | 1–5 items, unique, all in registry, capability-compatible (FR-94) |
| `routes.<route_id>.weights` | map model_id → int ≥ 0 | required iff `weighted`; keys = chain |
| `routes.<route_id>.cache` | `{exact: bool, ttl_s: int}` | `false`, 3600 → `CachePolicy` |
| `routes.<route_id>.execution` | partial `ExecutionPolicy` | optional per-route override, merged over `execution` |
| `execution.deadline_ms / max_attempts / max_fallbacks` | int | 60000 / 3 / 2 |
| `execution.retry` | `{initial_backoff_ms, max_backoff_ms, jitter: full}` | 200 / 2000 → `RetryPolicy` |
| `execution.timeouts` | `{connect_ms, first_token_ms, idle_stream_ms}` | 2000 / 15000 / 10000 → `TimeoutPolicy` |
| `execution.circuit_breaker` | `{failure_threshold, rolling_window_s, open_duration_s, half_open_probes}` | 5 / 30 / 15 / 2 |
| `execution.retry_budget` | `{max_retry_ratio}` | 0.2 → `RetryBudgetPolicy` |
Unknown keys are rejected (`extra="forbid"`). `version` is assigned by Postgres, never written in YAML.

### `Settings` (pydantic-settings, prefix `SWITCHYARD_`, `extra="forbid"`; no `.env` file is read in prod)
| Env var | Type | Default | Notes |
|---|---|---|---|
| `SWITCHYARD_DATABASE_URL` | `SecretStr` (postgresql+asyncpg) | — required | password part may come from Secrets Manager in ECS task def |
| `SWITCHYARD_DB_POOL_SIZE` / `_DB_MAX_OVERFLOW` | int | 20 / 10 | |
| `SWITCHYARD_REDIS_URL` | `SecretStr` (redis/rediss) | — required | |
| `SWITCHYARD_API_KEY_HMAC_SECRET_REF` | str | — required | Secrets Manager ARN/name; value fetched at startup |
| `SWITCHYARD_API_KEY_HMAC_KEY_ID` | str | `k1` | current `hmac_key_id`; older IDs listed in the secret JSON for verification |
| `SWITCHYARD_PROVIDER_SECRET_REFS` | JSON map provider → ARN | `{}` | e.g. `{"openai":"arn:...:switchyard/openai"}` |
| `SWITCHYARD_SECRETS_BACKEND` | `aws \| env` | `aws` | `env` = test/dev only: reads `SWITCHYARD_PROVIDER_KEY_<PROVIDER>` injected outside the repo |
| `SWITCHYARD_AWS_REGION` | str | `us-east-1` | OQ-08 |
| `SWITCHYARD_OTEL_EXPORTER_OTLP_ENDPOINT` | AnyUrl | `http://otel-collector:4317` | |
| `SWITCHYARD_MODELS_PATH` | Path | `config/models.yaml` | |
| `SWITCHYARD_MAX_BODY_BYTES` | int | 1048576 | OQ-05 (1 MiB) → 413 |
| `SWITCHYARD_MAX_MESSAGES` | int | 256 | OQ-05 → 400 |
| `SWITCHYARD_MAX_TOOL_PAYLOAD_BYTES` | int | 65536 | OQ-05 (64 KiB) → 400 |
| `SWITCHYARD_MAX_TOKENS_CAP` | `model` | `model` | `max_tokens` capped at the model's `max_output_tokens` (OQ-05) |
| `SWITCHYARD_DEFAULT_RPM` / `_TPM` / `_CONCURRENCY` | int | 600 / 200000 / 20 | new-tenant defaults |
| `SWITCHYARD_RESERVATION_GRACE_S` | int | 300 | TTL = deadline + grace (OQ-03) |
| `SWITCHYARD_IDEMPOTENCY_TTL_S` | int | 86400 | OQ-03 |
| `SWITCHYARD_CACHE_MAX_VALUE_BYTES` | int | 262144 | larger responses are not stored |
| `SWITCHYARD_WORKER_BATCH` / `_WORKER_INTERVAL_S` | int | 500 / 30 | expiry + cleanup workers |

## 7. Exact cache key (`CacheKeyBuilder`, `switchyard.application.cache_service`; pure, deterministic)
1. Build the ordered **JSON array** (position fixes field order, FR-88): `["sy-cache-v1", tenant_id, route_id, policy_version, model, messages, tools, tool_choice, parallel_tool_calls, temperature, top_p, max_tokens, response_format, stop]`. `model` = the requested `model` field (lookup runs before routing).
2. Normalise: `messages` → each `{role, content, name?, tool_call_id?, tool_calls?}`, absent/None keys dropped; string content stays a string, content parts stay a list in order; whitespace and order are kept. `tools` kept in request order (order can change output). `stop`: string → `[string]`, absent → `[]`. Absent `tool_choice` → `"auto"` only if `tools` non-empty else `null`; absent `top_p`/`max_tokens` → `null`; absent `response_format` → `{"type":"text"}`. Numbers: `temperature`/`top_p` → `float`, so `0` and `0.0` match.
3. Serialise: `json.dumps(arr, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` → UTF-8 → `sha256().hexdigest()`. Redis key = `sy:{tenant}:cache:{policy_version}:{hex}` (tenant and version also in the key: defence in depth, FR-73).
4. Excluded: `stream`, `stream_options`, `user`, `metadata`, `seed`, `n` (must be 1), `Idempotency-Key`, `request_id`, auth headers.

| Eligibility check | Lookup | Store | Fails → |
|---|---|---|---|
| Route `cache.exact == true` | yes | yes | `bypass` |
| `temperature` present and `== 0` | yes | yes | `bypass` |
| `n` absent or 1; no provider `extensions` set | yes | yes | `bypass` |
| Streaming request: lookup allowed (hit replayed as SSE); store only if the full stream was buffered and ended with `StreamEnd`, no `StreamError` | yes | yes | `bypass` (store skipped) |
| Response has no tool calls and `finish_reason == stop` | — | yes | not stored |
| Serialised value ≤ `SWITCHYARD_CACHE_MAX_VALUE_BYTES` | — | yes | not stored |
| Redis error / timeout (50 ms) | yes | yes | `bypass` on error, never raised |
Header `x-switchyard-cache`: `hit` (served), `miss` (eligible, not found), `bypass` (ineligible or Redis down). A hit settles with cost 0 and a ledger row with `cache_status='hit'` (FR-91).
