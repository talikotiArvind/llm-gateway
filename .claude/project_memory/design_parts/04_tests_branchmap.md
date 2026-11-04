## 8. Test layout

| Dir | Scope | Infra | Covers |
|---|---|---|---|
| `tests/unit/` | domain + services with mocked deps (`MagicMock(spec=...)`); hypothesis property tests for lifecycle | none | lifecycle invariants (FR-37..41), error classification, routing, pricing, cache key, retry/backoff, breaker logic |
| `tests/contract/` | adapters vs recorded provider fixtures (`tests/contract/fixtures/{openai,anthropic,gemini}/*.json|*.sse`) via `respx`; one shared `AdapterContractTests` base run per provider | none | schema normalisation, streaming, tool calls, usage, malformed chunks |
| `tests/integration/` | full app + real Postgres/Redis (testcontainers or compose) + `fake_provider` | PG, Redis | gateway pipeline, budgets (200 concurrent), idempotency (1,000 dup), settlement, workers, policy apply/LKG |
| `tests/chaos/` | fault injection via `fake_provider` knobs + toxiproxy | PG, Redis, toxiproxy | NFR resilience, correlated outage, mid-stream drop, Redis loss, process kill |
| `tests/security/` | negative cross-tenant suite, key revocation/expiry, log redaction | PG, Redis | tenant isolation acceptance gate |
| `loadtest/` | k6 scripts (not pytest) | full stack | overhead p95, TTFT, rate-limit ±5% |

pytest markers: `unit`, `contract`, `integration`, `chaos`, `security`. CI default job runs `unit` + `contract`; integration/security run in a compose-backed job; chaos runs nightly. Layering is enforced by `import-linter` contracts in `pyproject.toml` (checked in CI) mirroring §1.

## 9. Branch file map and collision fixes

Paths relative to repo root; `sy/` = `src/switchyard/`.

### Cross-cutting ownership rules (apply to every parallel group)
1. **`pyproject.toml` / `uv.lock`** — owned by `chore/repo-bootstrap`, which pre-declares **every** v1 runtime + dev dependency (fastapi, uvicorn, pydantic, pydantic-settings, httpx, sqlalchemy[asyncio], asyncpg, alembic, redis, typer, pyyaml, opentelemetry-*; pytest, pytest-asyncio, pytest-cov, hypothesis, respx, testcontainers, ruff, mypy, bandit, pip-audit, import-linter). Later branches avoid editing it; if unavoidable, merge = union of dependency lists, re-run `uv lock`.
2. **All `__init__.py` files** — created empty by `chore/repo-bootstrap`; no branch adds re-exports.
3. **Composition root `sy/application/container.py` (`Container.build(settings)`, see 01 §1)** (builds adapters, services, `GatewayService`) — wiring changes happen only in the *integrating* branch named per group below; parallel branches ship standalone, unit-tested components.
4. **Alembic migrations** — pre-assigned revision numbers (see 03 §4), strictly linear history; when two branches in one group add migrations, the later one's `down_revision` is re-pointed at merge time.
5. **`code_index.md` / `metrics.md`** — merged per CLAUDE.md protocol (section merge / counter sum).

