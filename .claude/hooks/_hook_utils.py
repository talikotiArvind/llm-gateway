"""Shared helpers for Claude hook scripts."""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

MARKER_START_PATTERN = re.compile(r"<!-- BEGIN: (.+?) -->")
MARKER_END_PATTERN = re.compile(r"<!-- END: (.+?) -->")

PROJECT_MEMORY_ALLOWLIST = {
    "code_index.md",
    "review_log.md",
    "review_context.md",
    "requirements.md",
    "design.md",
    "implementation_plan.md",
    "decisions.md",
    "metrics.md",
    "CLAUDE.md",
    "conftest.py",
    "settings.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
}


def normalize_path(path: str) -> str:
    """Normalize path separators for cross-platform matching.

    Args:
        path (str): File path, possibly using Windows-style backslashes.

    Returns:
        str: The path with all backslashes converted to forward slashes.
    """
    return path.replace("\\", "/")


def increment_metric(metrics_path: Path, key: str) -> None:
    """Increment an integer metric key in metrics.md.

    Silently does nothing if the metrics file is missing or the key is not
    found; write failures are logged to stderr rather than raised.

    Args:
        metrics_path (Path): Path to the metrics.md file.
        key (str): Metric key whose integer value should be incremented by 1.
    """
    if not metrics_path.exists():
        return
    try:
        content = metrics_path.read_text(encoding="utf-8")
        pattern = re.compile(rf"({re.escape(key)}:\s*)(\d+)")
        match = pattern.search(content)
        if not match:
            return
        new_val = int(match.group(2)) + 1
        updated = content[: match.start(2)] + str(new_val) + content[match.end(2) :]
        metrics_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        print(f"[hook-utils] metric update failed for '{key}': {exc}", file=sys.stderr)


def parse_index(index_path: Path) -> dict[str, str]:
    """Parse code_index.md markers into {file_path: section_content}.

    Logs a warning to stderr (but does not raise) on malformed markers such
    as nested or missing BEGIN/END pairs.

    Args:
        index_path (Path): Path to the code_index.md file.

    Returns:
        dict[str, str]: Mapping of indexed file path to its section content.
        Empty if the file does not exist.
    """
    if not index_path.exists():
        return {}
    content = index_path.read_text(encoding="utf-8")
    index: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        start_match = MARKER_START_PATTERN.match(line.strip())
        end_match = MARKER_END_PATTERN.match(line.strip())
        if start_match:
            if current_key is not None:
                print(
                    f"[hook-utils] malformed code_index: nested BEGIN before END for '{current_key}'",
                    file=sys.stderr,
                )
            current_key = start_match.group(1)
            current_lines = []
        elif end_match:
            if current_key is None:
                print(
                    f"[hook-utils] malformed code_index: END without BEGIN for '{end_match.group(1)}'",
                    file=sys.stderr,
                )
                continue
            index[current_key] = "\n".join(current_lines).strip()
            current_key = None
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key is not None:
        print(
            f"[hook-utils] malformed code_index: missing END marker for '{current_key}'",
            file=sys.stderr,
        )
    return index


@lru_cache(maxsize=8)
def cached_index_keys(index_path_str: str, mtime_ns: int, size: int) -> tuple[str, ...]:
    """Return cached tuple of index keys for fast repeated lookups.

    ``mtime_ns`` and ``size`` are part of the cache key only, so the cache
    is automatically invalidated when the index file changes on disk.

    Args:
        index_path_str (str): Path to the code_index.md file, as a string.
        mtime_ns (int): File modification time in nanoseconds (cache-key only).
        size (int): File size in bytes (cache-key only).

    Returns:
        tuple[str, ...]: All indexed file-path keys.
    """
    _ = mtime_ns, size  # cache-key only
    index = parse_index(Path(index_path_str))
    return tuple(index.keys())
