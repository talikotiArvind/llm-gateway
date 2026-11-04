# Project Metrics

Auto-updated by hooks and the `metrics` skill. **Do not edit manually.**
Reset by `session_metrics.py` at the start of each session (session counters only).

---

## Token Efficiency (current session)
index_hits: 0
full_reads: 0
indexed_reads_proceeded: 0
files_written_this_session: 0

> **How to read this:**
> - Suggested index opportunities: `index_hits`
> - Indexed reads still opened: `indexed_reads_proceeded`
> - True skips: `index_hits - indexed_reads_proceeded`
> - True skip efficiency: `true_skips / (true_skips + full_reads)` = token efficiency %.
> Target: >70% true skip efficiency. Low ratio = stale index or agents ignoring guard.

---

## Code Quality (last `metrics` skill run)
ruff_violations: —
mypy_errors: —
annotation_coverage_pct: —
avg_complexity: —
max_complexity_function: —
files_checked: —
quality_score: —

> Run `.claude/skills/metrics.md` after any code change to refresh these.

---

## Test Quality (last pytest run)
coverage_pct: —
total_tests: —
passing_tests: —
failing_tests: —
branches_covered_pct: —
uncovered_lines: —
last_run: —

> Run `pytest --cov=src --cov-report=json` and then the `metrics` skill to refresh.

---

## Review History (cumulative)
total_review_iterations: 0
issues_resolved: 0
issues_rejected: 0
avg_iterations_to_resolve: —

---

## Sub-Agent Parallelism (last session)
parallel_task_groups_run: 0
tasks_parallelized: 0
sequential_tasks: 0
