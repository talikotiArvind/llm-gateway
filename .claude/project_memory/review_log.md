# Code Review Log

Review history across all iterations. Latest review is at the bottom.

**Refactor agent**: Count `## Review` entries to determine current iteration number.

---

<!-- Reviews appended below -->

---
## Review — 2026-11-05 — Iteration 1 — Milestone M0 (Foundations, 7e336b2..4b842ea)

### Context Loaded
- review_context.md: ✓ (prep_review_context.py wrote the file, then crashed printing U+2713 on a cp1252 stdout)
- Full file reads: none (budget used: 0/2); targeted views of new files from the diff only
- Objective metrics collected: ✓ (Docker absent locally: Dockerfiles/compose reviewed statically = conditional)

### Objective Metrics (facts)
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Ruff violations (check + format) | 0 / 40 files formatted | 0 | ✓ |
| Mypy errors (strict, src tests fake_provider) | 0 (34 files) | 0 | ✓ |
| lint-imports | 3 kept, 0 broken | all kept | ✓ |
| Tests | 69 passed (+8 subtests); 1 intermittent Windows-only failure | all pass | ~ |
| Line coverage (switchyard) | 100% (94 stmts) | ≥80% | ✓ |
| Branch coverage | 100% (6/6) | ≥75% | ✓ |
| Bandit (src, fake_provider) | 0 findings (4 parser warnings from a `# nosec B311 - ...` comment) | 0 | ✓ |
| pip-audit | 0 known vulns (local `switchyard` skipped) | 0 | ✓ |

