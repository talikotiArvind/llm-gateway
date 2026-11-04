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
