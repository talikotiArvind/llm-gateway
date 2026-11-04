# Implementation Plan — Switchyard LLM Gateway

> Written by Planner 2026-11-04. Inputs: `design.md` (header + Part 04 §9, the branch file map), `requirements.md`
> (FR/NFR IDs), `project_plan.md` (milestones + exit gates). 33 tasks (T01..T33) = the 33 confirmed branches.
> `sy/` = `src/switchyard/`. Part 04 §9 collision fixes are applied (see §2). If this plan and §9 conflict, §9 wins.

## 1. Conventions

### 1.1 Branch, worktree, merge
| Rule | Detail |
|---|---|
| One branch per task | Branch names are the confirmed names (`chore/…`, `feat/…`, `test/…`, `docs/…`), cut from local `main` after the previous group has merged |
| Worktree per task | `git worktree add .claude/worktrees/<task-id>/ -b <branch> main`, e.g. `.claude/worktrees/t07/`. Mandatory for every `PARALLEL-GROUP-*` task (spawn `coding-agent` with `isolation: "worktree"` or the explicit command). `SEQUENTIAL-*` tasks use the same path for consistency |
| No self-merge | A task never merges itself. It reports done (all acceptance checks green inside its worktree) and stops |
| Group merge | Only after **every** task in the group reports done. Merge one task at a time, in the stated `Merge order` |
| Merge command | `git checkout main && git merge --squash <branch> && git commit -m "<type>: <summary> (Txx)"`; re-run the group's STD-CHECKS on `main` after each squash, before the next one |
| Clean-up | After the group is on `main` and green: `git worktree remove .claude/worktrees/<task-id>/` and `git branch -D <branch>` |
| Remote | No push / PR unless the user asks (user-confirmed default 4). `terraform apply` and live provider calls stay manual |
| Risk gate | Auto-merge only if the Code Reviewer's latest verdict is APPROVE and risk is LOW/MEDIUM. HIGH risk = stop and ask the user |

### 1.2 Shared-file merge protocol (CLAUDE.md "Parallel-group merge")
| File | Protocol |
|---|---|
| `.claude/project_memory/code_index.md` | Merge **by file-path section**. Sections are disjoint per §9 ownership, so take the union. If two worktrees carry the same section, keep the one from the worktree that owns that file in §9 and discard the other. Never accept a whole-file "theirs"/"ours" |
| `.claude/project_memory/metrics.md` | Integer counters (reads, index hits, full reads, session counts) are **summed** across worktrees: `main + Σ(worktree − base)`. Scores and ratios are not merged; re-run the `metrics` skill on `main` after the group merge |
| `pyproject.toml` / `uv.lock` | Owned by T01, which pre-declares every v1 dependency. Later tasks do not edit it. If one must: the merge = union of dependency lists, then `uv lock` on `main` |
| `__init__.py` | Created empty by T01. No task adds re-exports |
| `sy/application/container.py` | Edited only by the integrating task of a group (T09, T13, T16, T19, T21, T24, T27, T28) |
| Alembic `versions/` | Pre-assigned revisions 0001..0005, strictly linear. At the group-O merge, T26's `0005.down_revision` is changed from `"0003"` to `"0004"` in the squash commit. `uv run alembic heads` must print exactly one head |
| `docs/adr/README.md` | Created by T04 with all 10 ADR rows (`planned`). Each ADR task flips only its own row; at most one ADR writer per group |
| Any other conflict | Stop. Resolve by hand, record it in the task's Notes column (§5). Never let the later merge silently overwrite the earlier one |

### 1.3 STD-CHECKS (every task, in its worktree, before reporting done)
| # | Command | Must pass |
|---|---|---|
| S1 | `uv sync --frozen` | lock file unchanged, no resolver error |
| S2 | `uv run ruff check . && uv run ruff format --check .` | 0 violations |
| S3 | `uv run mypy src tests` | 0 errors (strict, from `pyproject.toml`) |
| S4 | `uv run lint-imports` | all contracts KEPT (layers, domain-forbidden, adapters ⟂ infrastructure) |
| S5 | `uv run pytest -m "unit or contract" --cov=switchyard --cov-branch` | all pass; line ≥ 80 %, branch ≥ 75 % (`fail_under` in pyproject) |
| S6 | `uv run bandit -q -r src && uv run pip-audit` | no HIGH/MEDIUM findings; no known vulns |
| S7 | Skills `linter`, `code-structure`, `annotations`, `security-check` | clean, 100 % annotation coverage |
| S8 | `git diff --name-only main...HEAD` | touches only the files in the task's **Files** row (+ project-memory files) |

Integration-marked checks (`-m integration|security|chaos`) need the compose stack: `docker compose up -d --wait`.

### 1.4 Milestone gates
The pipeline **stops at every milestone exit gate** (§4) and waits for the user's explicit confirmation before the
next milestone's first branch is cut. Per milestone: all groups merged → Code Reviewer (+ Refactor ≤ 3 iterations)
→ Unit Test agents → `metrics` skill → gate checklist → user confirmation.

## 2. Group and dependency graph

Labels are unique across the plan. `PARALLEL-GROUP-<M>-<X>` = run its tasks at the same time, one worktree each.
`SEQUENTIAL-<M>-<X>` = a single-task group. Every group starts only after all groups it depends on are merged to `main`.

### 2.1 Changes vs the confirmed branch table (Part 04 §9 fixes)
| Fix | Applied as |
|---|---|
| #6 depends on #5 (`AttemptRecord` uses `Usage`, `ErrorClass`) | T05 alone (`SEQUENTIAL-M1-C`); T06 moves into group D with T07, T08 (`PARALLEL-GROUP-M1-D`) |
| #2 vs #3 on compose | T02 owns `docker-compose.yml`, references `fake_provider/Dockerfile` by contract; T03 never edits compose |
| #10–#12 vs `container.py` | `ModelSpec` & friends come from T05; T10 adds registry/matcher; **T13 registers the 3 adapters + registry** |
| #21–#23 vs gateway/container/middleware | only T21 edits them; T22, T23 standalone; **T24 wires `AdmissionService` + `Redactor`** |
| #25/#26 two Alembic heads + wiring | **0005 re-pointed to 0004 at the group-O merge**; **T27 wires budget + idempotency** |
| M9 (planner choice) | T30 ⟂ T31 share no files → `PARALLEL-GROUP-M9-S`; T32 needs T31's ECS/RDS outputs → `SEQUENTIAL-M9-T` |

### 2.2 Graph
```
M0  SEQUENTIAL-M0-A      T01 ──► PARALLEL-GROUP-M0-B  {T02, T03, T04}
M1  SEQUENTIAL-M1-C      T05 ──► PARALLEL-GROUP-M1-D  {T06, T07, T08} ──► SEQUENTIAL-M1-E T09
M2  PARALLEL-GROUP-M2-F  {T10, T11, T12} ──► SEQUENTIAL-M2-G T13
M3  PARALLEL-GROUP-M3-H  {T14, T15} ──► SEQUENTIAL-M3-I T16
M4  PARALLEL-GROUP-M4-J  {T17, T18} ──► SEQUENTIAL-M4-K T19 ──► SEQUENTIAL-M4-L T20
M5  PARALLEL-GROUP-M5-M  {T21, T22, T23} ──► SEQUENTIAL-M5-N T24
M6  PARALLEL-GROUP-M6-O  {T25, T26} ──► SEQUENTIAL-M6-P T27
M7  SEQUENTIAL-M7-Q      T28
M8  SEQUENTIAL-M8-R      T29
M9  PARALLEL-GROUP-M9-S  {T30, T31} ──► SEQUENTIAL-M9-T T32
M10 SEQUENTIAL-M10-U     T33
Each milestone row starts only after the previous milestone's exit gate is confirmed by the user.
```

