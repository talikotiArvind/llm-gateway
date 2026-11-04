# Claude Workflow Directory

This folder contains the Claude Code workflow configuration for this repository.

## Quick Start
1. Read `CLAUDE.md` to understand the end-to-end pipeline and quality targets.
2. Start with `architect` for new work, then run `system-designer`, `planner`, `coding-agent`, `code-reviewer`, `code-refactor` (if needed), `unit-test`, `metrics`, `mkdocs-agent`, and finally `cleaner`.
3. Read `.claude/project_memory/code_index.md` before reading source files.

## Folder Layout
- `agents/` — role-specific instructions for each pipeline stage.
- `skills/` — reusable quality and analysis skills (linter, annotations, metrics, etc.).
- `hooks/` — automation for index updates, read guarding, review context, and session metrics.
- `project_memory/` — durable artifacts: requirements, design, implementation plans, review logs, and metrics.
- `settings.json` — active hook wiring.
- `settings.local.json` — local permissions overrides (portable template).

## Hook Troubleshooting
- `session_metrics.py` (SessionStart): initializes/prints status panel.
- `guard_file_reads.py` (PreToolUse/Read): injects index summaries to reduce source reads.
- `update_code_index.py` (PostToolUse/Edit|Write): refreshes signature index entries.
- `track_full_reads.py` (PostToolUse/Read): records full-read counters and indexed-read correlations.

If hooks are not firing:
1. Validate `.claude/settings.json` matcher entries.
2. Run `python .claude/hooks/validate_pipeline.py`.
3. Confirm `.claude/project_memory/metrics.md` and `code_index.md` exist and are writable.

## First-Run Sanity Checks
```bash
python .claude/hooks/session_metrics.py </dev/null || true
python .claude/hooks/validate_pipeline.py
```

## Conventions
- Use `PARALLEL-GROUP-*` labels consistently in plans.
- Use `test/` as the test directory for new tests; it runs in CI via `test/unit_test.sh`.
- Keep `.claude/settings.local.json` machine-agnostic (repo-relative paths only).
