"""Review context packager — run ONCE at the start of a code review session.

Instead of agents reading multiple files individually (expensive),
this script generates a single compact context file containing:
  1. Git diff of only changed Python files
  2. Code index sections for only those changed files
  3. Stats: lines changed, files affected, index coverage

Usage:
    python .claude/hooks/prep_review_context.py [--base HEAD~1] [--output .claude/project_memory/review_context.md]

Output: .claude/project_memory/review_context.md
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from _hook_utils import normalize_path

INDEX_PATH = Path(".claude/project_memory/code_index.md")
REVIEW_LOG_PATH = Path(".claude/project_memory/review_log.md")
DEFAULT_OUTPUT = Path(".claude/project_memory/review_context.md")
MARKER_START_PATTERN = re.compile(r"<!-- BEGIN: (.+?) -->")
MARKER_END_PATTERN = re.compile(r"<!-- END: (.+?) -->")

# Path-segment -> CLAUDE.md four-layer name. Best-effort heuristic, not a parser
# of design.md (design.md is transient — only exists mid-feature).
LAYER_MARKERS: dict[str, str] = {
    "resource": "resource (data access)",
    "infrastructure": "resource (data access)",
    "repository": "resource (data access)",
    "app": "app (service logic)",
    "domain": "app (service logic)",
    "service": "app (service logic)",
    "orchestration": "orchestration (steps)",
    "pipeline": "orchestration (steps)",
    "api": "api (surface)",
    "routes": "api (surface)",
    "cli": "api (surface)",
}
HIGH_RISK_MARKERS = {"auth", "payment", "secret", "credential", "a2a"}


def run(cmd: list[str], timeout_s: int = 10) -> tuple[str, str, int]:
    """Run a shell command and return (stdout, stderr, returncode).

    Args:
        cmd (list[str]): Command and arguments to execute.
        timeout_s (int): Timeout in seconds before the command is aborted.

    Returns:
        tuple[str, str, int]: Captured stdout, stderr, and return code. On
        timeout, returns empty stdout, an error message, and code 124.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout_s}s: {' '.join(cmd)}", 124


def get_changed_files(base: str) -> list[str]:
    """Get list of changed Python files since base commit.

    Falls back to staged changes (``git diff --cached``) if the base-to-HEAD
    diff fails or is empty, to support pre-commit scenarios.

    Args:
        base (str): Git ref to diff against (e.g. ``"HEAD~1"``).

    Returns:
        list[str]: Paths of changed ``.py`` files.
    """
    stdout, stderr, code = run(["git", "diff", base, "HEAD", "--name-only"])
    if code != 0 or not stdout.strip():
        # Fallback: try staged changes (pre-commit scenario)
        if code != 0 and stderr.strip():
            print(f"[prep_review_context] git diff error: {stderr.strip()}", file=sys.stderr)
        stdout, stderr, _ = run(["git", "diff", "--cached", "--name-only"])
    if not stdout.strip():
        return []
    return [f for f in stdout.strip().splitlines() if f.endswith(".py")]


def get_diff(base: str) -> str:
    """Get full git diff for Python files.

    Falls back to staged changes (``git diff --cached``) if the base-to-HEAD
    diff fails or is empty.

    Args:
        base (str): Git ref to diff against (e.g. ``"HEAD~1"``).

    Returns:
        str: Unified diff text for changed ``.py`` files.
    """
    stdout, stderr, code = run(["git", "diff", "--name-only", "--diff-filter=ACMRT", base, "HEAD"])
    python_files = [f for f in stdout.strip().splitlines() if f.endswith(".py")] if stdout.strip() else []
    if python_files:
        stdout, stderr, code = run(["git", "diff", base, "HEAD", "--", *python_files])
    if code != 0 or not stdout.strip():
        if code != 0 and stderr.strip():
            print(f"[prep_review_context] git diff error: {stderr.strip()}", file=sys.stderr)
        stdout, _, _ = run(["git", "diff", "--cached", "--", "*.py"])
    return stdout


def load_index_sections(file_paths: list[str]) -> dict[str, str]:
    """Extract only the index sections for the specified files.

    Args:
        file_paths (list[str]): File paths to look up in code_index.md.

    Returns:
        dict[str, str]: Mapping of input file path to its index section
        content, for files that have a matching entry.
    """
    if not INDEX_PATH.exists():
        return {}

    content = INDEX_PATH.read_text(encoding="utf-8")
    index: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        start_match = MARKER_START_PATTERN.match(line.strip())
        end_match = MARKER_END_PATTERN.match(line.strip())

        if start_match:
            current_key = start_match.group(1)
            current_lines = []
        elif end_match and current_key:
            index[current_key] = "\n".join(current_lines).strip()
            current_key = None
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    result: dict[str, str] = {}
    for fp in file_paths:
        norm = fp.replace("\\", "/")
        for key, val in index.items():
            if norm.endswith(key) or key.endswith(norm) or norm == key:
                result[fp] = val
                break
    return result


def detect_layers_touched(file_paths: list[str]) -> tuple[list[str], bool]:
    """Best-effort layer classification from path segments, plus a high-risk-area flag.

    Feeds Code Reviewer's Risk Assessment so "layers touched" and "touches a
    high-risk area" are read from the diff, not self-reported.

    Args:
        file_paths (list[str]): Changed file paths to classify.

    Returns:
        tuple[list[str], bool]: Sorted layer names touched, and True if any
        path matches a high-risk marker like auth/payment/secret/a2a.
    """
    layers: set[str] = set()
    high_risk = False
    for fp in file_paths:
        segments = normalize_path(fp).lower().split("/")
        for seg in segments:
            if seg in LAYER_MARKERS:
                layers.add(LAYER_MARKERS[seg])
            if seg in HIGH_RISK_MARKERS:
                high_risk = True
    return sorted(layers), high_risk