### 2.3 Group table
| Group | Tasks | Can start after | Merge order | Integrating task | Why this grouping |
|---|---|---|---|---|---|
| SEQUENTIAL-M0-A | T01 | immediately | — | T01 | everything needs pyproject + skeleton |
| PARALLEL-GROUP-M0-B | T02, T03, T04 | T01 merged | T03 → T02 → T04 | none | compose / fake_provider / docs: disjoint files |
| SEQUENTIAL-M1-C | T05 | M0 gate | — | — | schema + errors are imported by T06–T08 |
| PARALLEL-GROUP-M1-D | T06, T07, T08 | T05 merged | T06 → T07 → T08 | none | lifecycle / adapter / api: disjoint files |
| SEQUENTIAL-M1-E | T09 | group D merged | — | T09 (creates `container.py`) | needs T06+T07+T08 |
| PARALLEL-GROUP-M2-F | T10, T11, T12 | M1 gate | T10 → T11 → T12 | none | only T10 edits `capabilities.py` |
| SEQUENTIAL-M2-G | T13 | group F merged | — | T13 | registers adapters + registry in `container.py` |
| PARALLEL-GROUP-M3-H | T14, T15 | M2 gate | T14 → T15 | none | persistence ⟂ routing math |
| SEQUENTIAL-M3-I | T16 | group H merged | — | T16 | needs repo base (T14) + RoutePlanner (T15) |
| PARALLEL-GROUP-M4-J | T17, T18 | M3 gate | T17 → T18 | none | only T17 edits `adapters/base.py` |
| SEQUENTIAL-M4-K | T19 | group J merged | — | T19 | composes retry + breaker |
| SEQUENTIAL-M4-L | T20 | T19 merged | — | — | chaos suite needs the full orchestrator |
| PARALLEL-GROUP-M5-M | T21, T22, T23 | M4 gate | T21 → T22 → T23 | T21 (gateway/container/middleware) | T22, T23 standalone |
| SEQUENTIAL-M5-N | T24 | group M merged | — | T24 | wires admission + redaction, isolation suite |
| PARALLEL-GROUP-M6-O | T25, T26 | M5 gate | T25 → T26 (re-point 0005 → 0004) | none | both standalone, no wiring |
| SEQUENTIAL-M6-P | T27 | group O merged | — | T27 | wires budget + idempotency, workers |
| SEQUENTIAL-M7-Q | T28 | M6 gate | — | T28 | — |
| SEQUENTIAL-M8-R | T29 | M7 gate | — | T29 | edits across services for spans |
| PARALLEL-GROUP-M9-S | T30, T31 | M8 gate | T30 → T31 | none | app lifespan ⟂ terraform |
| SEQUENTIAL-M9-T | T32 | group S merged | — | — | CD deploys to T31's infra |
| SEQUENTIAL-M10-U | T33 | M9 gate | — | — | load runs need the deployed stack |

### 2.4 Forced sequential bottlenecks and risks
| Item | Risk / note | Mitigation |
|---|---|---|
| T05 | single-task critical path for all of M1 (L) | keep scope to models only; no registry logic (T10) |
| T09 | first `container.py` + first e2e; every later integrating task edits it | keep `Container.build` a flat list of factory calls so later diffs are additive |
| T19 | largest orchestration change (fallback, cancel, first-token rules) | rely on T06 hypothesis invariants as a regression net |
| T26 → T25 migration re-point | two heads if forgotten | CI step `alembic heads` = 1 + upgrade/downgrade/upgrade cycle |
| T29 | "edits across services" can touch any file | runs alone (`SEQUENTIAL-M8-R`); no parallel peer |
| FR-70 (Secrets Manager) | `sy/infrastructure/secrets.py` is not in the §9 file map | assigned to T21 (first consumer: HMAC secret); flag to System Designer to add the row |
| OQ-01..08 | open defaults (model IDs, budget period, TTLs, limits) | use the proposed defaults; T10 asks the user to confirm model IDs at the M2 gate |
| Chaos/load tooling | toxiproxy, k6, Docker needed locally | T20/T33 skip with an explicit reason if the tool is missing (CLAUDE.md failure recovery) |

## 3. Task blocks

Every task also runs STD-CHECKS S1–S8 (§1.3). The **Acceptance** row lists the task-specific checks on top.

### M0 — Foundations

#### T01 — chore/repo-bootstrap
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M0-A · worktree `.claude/worktrees/t01/` · Size **M** · Sub-agent `coding-agent` |
| Depends on | none |
| Files | delete `src/ai/`, `src/app/`, `src/__init__.py`, `src/__pycache__/`, `test/`, `.github/workflows/python-checks.yml`, `.github/workflows/unit-test.yml`; create `pyproject.toml`, `uv.lock`, `sy/**/__init__.py` (`api, cli, domain, application, adapters, infrastructure, infrastructure/repositories, infrastructure/db, security, workers`), `sy/infrastructure/settings.py`, `tests/{unit,contract,integration,chaos,security}/__init__.py`, `tests/conftest.py`, `tests/unit/test_layering.py`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `.gitignore`; edit `CLAUDE.md` (test paths) |
| Covers | FR-102, FR-13 (import-linter + AST layering test), NFR-17, constraint "delete old code" |
| Acceptance | `test ! -e src/ai -a ! -e src/app -a ! -e test -a ! -e src/__init__.py`; `uv lock --check`; `uv run python -c "import switchyard.api, switchyard.domain, switchyard.workers"`; `uv run lint-imports` → 3 contracts KEPT; `uv run pytest -m unit tests/unit/test_layering.py` passes; `uv run pytest --markers` lists `unit, contract, integration, chaos, security`; `SWITCHYARD_MAX_BODY_BYTES=abc uv run python -c "from switchyard.infrastructure.settings import Settings; Settings()"` raises `ValidationError`; `grep -n "test/" CLAUDE.md` → no hits for the old path; `ci.yml` parses (`actionlint` if installed) |
| Test dirs | `tests/unit/` |

