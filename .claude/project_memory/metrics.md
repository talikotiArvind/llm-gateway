# Project Metrics

Auto-updated by hooks and the `metrics` skill. **Do not edit manually.**
Reset by `session_metrics.py` at the start of each session (session counters only).

---

## Token Efficiency (current session)
index_hits: 0
full_reads: 0
indexed_reads_proceeded: 0
files_written_this_session: 2

> **How to read this:**
> - Suggested index opportunities: `index_hits`
> - Indexed reads still opened: `indexed_reads_proceeded`
> - True skips: `index_hits - indexed_reads_proceeded`
> - True skip efficiency: `true_skips / (true_skips + full_reads)` = token efficiency %.
> Target: >70% true skip efficiency. Low ratio = stale index or agents ignoring guard.

---

## Code Quality (last `metrics` skill run)
ruff_violations: 0
mypy_errors: 0  (strict; src tests fake_provider, 35 files)
annotation_coverage_pct: 99.6 (line 100%, 548 stmts; switchyard + fake_provider)
avg_complexity: 2.35 (radon A; no function graded C or worse)
max_complexity_function: none above B
files_checked: 35
quality_score: 99.7/100 (M0 gate, 2026-11-05)

> Run `.claude/skills/metrics.md` after any code change to refresh these.

---

## Test Quality (last pytest run)
coverage_pct: 99.83 (line 100; switchyard + fake_provider, 501 stmts)
total_tests: 173 (+78 subtests)
passing_tests: 173
failing_tests: 0
branches_covered_pct: 98.0 (96/98)
uncovered_lines: 0
last_run: 2026-11-05 (M0 exit gate)

> Run `pytest --cov=src --cov-report=json` and then the `metrics` skill to refresh.

---

## Review History (cumulative)
total_review_iterations: 2
issues_resolved: 14
issues_rejected: 6
avg_iterations_to_resolve: 1

---

## Sub-Agent Parallelism (last session)
parallel_task_groups_run: 2 (M0-B; M0 unit tests)
tasks_parallelized: 5 (T02, T03, T04, 2 unit-test agents)
sequential_tasks: 3 (T01, M0 refactor, fake_provider spec fix)
