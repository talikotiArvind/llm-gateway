# Python Project — Agent Workflow

## Agent Pipeline
```
User Input → Architect → System Designer → Planner
                                              ↓
                              ┌─────────────────────────────────────────────────────────────┐
                              │  Coding Agent (parallel ×N)                                 │
                              │  [PARALLEL-GROUP tasks]                                     │
                              │  + skills: linter / code-structure / annotations / security-check │
                              └─────────────────────────────────────────────────────────────┘
                                              ↓
                              Code Reviewer ←→ Code Refactor (max 3 iter)
                                              ↓
                              ┌──────────────────────────────┐
                              │  Unit Test Agent (parallel)  │
                              │  [one per module]             │
                              └──────────────────────────────┘
                                              ↓
                                       metrics skill
                                              ↓
                                      MkDocs Agent
                                    (build static site)
                                              ↓
                                         Cleaner
                                  (delete __pycache__ etc.)
```

## Failure Recovery (Stage-by-Stage)
- **Architect**: if requirements are incomplete, ask a single consolidated clarification round, then rewrite `requirements.md`.
- **System Designer**: if layering conflicts appear, record rejected alternatives in `decisions.md`, revise interfaces, and re-run planner.
- **Planner**: if dependencies are ambiguous, split into smaller sequential tasks and mark blocked items explicitly.
- **Coding Agent**: if read budget is exhausted, narrow task scope and spawn a second coding-agent instance for independent files.
- **Parallel-group merge**: if two worktrees touch the same shared file (e.g. `code_index.md`, `metrics.md`) on merge, stop and resolve the conflict explicitly — never let the later merge silently overwrite the earlier one. `code_index.md` merges by file-path section; `metrics.md`'s integer counters must be summed across worktrees, not taken from either copy (see `.claude/agents/coding-agent.md`).
- **Code Reviewer**: if objective metrics cannot run, report the exact tool/dependency gap and issue a conditional review. If risk is HIGH, say so even on APPROVE — do not let a clean metrics run imply it's safe to auto-proceed.
- **Code Refactor**: if critical issues cannot be safely fixed in 3 iterations, escalate to manual review and list unresolved FILE:LINE items.
- **Unit Test Agent**: if flaky/environment-sensitive tests appear, skip explicitly with reason and isolate deterministic coverage paths. If the implementation diverges from `requirements.md`/`design.md`, write the test to the spec (let it fail) and report the divergence to Code Reviewer as MAJOR — never adjust the assertion to match the implementation.
- **metrics skill**: if a tool is missing, log the missing tool, keep available metrics, and mark score as partial.
- **MkDocs Agent**: if `mkdocs build --strict` fails, fix nav/docstring reference errors and rerun until strict build passes.
- **Cleaner**: if deletion fails due to file locks, report locked paths and continue with non-blocked artefacts.

## Git Workflow Conventions
- Branch naming:
  - `feat/<short-name>` for features
  - `fix/<short-name>` for bug fixes
  - `chore/<short-name>` for tooling/docs
- Open PRs against `main`.
- Prefer squash merge for linear history unless preserving commit granularity is required.
- Run `python .claude/hooks/prep_review_context.py --base HEAD~1` before review to keep diff context consistent.
- **Risk gate**: only merge automatically when Code Reviewer's latest recommendation is APPROVE AND risk
  is LOW or MEDIUM. A HIGH risk verdict blocks automatic merge regardless of approval — get explicit
  human confirmation first.

## Coding-Agent 15 Guideline Summary
The coding agent enforces 15 structural rules from `.claude/agents/coding-agent.md`, including:
1. strict four-layer separation, 2. abstraction reuse-first, 3. class-oriented flows, 4. single responsibility boundaries,
5. typed constructors/factories, 6. fail-fast input validation, 7. deterministic outputs, 8. strict naming conventions,
9. typed models across boundaries, 10. safe mutable defaults, 11. high-signal comments only, 12. helper decomposition,
13. lazy heavy imports when justified, 14. reuse established execution patterns, 15. preserve subsystem-local style.

