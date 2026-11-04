"""SessionStart hook: initializes session metrics and displays project status.

Reads .claude/project_memory/metrics.md and emits a compact status panel
to the user at the start of every session, showing:
  - How many source modules are indexed
  - Last review outcome and iteration count
  - Current test coverage (if recorded)
  - Token efficiency score (index hits vs full reads)

Also resets per-session counters (index_hits, full_reads, files_written).

Outputs JSON to stdout (systemMessage shown to user, additionalContext to model).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

METRICS_PATH = Path(".claude/project_memory/metrics.md")
INDEX_PATH = Path(".claude/project_memory/code_index.md")
REVIEW_LOG_PATH = Path(".claude/project_memory/review_log.md")


def count_indexed_modules() -> int:
    """Count how many modules are tracked in code_index.md.

    Returns:
        int: Number of ``BEGIN`` markers found, or 0 if the index file is
        missing.
    """
    if not INDEX_PATH.exists():
        return 0
    content = INDEX_PATH.read_text(encoding="utf-8")
    return len(re.findall(r"<!-- BEGIN:", content))


def get_last_review_summary() -> str:
    """Extract the last review verdict from review_log.md.

    Returns:
        str: A compact ``"Iter <n> | <VERDICT> | <timestamp>"`` summary, or
        ``"No reviews yet"`` if the log is missing or has no review headers.
    """
    if not REVIEW_LOG_PATH.exists():
        return "No reviews yet"
    content = REVIEW_LOG_PATH.read_text(encoding="utf-8")
    # For large logs, focus parsing on tail while preserving latest review block.
    if len(content) > 50000:
        content = content[-50000:]
    review_headers = list(re.finditer(r"^## Review — (.+?) — Iteration (\d+)\s*$", content, flags=re.M))
    if not review_headers:
        return "No reviews yet"

    last_match = review_headers[-1]
    review_matches = list(re.finditer(r"^## Review — (.+?) — Iteration (\d+)\s*$", content, flags=re.M))
    if not review_matches:
        return "No reviews yet"

    last_match = review_matches[-1]
    last_ts = last_match.group(1)
    last_iter = last_match.group(2)
    start = last_match.start()
    end = len(content)
    # Bound the block at the next review header, if present.
    for match in review_matches:
        if match.start() > start:
            end = match.start()
            break
    review_block = content[start:end]
    verdict_match = re.search(r"Recommendation:\s*(APPROVE|REQUEST_CHANGES)", review_block)
    verdict = verdict_match.group(1) if verdict_match else "unknown"
    return f"Iter {last_iter} | {verdict} | {last_ts}"


def read_metric(content: str, key: str, default: str = "—") -> str:
    """Extract a metric value from metrics.md content.

    Args:
        content (str): Full text content of metrics.md.
        key (str): Metric key to search for (e.g. ``"coverage_pct"``).
        default (str): Value to return if the key is not found.

    Returns:
        str: The metric's value, or ``default`` if not found.
    """
    match = re.search(rf"{re.escape(key)}:\s*(.+)", content)
    return match.group(1).strip() if match else default


def reset_session_counters() -> None:
    """Reset per-session counters to 0 at the start of each session."""
    if not METRICS_PATH.exists():
        return
    try:
        content = METRICS_PATH.read_text(encoding="utf-8")
        for key in (
            "index_hits",
            "full_reads",
            "indexed_reads_proceeded",
            "files_written_this_session",
        ):
            pattern = re.compile(rf"({re.escape(key)}:\s*)(\d+)")
            content = pattern.sub(r"\g<1>0", content)
        METRICS_PATH.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"[session_metrics] failed to reset counters: {exc}", file=sys.stderr)


def ensure_metrics_file() -> None:
    """Create metrics.md with default structure if it doesn't exist."""
    if METRICS_PATH.exists():
        return
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    METRICS_PATH.write_text(
        f"# Project Metrics\n\n"
        f"Auto-updated by hooks. Last reset: {today}\n\n"
        f"## Token Efficiency (session)\n"
        f"index_hits: 0\n"
        f"full_reads: 0\n"
        f"indexed_reads_proceeded: 0\n"
        f"files_written_this_session: 0\n\n"
        f"## Code Quality (last run)\n"
        f"ruff_violations: —\n"
        f"mypy_errors: —\n"
        f"annotation_coverage_pct: —\n"
        f"avg_complexity: —\n\n"
        f"## Test Quality (last run)\n"
        f"coverage_pct: —\n"
        f"total_tests: —\n"
        f"passing_tests: —\n"
        f"failing_tests: —\n"
        f"branches_covered_pct: —\n\n"
        f"## Review History\n"
        f"total_review_iterations: 0\n"
        f"issues_resolved: 0\n"
        f"issues_rejected: 0\n",
        encoding="utf-8",
    )


def main() -> None:
    """Emit the session-start status panel and reset per-session counters.

    Ensures metrics.md exists, computes the previous session's token
    efficiency ratio from its counters, then resets those counters and
    prints a JSON payload containing both a user-facing ``systemMessage``
    status panel and model-facing ``additionalContext``.
    """
    ensure_metrics_file()

    indexed = count_indexed_modules()
    last_review = get_last_review_summary()

    content = METRICS_PATH.read_text(encoding="utf-8")
    coverage = read_metric(content, "coverage_pct")
    ruff = read_metric(content, "ruff_violations")
    mypy = read_metric(content, "mypy_errors")
    index_hits = read_metric(content, "index_hits", "0")
    full_reads = read_metric(content, "full_reads", "0")
    indexed_reads_proceeded = read_metric(content, "indexed_reads_proceeded", "0")

    # Compute efficiency ratio from previous session before reset
    try:
        hits = int(index_hits)
        reads = int(full_reads)
        proceeded = int(indexed_reads_proceeded)
        true_skips = max(hits - proceeded, 0)
        total = true_skips + reads
        efficiency = f"{int(true_skips/total*100)}%" if total > 0 else "n/a (first session)"
    except ValueError:
        efficiency = "n/a"

    reset_session_counters()

    status_lines = [
        "Project Session Status",
        f"- Indexed modules  : {indexed}",
        f"- Last review      : {last_review}",
        f"- Test coverage    : {coverage}",
        f"- Ruff violations  : {ruff}",
        f"- Mypy errors      : {mypy}",
        f"- Token efficiency : {efficiency}",
    ]
    status_msg = "\n".join(status_lines)

    output = {
        "systemMessage": status_msg,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                f"Session started. Project has {indexed} indexed modules. "
                f"Previous session true skip efficiency: {efficiency} "
                f"(index-hit suggestions accepted vs full reads). "
                f"Read `.claude/project_memory/code_index.md` first before any source file. "
                f"Full metrics in `.claude/project_memory/metrics.md`."
            ),
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