Steps:
- Delete the old code, tests and workflows listed above (`git rm -r`); delete `src/__pycache__/`.
- `pyproject.toml`: build backend hatchling, package `switchyard` under `src/`, `requires-python = ">=3.12,<3.13"`; runtime deps fastapi, uvicorn[standard], pydantic>=2, pydantic-settings, httpx, sqlalchemy[asyncio]>=2, asyncpg, alembic, redis>=5, typer, pyyaml, boto3, opentelemetry-api/-sdk/-exporter-otlp/-instrumentation-fastapi/-instrumentation-httpx; dev group pytest, pytest-asyncio, pytest-cov, hypothesis, respx, testcontainers[postgres,redis], openai (e2e client only), ruff, mypy, types-PyYAML, bandit, pip-audit, import-linter. Then `uv lock`.
- Tool config: `[tool.ruff]` target py312, line 100, rules `E,F,W,I,N,UP,B,S,ANN,SIM,RUF`; `[tool.mypy] strict = true`, `plugins = ["pydantic.mypy"]`; `[tool.pytest.ini_options]` `testpaths=["tests"]`, `asyncio_mode="auto"`, markers `unit, contract, integration, chaos, security`, `--strict-markers`; `[tool.coverage.run] branch = true, source = ["switchyard"]`, `[tool.coverage.report] fail_under = 80` plus a CI branch-rate check ≥ 75.
- `[tool.importlinter]` with `exclude_type_checking_imports = true` and 3 contracts from Part 01 §1: `layers` (api|cli > gateway/execution/container/workers > *_service|security > infrastructure|adapters > domain), `forbidden` (domain ↛ httpx, sqlalchemy, asyncpg, redis, fastapi, starlette, opentelemetry, boto3, botocore, socket, aiofiles, subprocess), `independence` (adapters ⟂ infrastructure).
- Create every package `__init__.py` empty (no re-exports) and the `tests/*/__init__.py` files.
- `sy/infrastructure/settings.py`: `Settings(BaseSettings)` with `env_prefix="SWITCHYARD_"`, `extra="forbid"`, no `env_file`; fields from Part 03 §6 that need no I/O (`models_path`, `max_body_bytes`, `max_messages`, `max_tool_payload_bytes`, `max_tokens_cap`, `otel_exporter_otlp_endpoint`, `aws_region`, `secrets_backend`, `default_rpm/_tpm/_concurrency`); DB/Redis fields are added by T14, HMAC fields by T21.
- `tests/conftest.py` (env stub fixture clearing `SWITCHYARD_*`) and `tests/unit/test_layering.py` (`unittest.TestCase`, AST walk with `DOMAIN_IMPORT_ALLOWLIST`, runs `lint-imports` via subprocess when present).
- `.github/workflows/ci.yml`: job `checks` (uv setup, `uv sync --frozen`, ruff, ruff format --check, mypy, lint-imports, `pytest -m "unit or contract"` with coverage, bandit, pip-audit); job `integration` (compose services, `pytest -m "integration or security"`, `alembic heads` = 1 step guarded by `if: hashFiles('alembic.ini') != ''`).
- `.pre-commit-config.yaml` (ruff, ruff-format, mypy hooks), `.gitignore` (venv, caches, `site/`, `.claude/worktrees/`).
- CLAUDE.md: replace the `test/` path with `tests/` in the Stage Acceptance table; touch nothing else.

#### T02 — chore/compose-stack
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M0-B · worktree `.claude/worktrees/t02/` · Merge order **2** · Size **M** |
| Depends on | T01 |
| Files | `docker-compose.yml` (pg, redis, otel-collector, gateway, fake-provider built from `fake_provider/Dockerfile`), `Dockerfile`, `infra/otel/collector.yaml`, `sy/api/app.py` (`create_app` + `/healthz`, `/readyz`), `sy/api/health.py`, `tests/unit/api/test_health.py` |
| Covers | FR-03, FR-103 |
| Acceptance | `docker compose config -q`; `uv run pytest -m unit tests/unit/api/test_health.py` (TestClient: `/healthz` → 200 `{"status":"ok"}`, `/readyz` → 200 with no probes registered); after group merge: `docker compose up -d --wait gateway postgres redis otel-collector` then `curl -fsS localhost:8080/healthz`; `docker build -t switchyard:dev .` succeeds |
| Test dirs | `tests/unit/api/` |

Steps:
- Multi-stage `Dockerfile`: `uv sync --frozen --no-dev` builder, slim python:3.12 runtime, non-root user, `uvicorn switchyard.api.app:create_app --factory`.
- `docker-compose.yml`: postgres:16 + redis:7 with healthchecks, otel-collector (contrib) mounting `infra/otel/collector.yaml`, `gateway` (depends_on healthy), `fake-provider` with `build: fake_provider/` and command `uvicorn fake_provider.app:create_app --factory` (contract only; T03 owns the Dockerfile).
- `infra/otel/collector.yaml`: OTLP gRPC/HTTP receivers, batch processor, `debug` exporter (Tempo/Prometheus exporters added in T29).
- `sy/api/health.py`: health router with `/healthz` (liveness, no I/O) and `/readyz` (runs registered async probes; none yet).
- `sy/api/app.py`: `create_app(settings: Settings) -> FastAPI` (Settings under `TYPE_CHECKING`), includes the health router; factory form for uvicorn.
- `tests/unit/api/test_health.py`: `unittest.TestCase` + `TestClient`; settings stubbed.

#### T03 — feat/fake-provider
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M0-B · worktree `.claude/worktrees/t03/` · Merge order **1** · Size **M** |
| Depends on | T01 |
| Files | `fake_provider/{__init__,app,knobs,streaming}.py`, `fake_provider/Dockerfile`, `tests/unit/fake_provider/*` |
| Covers | FR-104 |
| Acceptance | `uv run pytest -m unit tests/unit/fake_provider` covers: OpenAI-shaped non-stream + SSE ending `[DONE]`; tool-call response; knobs latency_ms, error_rate (seeded), 429 with `Retry-After`, 503, 529, hang (no first byte), stream drop after N chunks, malformed chunk; `docker build fake_provider/` succeeds; nothing in `switchyard` imports `fake_provider` |
| Test dirs | `tests/unit/fake_provider/` |

Steps:
- `knobs.py`: `FakeKnobs` (pydantic) — `latency_ms`, `error_rate`, `error_status`, `retry_after_s`, `hang`, `drop_after_chunks`, `malformed_at_chunk`, `seed`; set per request via `x-fake-*` headers or globally via `POST /_knobs`.
- `streaming.py`: `ChunkStreamer` yielding OpenAI `chat.completion.chunk` frames incl. tool-call deltas and a final usage chunk; honours drop/malformed knobs.
- `app.py`: `create_app() -> FastAPI` with `POST /v1/chat/completions` (stream + non-stream) and `GET /v1/models`; deterministic content from a seeded `random.Random`.
- `Dockerfile`: python:3.12-slim, runs `uvicorn fake_provider.app:create_app --factory --port 9000`.
- Tests with `httpx.AsyncClient(transport=ASGITransport(app))`; fixed seed for error-rate assertions.

#### T04 — docs/adr-001-002
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M0-B · worktree `.claude/worktrees/t04/` · Merge order **3** · Size **S** |
| Depends on | T01 |
| Files | `docs/adr/0001-openai-compatible-api-canonical-schema.md`, `docs/adr/0002-ecs-fargate.md`, `docs/adr/README.md` |
| Covers | FR-109 (ADR-001, ADR-002) |
| Acceptance | both ADRs have Status / Context / Decision / Consequences / Alternatives sections; README lists ADR 001–010 with 001/002 `accepted`, the rest `planned`; every relative link target exists |
| Test dirs | none |

Steps:
- Follow the ADR-000 conventions in `decisions.md`; content from its ADR-001/002 entries and plan §2/§13.
- README index table: number, title, status, milestone (from FR-109).
- No code changes.

### M1 — Single provider

#### T05 — feat/canonical-schema
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M1-C · worktree `.claude/worktrees/t05/` · Size **L** |
| Depends on | M0 gate |
| Files | `sy/domain/schema.py`, `sy/domain/errors.py`, `sy/domain/capabilities.py` (**models only**: `ModelCapabilities`, `ModelPricing`, `ModelStatus`, `ModelSpec`), `tests/unit/domain/test_schema.py`, `test_errors.py`, `test_capability_models.py` |
| Covers | FR-09, FR-10, FR-11, FR-12, FR-13, FR-62, NFR-18 |
| Acceptance | `uv run pytest -m unit tests/unit/domain`: round-trip of every supported request field; every unknown top-level field → `InvalidRequestError` (no silent drop, FR-10); `StreamEvent` union parses all 6 variants and rejects an unknown `type`; table test covers every `ErrorClass` (fixed retryable flag + HTTP status) and `classify()`; context-overflow detection cases; `tests/unit/test_layering.py` still passes; `ModelSpec` rejects negative pricing |
| Test dirs | `tests/unit/domain/` |