## Token Efficiency — READ THIS FIRST
**ALWAYS read `.claude/project_memory/code_index.md` before reading any source file.**
The hook `guard_file_reads.py` enforces this — it injects the index summary before every
`Read` of an indexed `.py` file. If the summary is enough, skip the Read.

**For code review:** run `python .claude/hooks/prep_review_context.py` — packages
git diff + index sections into one file, replacing N individual file reads with 1.

## Token Budget per Agent
| Agent | Max full file reads |
|-------|---------------------|
| Coding Agent | 3 |
| Code Reviewer | 2 |
| Code Refactor | 3 |
| Unit Test | 1 (module under test only) |
| MkDocs Agent | 2 (index + design.md sufficient for most pages) |
| Cleaner | 0 (no source reads — filesystem operations only) |

## Active Hooks
| Hook | Event | What it does |
|------|-------|-------------|
| `session_metrics.py` | SessionStart | Status panel + reset session counters |
| `guard_file_reads.py` | PreToolUse/Read | Injects index summary via `additionalContext` JSON |
| `update_code_index.py` | PostToolUse/Edit+Write | AST-extracts signatures → updates index (async) |
| `track_full_reads.py` | PostToolUse/Read | Counts full reads for efficiency ratio |

## Project Memory Structure
| File | Written by | Purpose |
|------|-----------|---------|
| `requirements.md` | Architect | Captured requirements |
| `design.md` | System Designer | Layered module design + decisions |
| `implementation_plan.md` | Planner | Tasks with parallel group labels |
| `code_index.md` | Hook (auto) | Module signatures index |
| `review_context.md` | `prep_review_context.py` | Compact diff + index for reviewer |
| `review_log.md` | Reviewer | Review history with objective metrics |
| `decisions.md` | System Designer | Architecture decision log |
| `metrics.md` | metrics skill + hooks | Quality scores + token efficiency |

## Parallelism
The Planner marks tasks with `PARALLEL-GROUP-X` labels.
Tasks in the same group have no shared outputs and no inter-dependencies.
Invoke `coding-agent` or `unit-test` once per group task simultaneously.

**Worktree isolation is mandatory for every parallel-group task.** "No shared outputs" is a planning
assumption, not a runtime guarantee — a shared working tree still lets two simultaneous agents silently
overwrite each other's edits (last-writer-wins) even when their target files differ, because index
updates, `metrics.md`, and other shared project-memory files are written by every agent regardless of
task. Each task in a `PARALLEL-GROUP-X` runs in its own git worktree under `.claude/worktrees/<task-id>/`
(spawn with `Agent(isolation: "worktree")` or an explicit `git worktree add`). No parallel task merges
itself — the group is merged explicitly, one task at a time, only after every task in the group has
reported completion. See `.claude/agents/planner.md` and `.claude/agents/coding-agent.md` for the
worktree assignment and merge protocol.

## Stage Acceptance Criteria (Required Before Handoff)
| Stage | Required outputs before next stage |
|-------|------------------------------------|
| Architect | `.claude/project_memory/requirements.md` created and user-confirmed |
| System Designer | `.claude/project_memory/design.md` updated + decision entries appended to `decisions.md` |
| Planner | `.claude/project_memory/implementation_plan.md` includes task IDs, dependencies, and `PARALLEL-GROUP-*` labels |
| Coding Agent | Task implementation complete, relevant files updated, linter + code-structure + annotations + security-check skills run, and — if part of a `PARALLEL-GROUP-*` — implemented in its own worktree and merged explicitly with no conflicting overwrite |
| Code Reviewer | `.claude/project_memory/review_log.md` appended with metrics + recommendation + risk level (LOW/MEDIUM/HIGH) |
| Code Refactor | Refactor evaluation logged + accepted changes applied (or explicit rejection reasoning); if risk is still HIGH after refactor, escalated to human instead of declared done |
| Unit Test | `tests/` coverage-added/updated for changed modules, deterministic test behavior verified, and expected behavior derived from `requirements.md`/`design.md` before reading the implementation (spec divergence, if any, reported — not silently matched) |
| metrics skill | `.claude/project_memory/metrics.md` refreshed with current quality values |
| MkDocs Agent | `mkdocs build --strict` passes and docs output is generated |
| Cleaner | Artefact cleanup summary printed (`Deleted N items...` or tidy message) |