### Per-branch files
| # | Branch | Creates / edits |
|---|---|---|
| 1 | chore/repo-bootstrap | delete `src/ai/`, `src/app/`, `src/__init__.py`, `test/`; create `pyproject.toml`, `uv.lock`, `sy/**/__init__.py` (all packages), `sy/infrastructure/settings.py` (`Settings` skeleton), `tests/{unit,contract,integration,chaos,security}/__init__.py`, `tests/conftest.py`, `.github/workflows/ci.yml` (replace python-checks/unit-test), `.pre-commit-config.yaml`, `.gitignore`, `CLAUDE.md` (test path) |
| 2 | chore/compose-stack | `docker-compose.yml` (pg, redis, otel-collector, gateway, fake-provider service built from `fake_provider/Dockerfile`), `Dockerfile`, `infra/otel/collector.yaml`, `sy/api/app.py` (`create_app` + `/healthz`, `/readyz`), `sy/api/health.py`, `tests/unit/api/test_health.py` |
| 3 | feat/fake-provider | `fake_provider/{__init__,app,knobs,streaming}.py`, `fake_provider/Dockerfile`, `tests/unit/fake_provider/*` |
| 4 | docs/adr-001-002 | `docs/adr/0001-*.md`, `docs/adr/0002-*.md`, `docs/adr/README.md` |
| 5 | feat/canonical-schema | `sy/domain/schema.py`, `sy/domain/errors.py`, `sy/domain/capabilities.py` (**models only**: `ModelCapabilities`, `ModelPricing`, `ModelStatus`, `ModelSpec`), tests |
| 6 | feat/lifecycle-state-machine | `sy/domain/lifecycle.py`, `tests/unit/domain/test_lifecycle*.py`, `docs/adr/0003-*.md` |
| 7 | feat/adapter-openai | `sy/adapters/base.py`, `sy/adapters/openai.py`, `tests/contract/fixtures/openai/*`, `tests/contract/test_openai_adapter.py`, `tests/contract/base.py` (`AdapterContractTests`) |
| 8 | feat/api-surface | `sy/api/{routes,middleware,sse,errors,deps}.py` (see 02 §4), edit `sy/api/app.py` (router include), tests |
| 9 | feat/gateway-service-v1 | `sy/application/{gateway_service,execution_service}.py`, `sy/application/container.py`, edit `sy/api/routes.py` (call service), `tests/integration/test_openai_sdk_e2e.py` |
| 10 | feat/capability-registry | edit `sy/domain/capabilities.py` (add `CapabilityRegistry`, `RequiredCapabilities`, `CapabilityMatcher`), `sy/domain/pricing.py`, `sy/infrastructure/registry_loader.py`, `config/models.yaml`, `tests/unit/test_registry_completeness.py`, `docs/adr/0007-*.md` |
| 11 | feat/adapter-anthropic | `sy/adapters/anthropic.py`, `tests/contract/fixtures/anthropic/*`, `tests/contract/test_anthropic_adapter.py` |
| 12 | feat/adapter-gemini | `sy/adapters/gemini.py`, `tests/contract/fixtures/gemini/*`, `tests/contract/test_gemini_adapter.py` |
| 13 | test/provider-contract-suite | edit `tests/contract/base.py`, edit `sy/application/container.py` (register 3 adapters + registry), `tests/contract/test_all_providers.py` |
| 14 | feat/persistence-foundation | `sy/infrastructure/{db,redis_client}.py`, `sy/infrastructure/repositories/base.py`, `alembic.ini`, `sy/infrastructure/db/migrations/{env.py,versions/0001_tenants.py}`, edit `sy/infrastructure/settings.py`, tests |
| 15 | feat/routing-strategies | `sy/domain/routing.py` (`CandidateRanker`, `RoutePlanner`), `sy/application/routing_service.py` (`RoutingService`), tests |
| 16 | feat/policy-versioning | `sy/domain/policy.py`, `sy/application/policy_service.py`, `sy/infrastructure/repositories/policy_repository.py`, `sy/infrastructure/db/migrations/versions/0002_policies.py`, `sy/cli/{__init__,main,policy}.py`, `config/policies/default.yaml`, edit `sy/application/container.py`, edit `gateway_service.py` (policy resolve + route), `docs/adr/0010-*.md` |
| 17 | feat/retry-and-timeouts | `sy/application/{retry,retry_budget}.py`, edit `sy/adapters/base.py` (timeout helpers), tests, `docs/adr/0004-*.md` |
| 18 | feat/circuit-breaker | `sy/application/circuit_breaker.py`, `sy/infrastructure/lua/breaker.lua` (if used), tests |
| 19 | feat/execution-orchestrator | edit `sy/application/execution_service.py`, edit `sy/application/container.py`, `docs/adr/0005-*.md`, tests |
| 20 | test/chaos-suite | `tests/chaos/*`, compose override `docker-compose.chaos.yml` (toxiproxy), `.github/workflows/nightly.yml` |
| 21 | feat/tenant-auth | `sy/security/{api_keys,tenant_context}.py`, `sy/infrastructure/repositories/{tenant,api_key,audit}_repository.py`, `sy/infrastructure/db/migrations/versions/0003_api_keys_audit.py`, `sy/cli/keys.py`, edit `sy/api/middleware.py` + `sy/api/deps.py`, `docs/adr/0008-*.md` — **integrating branch for group M** (edits `gateway_service.py`, `container.py`) |
| 22 | feat/rate-limits | `sy/application/admission_service.py`, `sy/infrastructure/lua/{token_bucket,concurrency}.lua`, tests (standalone; no wiring) |
| 23 | feat/log-redaction | `sy/security/redaction.py`, `sy/infrastructure/logging.py`, `docs/security.md`, tests (standalone; no wiring) |
| 24 | test/tenant-isolation | wire `AdmissionService` + `Redactor` into `gateway_service.py`/`container.py`, `tests/security/*` |
| 25 | feat/budget-ledger | `sy/application/budget_service.py`, `sy/infrastructure/repositories/{budget,ledger}_repository.py`, `sy/infrastructure/db/migrations/versions/0004_budgets_ledger.py`, `docs/adr/0006-*.md`, tests (standalone) |
| 26 | feat/idempotency-keys | `sy/application/idempotency_service.py`, `sy/infrastructure/repositories/idempotency_repository.py`, `.../versions/0005_idempotency_keys.py` (down_revision 0003 in its worktree; re-pointed to **0004** at the group-O merge, keeping history linear), tests (standalone) |
| 27 | feat/maintenance-workers | `sy/workers/{reservation_expiry,idempotency_cleanup,runner}.py`, **wires budget + idempotency into `gateway_service.py`/`container.py`**, crash test |
| 28 | feat/exact-cache | `sy/application/cache_service.py`, edit `gateway_service.py`, `container.py`, `sy/api/routes.py` (header), `docs/adr/0009-*.md` |
| 29 | feat/observability | `sy/infrastructure/telemetry.py`, edits across services for spans, `dashboards/*.json`, `infra/alerts/*.yaml` |
| 30 | feat/graceful-shutdown | edit `sy/api/app.py` (lifespan drain), `sy/api/sse.py`, tests |
| 31 | chore/terraform-infra | `infra/terraform/**` |
| 32 | chore/cd-pipeline | `.github/workflows/{cd,smoke}.yml` |
| 33 | chore/loadtest-and-docs | `loadtest/**`, `docs/{architecture,failure-modes}.md`, `docs/runbooks/*`, `README.md` |