Steps:
- `schema.py`: pydantic v2 models with `ConfigDict(extra="forbid", frozen=True)`; `ChatMessage`, `ToolDefinition`, `ToolCall`, `ToolChoice`, `ResponseFormat` (json_schema), `CanonicalRequest` (incl. `parallel_tool_calls`, namespaced `provider_extensions`), `Usage`, `UsageSource`, `FinishReason`, `CanonicalResponse`.
- Stream events `StreamStart`, `ContentDelta`, `ToolCallDelta`, `UsageEvent`, `StreamEnd`, `StreamError`, each with `sequence: int`; union `StreamEvent` discriminated on `type`.
- `errors.py`: `GatewayError` + the 14 subclasses from the naming contract; `ErrorClass` (FR-62 list); `RetryDecision`; `classify(error)`; `RateLimitedError.retry_after_s`, `ProviderTimeoutError.kind`, `NoEligibleModelError.reason`.
- Class → (retryable, http_status) as a frozen constant `ERROR_CLASS_TABLE`.
- `capabilities.py` models only; money fields are `Decimal`.
- Tests: `unittest.TestCase`, table-driven, no I/O.

#### T06 — feat/lifecycle-state-machine
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M1-D · worktree `.claude/worktrees/t06/` · Merge order **1** · Size **M** |
| Depends on | T05 |
| Files | `sy/domain/lifecycle.py`, `tests/unit/domain/test_lifecycle.py`, `tests/unit/domain/test_lifecycle_properties.py`, `docs/adr/0003-lifecycle-state-machine.md` (+ own row in `docs/adr/README.md`) |
| Covers | FR-36, FR-37, FR-38, FR-39, FR-109 (ADR-003) |
| Acceptance | `uv run pytest -m unit tests/unit/domain/test_lifecycle*.py`; hypothesis `RuleBasedStateMachine` (≥ 200 examples, `derandomize=True`) proves exactly one terminal state, `settle()` idempotent → exactly one SETTLED, `RETRY_WAIT`/`FALLBACK` only from `ATTEMPTING` while `first_token_seen` is false, unique `attempt_id`s; every illegal transition raises `IllegalTransitionError`; `billable_attempts()` includes failed attempts with usage |
| Test dirs | `tests/unit/domain/` |

Steps:
- `RequestState` (13 states) and `ALLOWED_TRANSITIONS: Mapping[RequestState, frozenset[RequestState]]` from plan §4.
- `AttemptRecord` (frozen) with `Usage | None`, `ErrorClass | None`.
- `RequestLifecycle(request_id, clock, id_factory)` — clock and id factory injected (NFR-18).
- `transition(to)`, `start_attempt(model_id)`, `finish_attempt(...)`, `mark_first_token()`, `settle()` (second call no-op), `billable_attempts()`.
- Example tests + hypothesis state machine.
- ADR-003; flip its README row to `accepted`.

#### T07 — feat/adapter-openai
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M1-D · worktree `.claude/worktrees/t07/` · Merge order **2** · Size **L** |
| Depends on | T05 |
| Files | `sy/adapters/base.py`, `sy/adapters/openai.py`, `tests/contract/base.py` (`AdapterContractTests`), `tests/contract/fixtures/openai/*`, `tests/contract/test_openai_adapter.py` |
| Covers | FR-14, FR-15, FR-19, FR-20, FR-47 |
| Acceptance | `uv run pytest -m contract tests/contract/test_openai_adapter.py` (respx + recorded fixtures, no network): text completion; tool call + parallel tool calls with IDs; streaming with increasing `sequence` and exactly one terminal event; usage incl. cached/reasoning tokens, `usage_source=reported`; malformed chunk → `StreamError(malformed_response)`, no exception; 429 → `RateLimitedError(retry_after_s)`, 529/503 → `ProviderOverloadedError`/`ProviderServerError`, 400 context-length → `ContextOverflowError`; `lint-imports` adapters ⟂ infrastructure KEPT |
| Test dirs | `tests/contract/` |

Steps:
- `base.py`: `ProviderAdapter` Protocol (`complete`, `stream`), `AttemptContext(attempt_id, deadline, timeouts, cancel_event)`, `AdapterRegistry` (register / get by provider, sorted `providers()`).
- `openai.py`: `OpenAIAdapter(http: httpx.AsyncClient, api_key_provider)`; canonical → OpenAI mapping (reject unmappable fields); response and SSE parsing into `StreamEvent`s.
- Validate each chunk with pydantic chunk models; any validation error → `StreamError` and stop.
- HTTP status → domain error mapping incl. `Retry-After` parsing.
- Record fixtures (`*.json`, `*.sse`) from fake_provider / provider docs; scrub IDs.
- `AdapterContractTests` base (abstract `make_adapter()`, `fixture_dir`) + OpenAI subclass.

