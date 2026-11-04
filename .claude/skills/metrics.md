---
name: metrics
description: Run code quality and test quality checks, then write scores to project_memory/metrics.md. Use after coding or test writing to get objective numbers.
---

Apply this skill to measure and record objective quality scores for the project.
Run this after any significant code or test changes.
Required tools: `ruff`, `mypy`, `pytest`, `pytest-cov`, `radon` (optional but recommended), `mkdocs`.
Install with `pip install -r requirements-dev.txt`.

## Step 0 — Detect Project Roots (path-aware)

```bash
# Prefer src/ + test/, then package root fallback
SOURCE_ROOT=$(python -c "from pathlib import Path; print('src' if Path('src').exists() else '.')")
TEST_ROOT=$(python -c "from pathlib import Path; print('test' if Path('test').exists() else 'test')")
echo "Using SOURCE_ROOT=$SOURCE_ROOT TEST_ROOT=$TEST_ROOT"
```

## Step 1 — Code Quality Metrics

Run all tools in parallel (independent checks):

**Ruff violations:**
```bash
ruff check \"$SOURCE_ROOT\" --statistics --output-format=json 2>/dev/null | python -c "
import json, sys
data = json.load(sys.stdin)
total = sum(item.get('count', 1) for item in data) if isinstance(data, list) else 0
print(f'ruff_violations: {total}')
" 2>/dev/null || echo "ruff_violations: (ruff not installed)"
```

**Mypy errors:**
```bash
mypy \"$SOURCE_ROOT\" --strict --ignore-missing-imports --no-error-summary 2>/dev/null | \
  grep -c "^${SOURCE_ROOT}/" || echo "0"
# Output: N (count of error lines)
```

**Annotation coverage (% of functions with return types):**
```bash
python -c "
import ast, pathlib
total, annotated = 0, 0
source_root = pathlib.Path('${SOURCE_ROOT}')
for path in source_root.rglob('*.py'):
    try:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                if node.returns:
                    annotated += 1
    except Exception:
        pass
pct = round(annotated/total*100) if total > 0 else 0
print(f'{pct}% ({annotated}/{total} functions annotated)')
"
```

**Cyclomatic complexity (requires radon):**
```bash
radon cc \"$SOURCE_ROOT\" -a -s 2>/dev/null | tail -1 || echo "(radon not installed — pip install radon)"
# Output: Average complexity: A (1.5)
```

## Step 2 — Test Quality Metrics

```bash
# Run pytest with coverage JSON output
pytest \"$TEST_ROOT\" --cov=\"$SOURCE_ROOT\" --cov-report=json --cov-report=term-missing -q 2>/dev/null
```

Extract from `coverage.json`:
```bash
python -c "
import json, pathlib
try:
    data = json.loads(pathlib.Path('coverage.json').read_text())
    totals = data.get('totals', {})
    print(f'coverage_pct: {round(totals.get(\"percent_covered\", 0), 1)}%')
    print(f'branches_covered_pct: {round(totals.get(\"percent_covered_branches\", 0), 1) if \"percent_covered_branches\" in totals else \"n/a\"}%')
    missing = totals.get('missing_lines', 0)
    print(f'uncovered_lines: {missing}')
except Exception:
    print('coverage_pct: (run pytest --cov=<source_root> --cov-report=json first)')
"
```

Extract test counts from pytest output:
```bash
pytest \"$TEST_ROOT\" -q --no-header 2>/dev/null | tail -2
# Output: X passed, Y failed in Zs
```

## Step 3 — Compute Quality Score

Compute an overall quality score (0–100):

```
quality_score = (
    (100 - min(ruff_violations, 50)) * 0.20 +   # 20% weight: style/bugs
    (100 - min(mypy_errors * 5, 50)) * 0.20 +    # 20% weight: type safety
    annotation_coverage_pct * 0.20 +              # 20% weight: annotation completeness
    (100 if avg_complexity <= 5 else 70 if avg_complexity <= 10 else 40) * 0.10 + # 10%: complexity
    coverage_pct * 0.30                           # 30% weight: test coverage
)
```

## Step 4 — Write to metrics.md

Update `.claude/project_memory/metrics.md` with all collected values.
Use the exact key names defined in that file so the session hook can read them.

Keys to update:
- `ruff_violations`, `mypy_errors`, `annotation_coverage_pct`, `avg_complexity`
- `max_complexity_function`, `files_checked`, `quality_score`
- `coverage_pct`, `total_tests`, `passing_tests`, `failing_tests`
- `branches_covered_pct`, `uncovered_lines`, `last_run`

## Step 5 — Report

Output a summary table:

```
## Metrics Report — [timestamp]

| Metric                  | Value   | Target  | Status |
|-------------------------|---------|---------|--------|
| Ruff violations         | N       | 0       | ✓/✗    |
| Mypy errors             | N       | 0       | ✓/✗    |
| Annotation coverage     | N%      | 100%    | ✓/✗    |
| Avg complexity          | N       | ≤5      | ✓/✗    |
| Test coverage           | N%      | ≥80%    | ✓/✗    |
| Branch coverage         | N%      | ≥75%    | ✓/✗    |
| Overall quality score   | N/100   | ≥80     | ✓/✗    |
```

Flag any metric below target as a priority fix. Pass the report to the coding agent if score < 80.

On Windows, execute this skill in Git Bash/WSL, or convert shell variables and pipes to PowerShell equivalents.