## Quality Targets
| Metric | Target |
|--------|--------|
| Ruff violations | 0 |
| Mypy errors | 0 |
| Annotation coverage | 100% |
| Avg cyclomatic complexity | ≤5 |
| Test line coverage | ≥80% |
| Test branch coverage | ≥75% |
| Token efficiency (index hits) | ≥70% |
| Overall quality score | ≥80/100 |

---

## Practical Conventions — Quick Reference

Every agent and skill in this project follows these rules. No exceptions.

### Architecture
- Keep architecture in four layers: **data access → service logic → orchestration → API surface**
- Never skip a layer. Never mix concerns across layers.
- Reuse existing abstractions before adding raw infrastructure code.
- Prefer class-based, typed, explicit designs over loose dict-driven code.

### Code
- Validate early — raise at construction or method entry on invalid input. Fail fast.
- Make outputs deterministic: sort intentionally, deduplicate explicitly, cap result sizes.
- Match surrounding module style rather than forcing a new one across the codebase.
- Keep comments minimal — only for non-obvious logic, operational constraints, or architectural decisions.
- Use lazy imports when import-time side effects or circular dependencies are a risk.

### Naming
- `snake_case` → functions, methods, variables, fields
- `PascalCase` → classes
- `UPPER_CASE` → constants
- `_snake_case` → private attributes/methods

### Data
- Use typed models (`@dataclass` or `pydantic.BaseModel`) for all structured data crossing layer boundaries.
- Never pass raw untyped dicts between services.
- Use `field(default_factory=list)` — never bare `[]` as a default.

### Testing
- **Framework: `unittest`** (`unittest.TestCase` subclasses)
- **Runner: `pytest`** (for discovery + coverage)
- **Mocking tools**: `@patch`, `patch.object`, `MagicMock(spec=...)`, `SimpleNamespace`, `PropertyMock`
- **Blind maker-checker**: derive expected behavior from `requirements.md`/`design.md` before reading the
  implementation under test. The source is a reference for signatures/mocking, never for what a test
  should assert. If the implementation contradicts the spec, write the test to the spec (it fails) and
  report the divergence — do not let the implementation quietly redefine "correct."
- Patch dependencies where the code under test looks them up — not where they are defined.
- Mock all external systems: storage, APIs, search, network, logging, expensive services.
- Test behavior, transformations, ordering, fallbacks, and validation failures.
- Keep tests deterministic — mock time, random, and environment.
- Stub env/config before import when modules have import-time side effects.
- Use shared base test classes for repeated behavioral contracts.
- Skip explicitly with a reason — never let flaky tests run nondeterministically.

---

## Available Agents
- `architect` — Requirements gathering (start here for new projects)
- `system-designer` — Layered module design and interface contracts
- `planner` — Task breakdown with explicit parallel groups
- `coding-agent` — OOP code writing with full 15-guideline enforcement (parallelizable)
- `code-reviewer` — Senior review with objective ruff/mypy/coverage metrics
- `code-refactor` — Smart refactoring with debate (max 3 iterations)
- `unit-test` — unittest + pytest-cov, 80% coverage (parallelizable by module)
- `mkdocs-agent` — Generates MkDocs site from docstrings + project memory; runs `mkdocs build --strict`
- `cleaner` — Deletes `__pycache__`, `.pyc`, `.pytest_cache`, `htmlcov`, `site/`, and other build artefacts

## Available Skills
- `linter` — ruff + mypy
- `code-structure` — Layer, factory, naming, determinism, typing validation (15 guidelines)
- `annotations` — Type annotation enforcement
- `metrics` — Code quality + test quality scores → writes to `metrics.md`
- `security-check` — bandit scan + OWASP manual checklist + pip-audit; run after coding
- `vault` — Query and write notes to the Obsidian Second Brain vault; use before design and after agent output