#### T08 — feat/api-surface
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M1-D · worktree `.claude/worktrees/t08/` · Merge order **3** · Size **L** |
| Depends on | T05 (T02's `app.py` already on `main`) |
| Files | `sy/api/{routes,middleware,sse,errors,deps}.py`, edit `sy/api/app.py` (router include), `tests/unit/api/test_{routes,middleware,sse,errors}.py` |
| Covers | FR-01, FR-02, FR-04, FR-05, FR-06, FR-08 |
| Acceptance | `uv run pytest -m unit tests/unit/api`: `x-request-id` on every response incl. errors; body > `max_body_bytes` → 413 before JSON parse (pure ASGI, no buffering of streams); `SseEncoder` frames match OpenAI chunk format and end with `data: [DONE]`; `ErrorMapper` body `{"error":{"message","type","param","code"}}` with status from `ERROR_CLASS_TABLE`; `/v1/models` OpenAI list shape; routes depend on a gateway Protocol stub, not a service import |
| Test dirs | `tests/unit/api/` |

Steps:
- `middleware.py`: `RequestIdMiddleware`, `BodyLimitMiddleware` as pure ASGI classes (no `BaseHTTPMiddleware`).
- `sse.py`: `SseEncoder.encode(event) -> bytes`; `[DONE]` only on success, typed error event otherwise.
- `errors.py`: `ErrorMapper` + exception handlers for `GatewayError` and request `ValidationError` → 400.
- `deps.py`: `get_gateway()` from `app.state`; `get_tenant_context` placeholder (anonymous tenant until T21).
- `routes.py`: `POST /v1/chat/completions` (JSON or `StreamingResponse`), `GET /v1/models`.
- Edit `app.py` only to include router + middleware.

#### T09 — feat/gateway-service-v1
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M1-E · worktree `.claude/worktrees/t09/` · Size **L** · integrating task |
| Depends on | T06, T07, T08 |
| Files | `sy/application/gateway_service.py`, `sy/application/execution_service.py`, `sy/application/container.py`, edit `sy/api/routes.py` (call service), `tests/unit/application/test_{gateway,execution}_service.py`, `tests/integration/test_openai_sdk_e2e.py` |
| Covers | FR-07, FR-01, FR-04, FR-37, FR-38 (end to end) |
| Acceptance | `uv run pytest -m unit tests/unit/application`; `docker compose up -d --wait fake-provider gateway` then `uv run pytest -m integration tests/integration/test_openai_sdk_e2e.py`: unmodified `openai` SDK (only `base_url` changed) streams a 2-turn tool-call conversation via `OpenAIAdapter` → fake_provider, ending `[DONE]`; every request ends in exactly one SETTLED (lifecycle spy); `lint-imports` KEPT with `container` in layer 3 |
| Test dirs | `tests/unit/application/`, `tests/integration/` |

Steps:
- `ExecutionService.execute(...)` / `stream(...)`: single attempt on one model, no retry yet; drives lifecycle transitions.
- `GatewayService.handle(req, tenant)`: RECEIVED → ADMITTED → ROUTED (static model lookup) → execute → terminal → `settle()` in `finally`.
- `Container.build(settings)`: flat list of factory calls — httpx client, `AdapterRegistry` with `OpenAIAdapter`, `ExecutionService`, `GatewayService` (later tasks append lines).
- `create_app` gets the container in lifespan; `routes.py` calls `GatewayService` through the port.
- Provider key via `SWITCHYARD_SECRETS_BACKEND=env` (fake_provider only; no real key in repo).
- e2e test uses the `openai` dev dependency pre-declared by T01.

### M2 — Provider abstraction

#### T10 — feat/capability-registry
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M2-F · worktree `.claude/worktrees/t10/` · Merge order **1** · Size **M** |
| Depends on | M1 gate (T05 models) |
| Files | edit `sy/domain/capabilities.py` (add `CapabilityRegistry`, `RequiredCapabilities`, `CapabilityMatcher`), `sy/domain/pricing.py` (`CostEstimator`), `sy/infrastructure/registry_loader.py`, `config/models.yaml`, `tests/unit/test_registry_completeness.py`, `tests/unit/domain/test_{capability_matcher,pricing}.py`, `docs/adr/0007-capability-registry.md` (+ own README row) |
| Covers | FR-23, FR-24, FR-25, FR-26, FR-27, FR-29 (matcher), FR-109 (ADR-007), NFR-18 |
| Acceptance | `uv run pytest -m unit tests/unit/test_registry_completeness.py` fails if any `active`/`deprecated` model lacks pricing or capabilities (prove with a broken temp YAML); loader raises on invalid YAML (startup fails, FR-24); `disabled` never returned by `routable()`; `deprecated` flagged; `CostEstimator.actual_cost` uses `Decimal` quantized `0.00000001`, `ROUND_HALF_EVEN`, golden-value table; `estimate_reservation` = `input_est × in_price × max_attempts + max_tokens × out_price` at the most expensive candidate; matcher property test (hypothesis) never returns a model lacking a required capability; model IDs per OQ-01 defaults, flagged for user confirmation at M2 gate |
| Test dirs | `tests/unit/`, `tests/unit/domain/` |

#### T11 — feat/adapter-anthropic
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M2-F · worktree `.claude/worktrees/t11/` · Merge order **2** · Size **L** |
| Depends on | M1 gate (T07 `base.py`, `AdapterContractTests`) |
| Files | `sy/adapters/anthropic.py`, `tests/contract/fixtures/anthropic/*`, `tests/contract/test_anthropic_adapter.py` |
| Covers | FR-16, FR-19, FR-20, FR-47 (Anthropic) |
| Acceptance | `uv run pytest -m contract tests/contract/test_anthropic_adapter.py` — subclass of `AdapterContractTests` passes unchanged: system-message hoisting, tool_use/tool_result mapping with stable IDs, SSE `message_start/content_block_delta/message_delta` → canonical events with increasing `sequence`, usage incl. cache-read tokens, 529 → `ProviderOverloadedError`, 429 + `retry-after`, malformed event → `StreamError`; no edits to `base.py` or `container.py` (S8) |
| Test dirs | `tests/contract/` |

#### T12 — feat/adapter-gemini
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M2-F · worktree `.claude/worktrees/t12/` · Merge order **3** · Size **L** |
| Depends on | M1 gate (T07) |
| Files | `sy/adapters/gemini.py`, `tests/contract/fixtures/gemini/*`, `tests/contract/test_gemini_adapter.py` |
| Covers | FR-17, FR-19, FR-20, FR-47 (Gemini) |
| Acceptance | `uv run pytest -m contract tests/contract/test_gemini_adapter.py` — `AdapterContractTests` subclass passes: `contents`/`systemInstruction` mapping, `functionCall` → `ToolCall` with synthesized deterministic IDs, `streamGenerateContent?alt=sse` parsing, `usageMetadata` incl. cached + thoughts tokens, 503/429 mapping, malformed chunk → `StreamError`; no edits to `base.py`/`container.py` |
| Test dirs | `tests/contract/` |

#### T13 — test/provider-contract-suite
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M2-G · worktree `.claude/worktrees/t13/` · Size **M** · integrating task (registers adapters) |
| Depends on | T10, T11, T12 |
| Files | edit `tests/contract/base.py`, edit `sy/application/container.py` (register OpenAI/Anthropic/Gemini adapters + `CapabilityRegistry` from `registry_loader`), `tests/contract/test_all_providers.py` |
| Covers | FR-18, FR-24 (startup load), FR-02 (`/v1/models` from registry) |
| Acceptance | `uv run pytest -m contract` — `test_all_providers.py` parametrizes the **same** `AdapterContractTests` over 3 providers, all green (M2 exit gate); `uv run pytest -m unit tests/unit/application` — `Container.build` registers exactly 3 adapters (sorted) and fails startup on an invalid `models.yaml`; `/v1/models` lists only `active` models |
| Test dirs | `tests/contract/`, `tests/unit/application/` |

### M3 — Routing

#### T14 — feat/persistence-foundation
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M3-H · worktree `.claude/worktrees/t14/` · Merge order **1** · Size **L** |
| Depends on | M2 gate |
| Files | `sy/infrastructure/{db,redis_client}.py`, `sy/infrastructure/repositories/base.py`, `alembic.ini`, `sy/infrastructure/db/migrations/{env.py,script.py.mako,versions/0001_tenants.py}`, edit `sy/infrastructure/settings.py` (DB/Redis fields), `tests/unit/infrastructure/*`, `tests/integration/test_migrations.py`, `tests/integration/test_redis_client.py` |
| Covers | FR-110, FR-67 (tenant-scoped repo base), NFR-15 (partial) |
| Acceptance | `uv run alembic heads` → `0001 (head)`; `uv run pytest -m integration tests/integration/test_migrations.py` runs `upgrade head → downgrade base → upgrade head` on testcontainers PG; `sy_forbid_mutation()` + roles/grants present; `TenantScopedRepository` refuses a query without `tenant_id` (unit); `RedisClient` loads scripts via `SCRIPT LOAD` and reloads on `NOSCRIPT` (integration); `Settings` requires `DATABASE_URL`/`REDIS_URL` as `SecretStr` (repr hides value) |
| Test dirs | `tests/unit/infrastructure/`, `tests/integration/` |

#### T15 — feat/routing-strategies
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M3-H · worktree `.claude/worktrees/t15/` · Merge order **2** · Size **M** |
| Depends on | M2 gate (T10 matcher/pricing) |
| Files | `sy/domain/routing.py` (`RoutingStrategy`, `CandidateRanker`, `RoutePlanner`, `RouteDecision`), `sy/application/routing_service.py` (`RoutingService`), `tests/unit/domain/test_routing*.py`, `tests/unit/application/test_routing_service.py` |
| Covers | FR-28, FR-29, FR-30, FR-31, FR-32, FR-33, FR-34, FR-35, NFR-10, NFR-18 |
| Acceptance | `uv run pytest -m unit tests/unit/domain/test_routing*.py tests/unit/application/test_routing_service.py`: hypothesis property — 100 % of generated chains capability-compatible (FR-34); `cheapest_capable` order = ascending estimate, ties by model ID; `lowest_latency` uses EWMA α = 0.2 (OQ-06) with injected clock; `weighted` chi-square test on seeded RNG (10 000 draws, p > 0.01); no candidate → `NoEligibleModelError(reason=capability_mismatch)` → 400 vs all breakers open → 503 `no_healthy_candidate`; breaker health injected as a Protocol (no Redis import) |
| Test dirs | `tests/unit/domain/`, `tests/unit/application/` |

#### T16 — feat/policy-versioning
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M3-I · worktree `.claude/worktrees/t16/` · Size **L** · integrating task |
| Depends on | T14, T15 |
| Files | `sy/domain/policy.py`, `sy/application/policy_service.py`, `sy/infrastructure/repositories/policy_repository.py`, `sy/infrastructure/db/migrations/versions/0002_policies.py` (down 0001), `sy/cli/{__init__,main,policy}.py`, `config/policies/default.yaml`, edit `sy/application/container.py`, edit `sy/application/gateway_service.py` (policy resolve + route), `docs/adr/0010-policy-versioning.md` (+ README row), tests |
| Covers | FR-93, FR-94, FR-95, FR-96, FR-110, FR-109 (ADR-010), NFR-10 |
| Acceptance | `uv run alembic heads` → `0002`; `uv run switchyard policy apply config/policies/default.yaml --tenant default` creates version 1 and activates it (integration, testcontainers PG); invalid policy (unknown model, capability-incompatible chain, schema error) rejected with non-zero exit and active version unchanged; partial unique index allows one active version per tenant; DB unreachable at reload → gateway keeps last-known-good (unit, mocked repo); `GatewayService` puts `policy_version` on the lifecycle and route decision; e2e from T09 still green |
| Test dirs | `tests/unit/domain/`, `tests/unit/application/`, `tests/unit/cli/`, `tests/integration/` |

### M4 — Resilience

#### T17 — feat/retry-and-timeouts
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M4-J · worktree `.claude/worktrees/t17/` · Merge order **1** · Size **M** |
| Depends on | M3 gate (T14 `RedisClient`) |
| Files | `sy/application/retry.py` (`BackoffCalculator`), `sy/application/retry_budget.py` (`RetryBudget`), edit `sy/adapters/base.py` (timeout helpers: connect / first-token / idle / deadline), tests, `docs/adr/0004-error-taxonomy-retry.md` (+ README row) |
| Covers | FR-46, FR-48, FR-50, FR-51, FR-52, FR-53, FR-54, FR-55, FR-56, FR-57, FR-109 (ADR-004) |
| Acceptance | `uv run pytest -m unit tests/unit/application/test_retry*.py tests/unit/adapters/test_timeouts.py`: full-jitter backoff within [0, min(max, initial·2ⁿ)] with seeded RNG; no retry scheduled past `deadline_ms`; `Retry-After` > remaining deadline → fail over / fail fast; table test: 400/401/403/context-overflow/cancel never retried, 401/403 emit alert signal; retry budget trips at ratio > 0.2 over rolling window (fake Redis + injected clock) and emits metric; each timeout kind raises `ProviderTimeoutError(kind=…)` (respx delayed responses) |
| Test dirs | `tests/unit/application/`, `tests/unit/adapters/` |

#### T18 — feat/circuit-breaker
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M4-J · worktree `.claude/worktrees/t18/` · Merge order **2** · Size **M** |
| Depends on | M3 gate (T14 `RedisClient`) |
| Files | `sy/application/circuit_breaker.py`, `sy/infrastructure/lua/breaker.lua` (if used), `tests/unit/application/test_circuit_breaker.py`, `tests/integration/test_breaker_shared.py` |
| Covers | FR-58, FR-59 (health input to `RoutingService`) |
| Acceptance | unit: closed → open after 5 failures in 30 s, open → half-open after 15 s (injected clock), 2 probes → closed, probe failure → open; integration (real Redis): two `CircuitBreaker` instances share state (replica simulation); Redis down → breaker fails open-to-traffic (closed) and logs, never raises to caller (NFR-15); implements the health Protocol used by `RoutingService` |
| Test dirs | `tests/unit/application/`, `tests/integration/` |

#### T19 — feat/execution-orchestrator
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M4-K · worktree `.claude/worktrees/t19/` · Size **L** · integrating task |
| Depends on | T17, T18 |
| Files | edit `sy/application/execution_service.py`, edit `sy/application/container.py`, `docs/adr/0005-streaming-semantics.md` (+ README row), `tests/unit/application/test_execution_service*.py`, `tests/integration/test_cancellation.py` |
| Covers | FR-21, FR-40, FR-42, FR-43, FR-44, FR-45, FR-49, FR-60, FR-109 (ADR-005), NFR-04 |
| Acceptance | unit (mocked adapters, injected clock/RNG): retry/fallback only before first token; post-first-token failure → terminal `StreamError`, no provider switch; partial tool call streamed → no switch; `max_attempts` 3 / `max_fallbacks` 2 enforced; open breaker skips a model without an attempt; all candidates fail → typed 503 before `deadline_ms`; lifecycle invariants re-checked after every scenario; integration: client disconnect closes the fake_provider connection (server-side disconnect observed) and settles used tokens |
| Test dirs | `tests/unit/application/`, `tests/integration/` |

#### T20 — test/chaos-suite
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M4-L · worktree `.claude/worktrees/t20/` · Size **L** |
| Depends on | T19 |
| Files | `tests/chaos/*`, `docker-compose.chaos.yml` (toxiproxy), `.github/workflows/nightly.yml` |
| Covers | NFR-03, NFR-04, NFR-15 (Redis loss), FR-43/45/46 under fault |
| Acceptance | `docker compose -f docker-compose.yml -f docker-compose.chaos.yml up -d --wait` then `uv run pytest -m chaos`: ≥ 99.5 % success with 50 % retryable errors on primary (1 000 requests, seeded); correlated outage → typed 503 within `deadline_ms`; mid-stream drop → typed error event, no truncation without terminal event; toxiproxy latency → TTFT/idle timeouts fire; Redis stopped → requests still served (limits/breakers reset), no 5xx from Redis errors; `nightly.yml` runs the chaos job on cron; skip with explicit reason if Docker/toxiproxy absent |
| Test dirs | `tests/chaos/` |

### M5 — Security and tenancy

#### T21 — feat/tenant-auth
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M5-M · worktree `.claude/worktrees/t21/` · Merge order **1** · Size **L** · integrating task for group M |
| Depends on | M4 gate |
| Files | `sy/security/{api_keys,tenant_context}.py`, `sy/infrastructure/repositories/{tenant,api_key,audit}_repository.py`, `sy/infrastructure/db/migrations/versions/0003_api_keys_audit.py` (down 0002), `sy/cli/keys.py`, edit `sy/api/middleware.py` + `sy/api/deps.py`, edit `sy/application/gateway_service.py` + `container.py` (tenant context only), edit `sy/infrastructure/settings.py` (HMAC fields), `docs/adr/0008-tenant-isolation-api-keys.md` (+ README row), tests |
| Covers | FR-63, FR-64, FR-65, FR-66, FR-67, FR-22, FR-70 (HMAC secret via Secrets Manager / env backend), FR-109 (ADR-008) |
| Acceptance | `uv run alembic heads` → `0003`; unit: `ApiKeyHasher` HMAC-SHA-256 with `hmac_key_id`, constant-time compare, only prefix displayable; expired/revoked/unknown key → 401 before any service runs; integration: `switchyard keys create/rotate/revoke` writes `audit_events`, UPDATE/DELETE on `audit_events` rejected by trigger; every repository method takes `tenant_id` (AST test over `repositories/`); Secrets Manager client mocked (`MagicMock(spec=...)`), never called in tests; no raw key in logs (caplog) |
| Test dirs | `tests/unit/security/`, `tests/unit/infrastructure/`, `tests/integration/` |

#### T22 — feat/rate-limits
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M5-M · worktree `.claude/worktrees/t22/` · Merge order **2** · Size **M** · standalone, no wiring |
| Depends on | M4 gate |
| Files | `sy/application/admission_service.py`, `sy/infrastructure/lua/{token_bucket,concurrency}.lua`, `tests/unit/application/test_admission_service.py`, `tests/integration/test_rate_limits.py` |
| Covers | FR-68, FR-69, NFR-09 (single-node part) |
| Acceptance | unit: body / message-count / `max_tokens` / tool-payload limits → 400/413 with typed errors (OQ-05 defaults); RPM/TPM/concurrency exceed → `RateLimitedError` with `retry_after_s`; integration (real Redis, 3 `AdmissionService` instances = 3 replicas): admitted count within ±5 % of RPM over 60 s simulated clock; concurrency slot released on exception; Redis down → admit + log (degrade, NFR-15); S8 shows no edit to `gateway_service.py`/`container.py` |
| Test dirs | `tests/unit/application/`, `tests/integration/` |

#### T23 — feat/log-redaction
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M5-M · worktree `.claude/worktrees/t23/` · Merge order **3** · Size **M** · standalone, no wiring |
| Depends on | M4 gate |
| Files | `sy/security/redaction.py` (`Redactor`), `sy/infrastructure/logging.py` (JSON logging + redaction filter hook), `docs/security.md` (retention/deletion + STRIDE), `tests/unit/security/test_redaction.py`, `tests/unit/infrastructure/test_logging.py` |
| Covers | FR-71, FR-72, NFR-14 |
| Acceptance | unit: messages, tool arguments, tool results and `Authorization`/API-key patterns replaced by `[REDACTED]` by default; per-tenant opt-in flag leaves prompts unredacted but still masks keys; nested/structured log records handled; `docs/security.md` has STRIDE table per component + retention/deletion section; `uv run bandit -r src` clean |
| Test dirs | `tests/unit/security/`, `tests/unit/infrastructure/` |

#### T24 — test/tenant-isolation
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M5-N · worktree `.claude/worktrees/t24/` · Size **M** · integrating task (admission + redaction) |
| Depends on | T21, T22, T23 |
| Files | wire `AdmissionService` + `Redactor` into `sy/application/gateway_service.py` / `container.py` (+ `sy/api/app.py` logging setup if needed), `tests/security/*` |
| Covers | FR-73, NFR-08, FR-68/FR-71 end to end |
| Acceptance | `docker compose up -d --wait` then `uv run pytest -m security`: tenant A cannot read B's keys, policy, audit rows (and, as stubs failing to-spec until M6/M7, ledger, idempotency, cache — marked `xfail(strict=True, reason="lands in T25–T28")`); A's request with B's `Idempotency-Key`/`model` alias leaks nothing; rate limit of A does not consume B's bucket; captured logs contain no prompt text by default; 0 leaks |
| Test dirs | `tests/security/` |

### M6 — Cost governance

#### T25 — feat/budget-ledger
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M6-O · worktree `.claude/worktrees/t25/` · Merge order **1** · Size **L** · standalone |
| Depends on | M5 gate |
| Files | `sy/application/budget_service.py`, `sy/infrastructure/repositories/{budget,ledger}_repository.py`, `sy/infrastructure/db/migrations/versions/0004_budgets_ledger.py` (down 0003), `docs/adr/0006-postgres-only-budget.md` (+ README row), tests |
| Covers | FR-41, FR-61, FR-74, FR-75, FR-76, FR-77, FR-78, FR-79, FR-80, FR-81, NFR-05, FR-109 (ADR-006) |
| Acceptance | `uv run alembic heads` → `0004`; integration: 200 concurrent `reserve()` vs $1 limit → Σ committed + reserved ≤ $1 (0 overspend); settle twice → one ledger row (idempotent by `request_id`); late settlement after expiry appends `late_settlement` row; reservation transition trigger rejects illegal moves; ledger UPDATE/DELETE rejected; unit: reservation includes `max_attempts`; failed billable attempts included; no usage → `usage_source=estimated`; hard → `BudgetExceededError` (402), soft → allow + alert at 80 % (OQ-07) |
| Test dirs | `tests/unit/application/`, `tests/integration/` |

#### T26 — feat/idempotency-keys
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M6-O · worktree `.claude/worktrees/t26/` · Merge order **2** (re-point 0005 → 0004 in the squash commit) · Size **M** · standalone |
| Depends on | M5 gate |
| Files | `sy/application/idempotency_service.py`, `sy/infrastructure/repositories/idempotency_repository.py`, `sy/infrastructure/db/migrations/versions/0005_idempotency_keys.py` (down **0003** in worktree), tests |
| Covers | FR-83, FR-84, FR-85, FR-86, NFR-07 (service level) |
| Acceptance | in worktree: `alembic heads` → `0005`; integration: same key + same body → replay stored response; different body → `IdempotencyMismatchError` (422); in-progress (`locked_until` in future) → `IdempotencyConflictError` (409); 1 000 concurrent duplicates → exactly one `acquire` winner; records tenant-scoped. **After group merge on `main`:** `0005.down_revision == "0004"`, `uv run alembic heads` prints exactly one head, upgrade → downgrade → upgrade cycle green |
| Test dirs | `tests/unit/application/`, `tests/integration/` |

#### T27 — feat/maintenance-workers
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M6-P · worktree `.claude/worktrees/t27/` · Size **L** · integrating task (budget + idempotency) |
| Depends on | T25, T26 |
| Files | `sy/workers/{reservation_expiry,idempotency_cleanup,runner}.py`, wire `BudgetService` + `IdempotencyService` into `sy/application/gateway_service.py` / `container.py`, `tests/integration/test_crash_settlement.py`, `tests/unit/workers/*` |
| Covers | FR-82, FR-87, FR-84 (gateway replay), FR-41/FR-78 end to end, NFR-05, NFR-06, NFR-07 |
| Acceptance | integration: kill gateway mid-request (subprocess `SIGKILL`) → after TTL + one worker pass, 100 % reservations `committed` or `expired` (flag + metric + ledger marker); cleanup worker deletes only records past `expires_at` in batches of 500; 1 000 duplicate-key retries through HTTP → 0 double ledger rows; 200 concurrent HTTP requests vs $1 → 0 overspend; xfail markers for ledger/idempotency in `tests/security/` removed and passing |
| Test dirs | `tests/unit/workers/`, `tests/integration/`, `tests/security/` |

### M7 — Exact caching

#### T28 — feat/exact-cache
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M7-Q · worktree `.claude/worktrees/t28/` · Size **M** · integrating task |
| Depends on | M6 gate |
| Files | `sy/application/cache_service.py` (`CacheService`, `CacheKeyBuilder`), edit `gateway_service.py`, `container.py`, `sy/api/routes.py` (header), `docs/adr/0009-exact-cache.md` (+ README row), tests |
| Covers | FR-88, FR-89, FR-90, FR-91, FR-92, NFR-11, FR-109 (ADR-009) |
| Acceptance | unit: key includes all 12 FR-88 fields (changing any one changes the key; hypothesis); eligibility table (route flag, `temperature == 0`, no tool calls, non-stream or buffered) — 0 wrong hits; hit path `ADMITTED → CACHE_HIT → COMPLETED → SETTLED`, no adapter call; integration: `x-switchyard-cache` = hit/miss/bypass on every response; Redis down → `miss`, never error; values > 256 KiB not stored; cache xfail in `tests/security/` now passes; hit-rate benchmark script output recorded |
| Test dirs | `tests/unit/application/`, `tests/integration/`, `tests/security/` |

### M8 — Observability

#### T29 — feat/observability
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M8-R · worktree `.claude/worktrees/t29/` · Size **L** · integrating task |
| Depends on | M7 gate |
| Files | `sy/infrastructure/telemetry.py` (`Telemetry`), span/metric edits across services, `infra/otel/collector.yaml` (Tempo + Prometheus exporters), `dashboards/*.json`, `infra/alerts/*.yaml`, tests |
| Covers | FR-97, FR-98, FR-99, FR-100, FR-101, NFR-16 |
| Acceptance | unit with `InMemorySpanExporter`: one root span per request + one child per attempt carrying all FR-97 attributes; ledger row `trace_id` = span trace ID; metrics (in-memory reader) for every FR-98 series; `promtool check rules infra/alerts/*.yaml` passes and covers the 6 FR-100 alerts; dashboards JSON valid; demo: one trace answers "why did X cost $Y and take Z s" (attempts, fallback reason, usage, cost, policy_version) |
| Test dirs | `tests/unit/infrastructure/`, `tests/integration/` |

### M9 — Deployment

#### T30 — feat/graceful-shutdown
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M9-S · worktree `.claude/worktrees/t30/` · Merge order **1** · Size **M** |
| Depends on | M8 gate |
| Files | edit `sy/api/app.py` (lifespan drain), edit `sy/api/sse.py`, tests |
| Covers | FR-107, NFR-12 |
| Acceptance | integration: start uvicorn subprocess, open 20 SSE streams on slow fake_provider, send SIGTERM → `/readyz` 503 immediately, new requests refused, all 20 streams end with terminal event (0 truncated), exit within drain timeout |
| Test dirs | `tests/integration/` |

#### T31 — chore/terraform-infra
| Field | Value |
|---|---|
| Group | PARALLEL-GROUP-M9-S · worktree `.claude/worktrees/t31/` · Merge order **2** · Size **L** |
| Depends on | M8 gate |
| Files | `infra/terraform/**` |
| Covers | FR-105, FR-70 (Secrets Manager resources) |
| Acceptance | `terraform fmt -check -recursive`, `terraform init -backend=false && terraform validate` per env, `tflint`, `checkov`/`tfsec` no HIGH; region variable defaults to `us-east-1` (OQ-08); no secret values in `.tf`/`.tfvars`; **`terraform apply` is manual (user)** |
| Test dirs | none (static checks) |

#### T32 — chore/cd-pipeline
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M9-T · worktree `.claude/worktrees/t32/` · Size **M** |
| Depends on | T31 (and T30) |
| Files | `.github/workflows/{cd,smoke}.yml` |
| Covers | FR-106 |
| Acceptance | `actionlint` clean; cd: build → push → staging deploy → smoke → manual approval → prod; rollback job redeploys previous ECS task def and re-activates last-known-good policy; smoke: nightly cron, live provider calls gated on secrets (manual); OIDC role, no long-lived keys |
| Test dirs | none |

### M10 — Hardening and demo

#### T33 — chore/loadtest-and-docs
| Field | Value |
|---|---|
| Group | SEQUENTIAL-M10-U · worktree `.claude/worktrees/t33/` · Size **L** |
| Depends on | M9 gate |
| Files | `loadtest/**` (k6), `docs/{architecture,failure-modes}.md`, `docs/runbooks/*`, `README.md` |
| Covers | FR-108, NFR-01, NFR-02, NFR-13, all §15 targets (re-run) |
| Acceptance | `k6 run loadtest/overhead.js` (200 VUs, fake provider 300 ms) → overhead p95 < 15 ms; `loadtest/ttft.js` → added TTFT p95 < 10 ms; rate-limit run on 3 replicas ±5 %; chaos + security + integration suites green; 5 runbooks present; `failure-modes.md` covers Redis loss (NFR-15); README demo steps run from a clean clone |
| Test dirs | `loadtest/`, all `tests/` |

## 4. Milestone exit-gate checklist (stop for user confirmation after each)
| Gate | Groups merged | Must be true | Verify with |
|---|---|---|---|
| M0 | A, B | CI green; `/healthz` up; old code gone | `ci.yml` jobs green locally (`act` or same commands); `docker compose up -d --wait`; `curl -fsS localhost:8080/healthz` |
| M1 | C, D, E | OpenAI SDK streams a tool-call conversation; lifecycle invariant tests pass | `pytest -m integration tests/integration/test_openai_sdk_e2e.py`; `pytest tests/unit/domain/test_lifecycle_properties.py` |
| M2 | F, G | same contract suite passes on all 3 providers; registry completeness test green; user confirms model IDs (OQ-01) | `pytest -m contract tests/contract/test_all_providers.py`; `pytest tests/unit/test_registry_completeness.py` |
| M3 | H, I | 100 % fallbacks capability-compatible; policy apply/validate/LKG works; `alembic heads` = 1 | routing property tests; `switchyard policy apply` integration test |
| M4 | J, K, L | chaos suite passes (≥ 99.5 %, typed 503, cancel closes provider conn) | `pytest -m chaos` with chaos compose override |
| M5 | M, N | cross-tenant negative tests pass (0 leaks); rate limit ±5 %; no prompts/keys in logs | `pytest -m security`; `pytest tests/integration/test_rate_limits.py` |
| M6 | O, P | 0 overspend at 200 concurrent vs $1; crash test settles 100 %; 0 double bills / 1 000 dup keys; one Alembic head | `pytest -m integration tests/integration/test_crash_settlement.py`; `alembic heads` |
| M7 | Q | 0 wrong cache hits; hit-rate benchmark recorded; cache isolation test green | `pytest -m "unit or integration or security" -k cache` |
| M8 | R | "why did X cost $Y" answered from one trace; alerts lint | span tests; `promtool check rules` |
| M9 | S, T | `terraform validate` clean (apply from zero done manually by user); 0 truncated streams on SIGTERM; CD/rollback workflows lint | graceful-shutdown test; `actionlint`; user confirms manual apply |
| M10 | U | every §15 target met (NFR-01..12); NFR-17 quality targets; runbooks + README | k6 reports; `metrics` skill → `metrics.md` score ≥ 80 |

Per gate also: Code Reviewer verdict APPROVE with risk ≤ MEDIUM (HIGH → human), `metrics.md` refreshed, worktrees removed.

## 5. Progress tracking
| Milestone | Tasks | Status | Notes |
|---|---|---|---|
| M0 | T01, T02, T03, T04 | in progress | T01 done in worktree t01 (awaiting merge); actionlint not run (not installed); import-linter layer modules not yet created are marked optional `(…)` in pyproject ; T03 done in worktree t03 (awaiting merge order 1): pyproject `[tool.pytest.ini_options] pythonpath = ["."]` added so top-level fake_provider imports; docker build not run (Docker not installed) |
| M1 | T05, T06, T07, T08, T09 | pending | |
| M2 | T10, T11, T12, T13 | pending | |
| M3 | T14, T15, T16 | pending | |
| M4 | T17, T18, T19, T20 | pending | |
| M5 | T21, T22, T23, T24 | pending | |
| M6 | T25, T26, T27 | pending | 0005 re-point at group-O merge |
| M7 | T28 | pending | |
| M8 | T29 | pending | |
| M9 | T30, T31, T32 | pending | `terraform apply` manual |
| M10 | T33 | pending | |
