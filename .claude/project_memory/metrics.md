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
mypy_errors: 0  (strict; src tests fake_provider, 34 files)
annotation_coverage_pct: 100  (switchyard + fake_provider)
avg_complexity: —
max_complexity_function: —
files_checked: 34
quality_score: —

> Run `.claude/skills/metrics.md` after any code change to refresh these.

---

## Test Quality (last pytest run)
coverage_pct: 99.83 (line 100; switchyard + fake_provider, 501 stmts)
total_tests: 86 (+8 subtests)
passing_tests: 86
failing_tests: 0
branches_covered_pct: 98.75 (79/80)
uncovered_lines: 0
last_run: 2026-11-05 (M0 review iteration 2)

> Run `pytest --cov=src --cov-report=json` and then the `metrics` skill to refresh.

---

## Review History (cumulative)
total_review_iterations: 2
issues_resolved: 14
issues_rejected: 6
avg_iterations_to_resolve: 1

---

## Sub-Agent Parallelism (last session)
parallel_task_groups_run: 0
tasks_parallelized: 0
sequential_tasks: 0