### Collisions found and fixes (changes to the confirmed branch table)
| Group | Collision | Fix |
|---|---|---|
| B (2,3,4) | `docker-compose.yml` needs the fake-provider service | #2 owns compose and references `fake_provider/Dockerfile` + `fake_provider.app:create_app` by contract; #3 never edits compose |
| C (5,6) | `lifecycle.AttemptRecord` imports `Usage` / `ErrorClass` from #5 → **not independent** | Move #6 into group **D**: #5 alone, then #6, #7, #8 in parallel |
| D (7,8) | both could edit `pyproject.toml` | pre-declared by #1 |
| F (10,11,12) | adapters need `ModelSpec`; registering adapters touches `container.py` | `ModelSpec` & friends created in #5 (models only); #10 adds registry/matcher; adapter registration done in #13 |
| J (17,18) | none on files; both need `RedisClient` from #14 | fine (H merged first) |
| M (21,22,23) | `gateway_service.py`, `container.py`, `api/middleware.py` | only #21 edits them; #22, #23 standalone; wiring moved into #24 (now "wire admission + redaction + isolation suite") |
| O (25,26) | two Alembic heads; both would wire `gateway_service.py` | 0005 re-pointed to 0004 at the group merge (CI asserts `alembic heads` = 1); wiring in #27 |
| all | `code_index.md`, `metrics.md` | CLAUDE.md merge protocol |