### Files Reviewed
pyproject.toml, .github/workflows/ci.yml, Dockerfile, fake_provider/Dockerfile, docker-compose.yml,
src/switchyard/infrastructure/settings.py, src/switchyard/api/{app,health}.py,
fake_provider/{app,knobs,streaming}.py, tests/conftest.py, tests/unit/test_layering.py, docs/adr/*.

### Issues

#### CRITICAL (must fix — blocks approval)
- none

#### MAJOR (should fix — degrades quality)
- **[src/switchyard/infrastructure/settings.py:27-31]** Unknown `SWITCHYARD_*` env vars are silently ignored
  - Problem: `extra="forbid"` in pydantic-settings only rejects unknown init kwargs / dotenv keys, not environment variables. Verified: `SWITCHYARD_BOGUS=1` -> `Settings()` succeeds. A typo such as `SWITCHYARD_DEFAULT_RMP=50` silently runs with the default 600 rpm. The docstring ("invalid or unknown values fail at construction") is wrong, and `test_unknown_field_rejected` only covers kwargs.
  - Fix: add a `model_validator(mode="before")` (or a `settings_customise_sources` wrapper) that computes `{k[len(prefix):].lower() for k in os.environ if k.startswith("SWITCHYARD_")} - set(cls.model_fields)` and raises; add a test that sets an env var, not a kwarg.
- **[fake_provider/streaming.py:53-55, fake_provider/app.py:111-115]** `hang` never ends in a real server, so tasks leak
  - Problem: `SystemClock.hang()` waits "until cancelled (the client disconnects)", but uvicorn does not cancel a handler on disconnect, and Starlette's StreamingResponse (ASGI spec 2.4) detects a disconnect only on `send`. BEFORE_HEADERS, BEFORE_FIRST_CHUNK and MID_STREAM hangs therefore park one coroutine forever per request. Chaos suites will accumulate them and `open_connections` never decrements. Unit tests miss it because they use a fake clock.
  - Fix: bound the wait (a `hang_max_s` knob, default e.g. 300) and race it against disconnect (`while not await request.is_disconnected(): await asyncio.sleep(0.1)` inside `asyncio.timeout(...)`); pass `Request` (or a disconnect callable) into `CompletionService.handle` / `ChunkStreamer.stream`.
- **[.github/workflows/ci.yml:57-105, Dockerfile:5]** M0 exit gate "/healthz up" and both image builds are not verified anywhere
  - Problem: the integration job uses GH service containers; nothing runs `docker build` or `docker compose up --wait` + `curl /healthz`. Meanwhile the gateway Dockerfile pins `uv:0.5.11`, `uv.lock` is `revision = 3` (written by uv 0.12.x), and CI uses floating-latest uv, so a lock-format incompatibility would only surface at deploy time.
  - Fix: add a `compose-smoke` job: `docker compose config -q && docker compose up -d --wait gateway && curl -fsS localhost:8080/healthz`, plus `docker build fake_provider/`. Pin one uv version in setup-uv (`version:`) and in the Dockerfile `COPY --from=ghcr.io/astral-sh/uv:<same>`.
- **[pyproject.toml:105-116]** Layers contract only constrains *named* application modules
  - Problem: `:` (non-independent siblings, import-linter >= 2.1) is valid syntax and lint-imports keeps it, but every application module is listed explicitly and as optional. Any new module (e.g. `switchyard.application.ports`, `dto`, or a misspelled service name) belongs to no layer and may import `api` or orchestration freely. `:` also permits cycles between services (budget_service <-> routing_service).
  - Fix: add a unit test asserting every module under `switchyard/application/` appears in the layers contract (fail on unlisted modules), and add an `acyclic_siblings`/`independence` contract for the service tier, or document which service-to-service imports are intended.

#### MINOR (nice to fix — does not block)
- **[tests/unit/test_layering.py:95-101]** `subprocess.run(..., text=True)` decodes the Unicode banner of lint-imports with the locale codec; fails intermittently on Windows (cp1252, byte 0x90). Pass `encoding="utf-8", errors="replace"`. Linux CI is unaffected.
- **[.github/workflows/ci.yml:105]** `|| [ $? -eq 5 ]` is correct under `bash -e` (the `||` list suppresses errexit and `$?` is pytest's exit code), but it will also mask a future marker typo that deselects every integration test. Add a dated TODO and remove it once T14 lands integration tests.
- **[pyproject.toml:88-95]** `skip_empty` only hides zero-statement `__init__.py` files (no real gap). However `source=["switchyard"]` means fake_provider (~600 lines) is never coverage-measured; add a separate non-gating `--cov=fake_provider` report.
- **[pyproject.toml:7-24]** Runtime deps have no lower bounds except pydantic/sqlalchemy/redis. The lock compensates for the app, but add floors (fastapi, pydantic-settings>=2, opentelemetry-*) so `uv lock --upgrade` cannot regress silently.
- **[fake_provider/Dockerfile:39]** Hand-pinned fastapi/pydantic/uvicorn duplicate uv.lock and will drift (they match today). Non-root ✓. Consider `uv export` to a requirements file, or a check that the pins match the lock.
- **[Dockerfile / repo root]** No `.dockerignore`: the build context ships `.venv`, `.git`, `.claude/worktrees` (and any local `.env`) to the daemon. COPYs are explicit, so nothing is baked into the image, but it is slow and risky.
- **[docker-compose.yml:11-12,23-24]** Postgres/Redis are published on 0.0.0.0 with dev creds / no auth; bind to `127.0.0.1:`.
- **[docker-compose.yml:40-42]** The otel-collector healthcheck runs `validate` (config only, not liveness), yet `gateway` depends on it as "healthy". Acceptable for a distroless image; say so in the comment.
- **[src/switchyard/api/health.py:147-151]** Probes run sequentially with no per-probe timeout; a hung DB probe would hang `/readyz` past the ALB timeout. Wrap each probe in `asyncio.timeout(...)` and `asyncio.gather` before T14 adds real probes.
- **[src/switchyard/api/app.py:60-69]** `ReadinessChecker()` is built inside the factory with no injection point; T14 needs lifespan-created engines for its probes. Plan for `create_app(settings, probes=...)` or a lifespan that registers probes on `app.state`.
- **[fake_provider/app.py:107-109]** A `KnobError` raised in `handle` after `requests += 1` is never recorded in `by_status` (400s are invisible in /admin/stats).
- **[fake_provider/knobs.py:126-140]** RNG streams are process-global per seed; determinism holds only for sequential requests (concurrent requests interleave draws). Document this in the knob docs.
- **[fake_provider/streaming.py:195-206]** `malformed_at_chunk` / `drop_after_chunks` beyond the frame count are silent no-ops; reject them at plan time or document it.
- **[fake_provider/knobs.py:135]** `# nosec B311 - fault injection, not crypto` makes bandit parse the words as test IDs (4 warnings); use `# nosec B311`.
- **[docs/adr/]** File names differ from implementation_plan T04 (`0001-openai-compatible-api-canonical-schema.md`, `0002-ecs-fargate.md`); update the plan or rename. README links are internally consistent.
- **[.claude/hooks/prep_review_context.py:308]** Tooling: `print("✓ ...")` crashes on Windows cp1252 consoles (the output file is still written).

#### APPROVED (explicitly good — worth noting)
- SSE framing is correct: `data: <compact json>\n\n` per chunk, role-first delta, tool-call deltas carry `index`, a terminal `finish_reason` chunk, a usage chunk with `choices: []`, then `data: [DONE]\n\n`; a drop raises before `[DONE]`.
- Completion ids hash seed+model+messages; the injected Clock keeps all timing tests sleep-free; RngPool reset on admin update gives replayable error sequences.
- `Settings` is frozen, with typed limits (`PositiveInt`, `Literal`), no secrets and no `env_file`; settings fail at factory time.
- `/readyz` converts probe exceptions to `failed` (503) rather than 500, with a sorted checks payload; `/healthz` does no I/O.
- Gateway image: multi-stage, `--frozen --no-dev --no-editable`, uid 10001 non-root, exec-form CMD, HEALTHCHECK on /healthz; no secrets baked in. Compose uses `depends_on: service_healthy` throughout.
- CI: least-privilege `permissions: contents: read`, concurrency cancel, `uv sync --frozen`, a separate branch-rate gate, and a correctly guarded alembic-heads step.
- ADR-001/002: MADR structure with drivers, 4 options each with pros/cons, explicit consequences and FR/NFR traceability; ADR-002 ties drain/stopTimeout to the stream deadline and states the ~110 s ceiling.

### Risk Assessment
| Factor | Value (source) | Contributes to |
|--------|-------|-----------------|
| Unresolved CRITICAL issues | 0 (computed, review_context.md) | — |
| Security-check findings | 0 high (bandit 0, pip-audit 0; self-reported) | — |
| Layers touched by this diff | ai (data access), api (surface), app (service logic) (computed; ai/app are legacy deletions) | HIGH (>2 layers) |
| High-risk area touched (auth/payment/secret/a2a) | yes (computed; trigger = deletion of legacy `src/ai/a2a/`) | HIGH |
| Coverage delta vs target | 100% line / 100% branch vs 80/75 (self-reported) | LOW |
| Unresolved MAJOR issues | 4 (this review) | MEDIUM |

**Risk level: HIGH** — triggered by the computed rows (the legacy `src/ai`/`src/app` deletion counts as 3 layers + an a2a high-risk area). The substantive risk of the new code is MEDIUM. A human must confirm that deleting `src/ai`, `src/app` and `test/` is intended (the T01 spec says it is) before the pipeline proceeds.

### Summary
- Critical: 0 | Major: 4 | Minor: 16
- Ruff: 0 violations | Mypy: 0 errors | Coverage: 100% (switchyard)
- M0 exit gate: "CI green" — expected green on ubuntu-latest (every step passes locally; Linux avoids the Windows encoding flake). "/healthz up" — unit-tested via TestClient only; the container/compose path is unverified (conditional).
- Recommendation: **REQUEST_CHANGES**
- Risk: **HIGH**
---

### Refactor Evaluation — Iteration 1

| Issue | Decision | Reasoning |
|-------|----------|-----------|
| settings.py:27-31 — unknown `SWITCHYARD_*` env vars ignored | ACCEPT | Real correctness bug: `extra="forbid"` covers kwargs only, so `SWITCHYARD_DEFAULT_RMP` silently ran at 600 rpm. Added a `model_validator(mode="before")` that scans `os.environ` (case-insensitive) and lists unknown names sorted. Modification: `SWITCHYARD_PROVIDER_KEY_*` is exempt, because the design's `env` secrets backend reads those names directly; without the exemption the compose/test stack could never supply provider keys. |
| streaming.py:53-55, app.py:111-115 — `hang` never ends | ACCEPT | Uvicorn does not cancel a handler on disconnect, so each hung request parked a coroutine forever. Replaced `Clock.hang()` with `Clock.monotonic()` + a `HangWaiter` that polls a disconnect probe (`request.is_disconnected`) every 0.1 s, capped by the new `hang_max_s` knob (default 300 s, max 3600 s). Expiry semantics: before headers / non-stream -> 504 JSON (recorded in stats); before first chunk / mid stream -> `StreamDroppedError`, so the stream ends without `[DONE]` and `open_connections` is released. Tests use a fake clock whose `sleep` advances `monotonic`. |
| ci.yml:57-105, Dockerfile:5 — compose/healthz not verified, uv drift | ACCEPT | uv pinned to 0.12.21 in both setup-uv steps (`env.UV_VERSION`) and the Dockerfile; added `compose-smoke` (config, build, `up -d --wait`, curl `/healthz` and fake `/v1/models`, logs + `down -v` under `if: always()`). Added root and `fake_provider/` `.dockerignore`. Docker is not installed locally: the YAML was only parsed, the job itself is unverified until CI runs. |
| pyproject.toml:105-116 — layers contract misses unnamed modules | ACCEPT with modification | Design Part 02 section 1 has no `*_service` -> `*_service` imports, so the six services are now independent (`\|`). But it does require service -> support imports: `RoutingService` reads `CircuitBreaker` health, every service takes `security.TenantContext`, and services/security use `application.models` DTOs. Making all of these `\|` siblings (as asked) would make the design's own imports illegal. So: service tier `\|`, a support tier below it (`circuit_breaker \| retry_budget \| retry \| security`), and `application.models` just above domain. Orchestration keeps `:`. Added `ApplicationLayeringTest`: every module/subpackage under `src/switchyard/application/` must be named in the `layers` contract. |
| test_layering.py:95 — cp1252 decode | ACCEPT | `encoding="utf-8", errors="replace"`. |
| ci.yml:105 — `\|\| [ $? -eq 5 ]` | ACCEPT | Dated TODO to remove it when T14 lands integration tests. |
| pyproject.toml:88-95 — fake_provider not measured | ACCEPT | `source = ["switchyard", "fake_provider"]`, `fail_under` stays 80; CI and S5 use `--cov` so the config source applies. |
| pyproject.toml:7-24 — no lower bounds | REJECT (defer) | `uv sync --frozen` installs exactly the lock in CI and Docker, so floors change nothing today. Adding them rewrites `uv.lock`; out of scope for a review-fix branch. Add floors at the next deliberate `uv lock --upgrade`. |
| fake_provider/Dockerfile:39 — hand pins | REJECT (defer) | Pins match the lock today; the new compose-smoke job builds and health-checks the image, so a broken pin fails CI. Replacing pip with `uv export` changes the image build and belongs in its own task. |
| Dockerfile/root — no `.dockerignore` | ACCEPT | Done (MAJOR 3). |
| docker-compose.yml:11-12,23-24 — 0.0.0.0 ports | ACCEPT | Postgres/Redis bound to `127.0.0.1`. |
| docker-compose.yml:40-42 — otel healthcheck is config validation only | ACCEPT | Comment now says so and why it is acceptable. |
| health.py:147-151 — sequential probes, no timeout | REJECT (defer to T14) | No real probe exists yet; the only probes today do no I/O, so nothing can hang. T14 adds the DB/Redis probes and must add per-probe `asyncio.timeout` + `gather` then. |
| app.py:60-69 — no probe injection point | REJECT (defer to T14) | Design note, not a defect: design 4.1 already plans `create_app(settings)` + lifespan wiring through `Container`. Changing the factory now would guess T14's interface. |
| fake_provider/app.py:107-109 — KnobError not in `by_status` | ACCEPT | `handle` now records 400 before re-raising; test added. |
| knobs.py:126-140 — RNG determinism under concurrency | ACCEPT | Documented on `RngPool`. |
| streaming.py:195-206 — out-of-range drop/malformed indexes are no-ops | REJECT | Consistent with the knob meaning: "drop after N chunks" with N >= the frame count has nothing to drop. The frame count is only known after `chunks`, `usage` and `tool_call` are merged from the global store and headers, so plan-time rejection would couple validation across knobs for no correctness gain. |
| knobs.py:135 — `# nosec B311 - ...` | ACCEPT | Now `# nosec B311`; bandit prints no parser warnings. |
| docs/adr — names differ from plan T04 | ACCEPT | Kept the file names (ADR index and cross-links already use them); updated `implementation_plan.md` T04. The root README has no ADR links. |
| prep_review_context.py:308 — Windows print crash | REJECT (out of scope) | Agent tooling under `.claude/hooks`, not product code; it still writes its output file. Fix in a `chore/` tooling branch. |

### Refactor Applied — Iteration 1
- Implemented: all 4 MAJORs (settings env fail-fast, capped hang with disconnect polling, uv pin + compose-smoke + .dockerignore, two-tier service layering + application-layering test); MINORs: cp1252 decode, fake_provider coverage, exit-code-5 TODO, compose 127.0.0.1 binds, otel healthcheck comment, KnobError stats, RNG doc, nosec comment, ADR names in plan (STD-CHECKS S3/S5/S6 rows updated to cover fake_provider).
- Rejected/deferred: dependency floors, fake_provider pip pins, probe timeouts and probe injection (T14), out-of-range fault indexes (intended), prep_review_context.py print (tooling).
- Files changed: src/switchyard/infrastructure/settings.py, fake_provider/{app,knobs,streaming}.py, fake_provider/.dockerignore, .dockerignore, Dockerfile, docker-compose.yml, .github/workflows/ci.yml, pyproject.toml, tests/unit/{test_settings,test_layering}.py, tests/unit/fake_provider/{support,test_app,test_streaming}.py, .claude/project_memory/{implementation_plan,code_index,review_log}.md
- STD-CHECKS: S1 `uv sync --frozen` OK (lock unchanged) | S2 ruff 0 / 40 files formatted | S3 mypy `src tests fake_provider` 0 errors (34 files) | S4 lint-imports 3 kept | S5 86 passed, coverage 99.83% (switchyard + fake_provider; 1 partial branch) | S6 bandit `src fake_provider` 0 findings, 0 warnings; pip-audit 0 vulns
- Not verified locally: Docker images, compose stack, `compose-smoke` job (Docker absent; YAML parsed only).
- Risk: still HIGH per the M0 review's computed rows (legacy `src/ai`/`src/app` deletion incl. `a2a`). This refactor does not change that; it needs human confirmation, not auto-proceed.

---
## Review — 2026-11-05 — Iteration 2 — Milestone M0 re-review (refactor 8738372..55a8576)

### Context Loaded
- review_context.md: ✓ (`prep_review_context.py --base 8738372`, run with PYTHONIOENCODING=utf-8; the package lists only the 9 `.py` files, so the non-Python half of the diff (ci.yml, Dockerfile, compose, pyproject, .dockerignore) was read with `git diff`)
- Full file reads: none (budget used: 0/2); design.md Part 01 §1 and Part 02 §1 read by section
- Objective metrics collected: ✓ (Docker absent locally: compose-smoke job, images and .dockerignore reviewed statically = conditional)

### Objective Metrics (facts)
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Ruff violations (check + format) | 0 / 40 files formatted | 0 | ✓ |
| Mypy errors (strict, src tests fake_provider) | 0 (34 files) | 0 | ✓ |
| lint-imports | 3 kept, 0 broken | all kept | ✓ |
| Tests | 86 passed (+8 subtests), 0 failed (Windows, no cp1252 flake) | all pass | ✓ |
| Line coverage (switchyard + fake_provider) | 100% (501 stmts); total 99.83% incl. branches | ≥80% | ✓ |
| Branch coverage | 98.75% (79/80; partial `fake_provider/app.py:57->55`) | ≥75% | ✓ |
| Bandit (src, fake_provider) | 0 findings, 0 parser warnings | 0 | ✓ |

### Files Reviewed
settings.py, fake_provider/{app,knobs,streaming}.py, tests/unit/{test_settings,test_layering}.py,
tests/unit/fake_provider/*, pyproject.toml (importlinter + coverage), .github/workflows/ci.yml, Dockerfile,
docker-compose.yml, .dockerignore, fake_provider/.dockerignore.

### Verification of the 4 iteration-1 MAJORs
1. **Settings env rejection: FIXED.** `model_validator(mode="before")` scans `os.environ` case-insensitively, compares the suffix with `model_fields`, and lists names (never values) sorted. It is tested via env (not kwargs), lower-case, kwargs construction and the carve-out. The carve-out is narrow: one literal prefix, `SWITCHYARD_PROVIDER_KEY_`, which design Part 03 (`SWITCHYARD_SECRETS_BACKEND=env`) names as read outside `Settings`. No current or planned field starts with `provider_key_`, so no real-field typo can hide in it. The compose env (`SECRETS_BACKEND`, `OTEL_EXPORTER_OTLP_ENDPOINT`) matches existing fields, so the stack still starts; ci.yml sets no `SWITCHYARD_*` vars.
2. **fake_provider hang: FIXED.** `HangWaiter` polls `request.is_disconnected` every 0.1 s against a monotonic deadline (`hang_max_s`, default 300, `gt=0, le=3600`). Before-headers / non-stream returns a recorded 504; first-chunk / mid-stream raises `StreamDroppedError` (no `[DONE]`), and the `finally` in `_tracked` releases `open_connections`. Polling is correct in both Starlette modes (pre-2.4 `listen_for_disconnect` cancels anyway; 2.4 needs the poll because no `send` happens during a hang).
3. **uv pin / .dockerignore / compose-smoke: FIXED (static).** `UV_VERSION=0.12.21` is used by both setup-uv steps and the Dockerfile `COPY --from` tag. Root `.dockerignore` keeps `README.md`, `pyproject.toml`, `uv.lock` and `src/` (everything the Dockerfile COPYs) and excludes `.git`, `.claude`, `.venv`, `.env*`; `fake_provider` builds from its own context, so excluding it at the root is correct. `compose-smoke` runs config -q, build, `up -d --wait`, curls `/healthz` and `/v1/models`, then logs + `down -v` under `if: always()`. Not executed: conditional until the first CI run is green.
4. **Layering: FIXED, consistent with the design.** The six `*_service` modules are now independent (`|`), matching Part 02 §1 (no service-to-service imports). The support tier (`circuit_breaker | retry_budget | retry | security`) below them matches Part 02 §1.7/1.8 (routing wraps breaker health, services take `TenantContext`) and keeps `security` and the services apart (Part 01 §1 sibling rule). `application.models` above domain matches §1.1 (DTOs built only from domain types). `ApplicationLayeringTest` fails on any unlisted `switchyard.application.*` module or subpackage. The four-layer *direction* is still enforced (no upward imports); MINOR 1-3 cover what it still does not enforce.

### Issues

#### CRITICAL (must fix — blocks approval)
- none

#### MAJOR (should fix — degrades quality)
- none

#### MINOR (nice to fix — does not block)
1. **[pyproject.toml:105-124]** The `layers` contract forbids upward imports but not skips. Part 01 §1 says "no skips (api never imports infrastructure/adapters/services directly)"; today only convention (`Settings` under `TYPE_CHECKING`) keeps it. Pre-existing, not a regression. Fix: add a `forbidden` contract with `source_modules = ["switchyard.api", "switchyard.cli"]`, `forbidden_modules = ["switchyard.infrastructure", "switchyard.adapters"]` (+ the `*_service` modules once they exist, if the design keeps that rule).
2. **[design.md Part 01 §1 Enforcement row / decisions.md]** The design still shows the flat service layer. The two-tier split and the `application.models` layer (which now lets `infrastructure`/`adapters` import `application.models`, wider than "data access may import domain") are recorded only in a pyproject comment. Fix: update the Part 01 §1 table and append a decision entry.
3. **[design.md Part 02 §1.10 vs pyproject.toml:120]** `Redactor.redact_text` is "used by `Telemetry`" (infrastructure), but `security` sits above infrastructure, so that import will break the contract when Telemetry lands. Pre-existing design conflict, made visible here. Fix before the telemetry task: inject a redaction callable/Protocol into `Telemetry` from `Container`, or move the pure redactor into domain.
4. **[pyproject.toml:120]** `switchyard.application.retry` is not a module in the design (retry rules are `domain.policy.RetryPolicy` + `RetryBudget`). Drop it or add it to design Part 02.
5. **[tests/unit/test_layering.py:69-95]** The unlayered-module guard covers only `switchyard/application/`; a new top-level package (e.g. `switchyard.telemetry`) also escapes every layer. Fix: also assert that every `src/switchyard/*` package appears in the contract.
6. **[fake_provider/app.py:131-135, streaming.py:80-90]** A hang ended by client disconnect is still counted as a 504 in `by_status` (no client received it), and both callers ignore the `bool` that `HangWaiter.wait` returns. Either branch on it (e.g. a `disconnects` counter) or return `None`.
7. **[settings.py:16-17]** The carve-out accepts any suffix (`SWITCHYARD_PROVIDER_KEY_`, `..._OPENAII`). Fine for Settings, but the env secrets backend (T-secrets) should reject unknown provider suffixes so typos still fail fast.
8. **[.claude/hooks/prep_review_context.py]** Tooling: the context package omits non-`.py` files from "Changed Files"/diff and labels this diff "ai (data access)". Fix in a `chore/` branch.

#### Refactor rejections: judgement
All 6 are reasonable. Dependency floors and the fake_provider pip pins are covered by `uv sync --frozen` and the compose-smoke build; probe timeouts/injection belong to T14 (no I/O probe exists yet); out-of-range fault indexes are consistent knob semantics; the prep script is tooling. Keep them tracked for T14 and the next `uv lock --upgrade`.

#### APPROVED (explicitly good — worth noting)
- `HangWaiter` takes the injected `Clock` and validates its inputs; the fake clock's `sleep` advances `monotonic`, so the cap and the poll stay sleep-free and deterministic in tests.
- `KnobError` now lands in `by_status[400]`; `hang_max_s` is bounded (`le=3600`), so a client cannot request an unbounded park.
- The env-rejection error lists names only, never values: no secret leaks through `ValidationError` text.
- The layering test reads the real `pyproject.toml` via `tomllib` and has negative tests for an unlisted module and for subpackage discovery.

### Risk Assessment
| Factor | Value (source) | Contributes to |
|--------|-------|-----------------|
| Unresolved CRITICAL issues | 0 (computed, review_context.md) | — |
| Security-check findings | 0 (bandit 0 findings/0 warnings; self-reported) | — |
| Layers touched by this diff | 1: "ai (data access)" (computed, review_context.md; the refactor touches infrastructure.settings, fake_provider and tooling only) | — |
| High-risk area touched (auth/payment/secret/a2a) | no (computed, review_context.md) | — |
| Coverage delta vs target | 99.83% total / 98.75% branch vs 80/75 (self-reported, metrics.md) | LOW |
| Unresolved MAJOR issues | 0 (this review) | — |
| Legacy `src/ai`, `src/app`, `test/` deletion (iteration-1 HIGH trigger) | **human-confirmed** in chat by the user (2026-11-05) | resolved; not scored |

**Risk level: LOW.** The only iteration-1 HIGH trigger was the legacy deletion, which the user has now explicitly confirmed; the new code triggers no factor above LOW. Condition: the `compose-smoke` job has never run (no Docker locally); its first CI run must be green before merge.

### Summary
- Critical: 0 | Major: 0 | Minor: 8
- Ruff: 0 violations | Mypy: 0 errors | Coverage: 99.83% (line 100%, branch 98.75%)
- Iteration-1 MAJORs: 4/4 fixed (MAJOR 3 verified statically only)
- Recommendation: **APPROVE** (conditional on a green `compose-smoke` CI run)
- Risk: **LOW**
---
