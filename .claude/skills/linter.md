---
name: linter
description: Run Python linting tools (ruff + mypy) on a file or directory and fix reported issues.
---

Apply this skill when asked to lint Python code or after any code is written.

## Steps

**1. Run ruff for style and correctness:**
```bash
ruff check {file_or_dir} --fix
ruff format {file_or_dir}
```

**2. Run mypy for type checking:**
```bash
mypy {file_or_dir} --strict --ignore-missing-imports
```

**3. Fix issues found:**

For `ruff` violations that are not auto-fixed, fix them manually:
- `E501` (line too long) — break the line logically
- `F401` (unused import) — remove it unless it's a re-export
- `B006` (mutable default argument) — replace with `None` + guard
- `C901` (complexity) — split the function

For `mypy` errors:
- Missing return type → add annotation
- `Any` type → narrow to a specific type
- Optional not handled → add None check or `assert x is not None`

**4. Report:**
After fixing, list what was changed. If issues remain that require design changes (not just annotation fixes), flag them for the coding agent.

## Tools setup (if not installed)
```bash
pip install ruff mypy
```

## Common ruff rule reference
| Code | Meaning |
|------|---------|
| E | PEP 8 style |
| F | Pyflakes (unused, undefined) |
| B | Bugbear (common bugs) |
| I | isort (import order) |
| C | McCabe complexity |
| N | Naming conventions |