def count_unresolved_criticals() -> int:
    """CRITICAL count from the latest review_log.md block, or 0 if no reviews yet.

    Mirrors the scoped-to-last-block parsing in session_metrics.py — scans only the
    most recent '## Review' section so an old resolved issue doesn't get double-counted.

    Returns:
        int: Number of unresolved CRITICAL issues in the latest review block.
    """
    if not REVIEW_LOG_PATH.exists():
        return 0
    content = REVIEW_LOG_PATH.read_text(encoding="utf-8")
    review_headers = list(re.finditer(r"^## Review — .+? — Iteration \d+\s*$", content, flags=re.M))
    if not review_headers:
        return 0
    last = review_headers[-1]
    start = last.start()
    end = len(content)
    for match in review_headers:
        if match.start() > start:
            end = match.start()
            break
    block = content[start:end]
    critical_match = re.search(r"Critical:\s*(\d+)", block)
    return int(critical_match.group(1)) if critical_match else 0


def count_diff_stats(diff: str) -> tuple[int, int]:
    """Count added and removed lines in a git diff string.

    Args:
        diff (str): Unified diff text.

    Returns:
        tuple[int, int]: Number of added lines and number of removed lines
        (excluding the ``+++``/``---`` file-header lines).
    """
    added = sum(
        1 for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return added, removed


def build_context(base: str, output_path: Path) -> None:
    """Build and write the compact review context file.

    Args:
        base (str): Git ref to diff against (e.g. ``"HEAD~1"``).
        output_path (Path): Destination path for the generated review context
            Markdown file.
    """
    changed_files = get_changed_files(base)

    if not changed_files:
        print(f"No changed Python files found between {base} and HEAD.")
        print("Check: git status, git log, or try --base with a different ref.")
        return

    diff = get_diff(base)
    sections = load_index_sections(changed_files)
    added, removed = count_diff_stats(diff)
    layers_touched, high_risk_area = detect_layers_touched(changed_files)
    unresolved_criticals = count_unresolved_criticals()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    index_coverage = f"{len(sections)}/{len(changed_files)}"

    doc_lines: list[str] = [
        f"# Review Context — {timestamp}",
        f"Comparing: `{base}` → HEAD\n",
        "## Session Stats",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Files changed | {len(changed_files)} |",
        f"| Lines added | +{added} |",
        f"| Lines removed | -{removed} |",
        f"| Index coverage | {index_coverage} files indexed |",
        f"| Layers touched (computed) | {', '.join(layers_touched) if layers_touched else 'none detected'} |",
        f"| High-risk area touched (computed) | {'yes' if high_risk_area else 'no'} |",
        f"| Unresolved CRITICAL from last review (computed) | {unresolved_criticals} |",
        "",
        "> Reviewer: use the three computed rows above for the Risk Assessment table's "
        "'Layers touched' and 'Unresolved CRITICAL' rows instead of re-deriving them from "
        "memory — they're read from the diff and review_log.md, not self-reported.",
        "",
        "## Changed Files",
    ]

    for fp in changed_files:
        status = "✓ indexed" if fp in sections else "✗ not indexed"
        doc_lines.append(f"- `{fp}` — {status}")

    doc_lines += ["", "---", "", "## Code Index — Changed Files Only"]
    if sections:
        for fp, section in sections.items():
            doc_lines += [f"\n### {fp}", section]
    else:
        doc_lines.append(
            "_No indexed entries for changed files. "
            "Run coding-agent to write code and auto-index._"
        )

    doc_lines += [
        "",
        "---",
        "",
        "## Git Diff",
        "```diff",
        diff.strip() if diff.strip() else "(empty diff — check git status)",
        "```",
        "",
        "---",
        "",
        "## Reviewer Checklist",
        "- [ ] Read index sections above — understand module context without loading full files",
        "- [ ] Review diff for: correctness, design, security, performance, maintainability",
        "- [ ] For any CRITICAL issue needing full context: Read only that specific file (budget: 2 reads)",
        "- [ ] Write findings to `.claude/project_memory/review_log.md`",
        "- [ ] Invoke `code-refactor` agent if REQUEST_CHANGES, or `unit-test` if APPROVE",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(doc_lines), encoding="utf-8")

    print(f"✓ Review context written to: {output_path}")
    print(f"  {len(changed_files)} files | +{added}/-{removed} lines | {index_coverage} indexed")


def main() -> None:
    """Parse CLI args and build the review context file.

    Reads ``--base`` (defaults to ``HEAD~1``) and ``--output`` (defaults to
    ``.claude/project_memory/review_context.md``), then delegates to
    ``build_context``.
    """
    parser = argparse.ArgumentParser(
        description="Package git diff + code index into a compact review context file"
    )
    parser.add_argument(
        "--base", default="HEAD~1",
        help="Base git ref to diff against (default: HEAD~1)"
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help=f"Output file path (default: {DEFAULT_OUTPUT})"
    )
    args = parser.parse_args()
    build_context(base=args.base, output_path=Path(args.output))


if __name__ == "__main__":
    main()
