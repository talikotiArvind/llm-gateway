"""PostToolUse hook: auto-updates .claude/project_memory/code_index.md
when a Python source file is edited or written.

Extracts class/function signatures via AST (no full file re-read needed).
Also increments the session write counter in metrics.md.

Receives JSON on stdin from Claude Code with tool_name and tool_input.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from _hook_utils import increment_metric, normalize_path

INDEX_PATH = Path(".claude/project_memory/code_index.md")
METRICS_PATH = Path(".claude/project_memory/metrics.md")
MARKER_START = "<!-- BEGIN: {} -->"
MARKER_END = "<!-- END: {} -->"


def extract_signatures(file_path: Path) -> str | None:
    """Extract class and function signatures from a Python file using AST.

    Logs a message to stderr and returns None on syntax errors or read
    failures instead of raising.

    Args:
        file_path (Path): Path to the Python source file to parse.

    Returns:
        str | None: Markdown-formatted purpose/classes/functions summary, or
        None if the file could not be parsed or read.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"[update_code_index] syntax error indexing {file_path}: {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"[update_code_index] failed to read {file_path}: {exc}", file=sys.stderr)
        return None

    lines: list[str] = []

    module_docstring = ast.get_docstring(tree)
    purpose = module_docstring.split("\n")[0] if module_docstring else "No module docstring"
    lines.append(f"**Purpose**: {purpose}")

    # Only top-level classes (not nested inner classes)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    # Only top-level functions (module-level, not inside classes)
    functions = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    if classes:
        lines.append("**Classes**:")
        for cls in classes:
            cls_doc = ast.get_docstring(cls) or ""
            cls_summary = cls_doc.split("\n")[0] if cls_doc else ""
            bases = (
                ", ".join(ast.unparse(b) for b in cls.bases)
                if cls.bases
                else ""
            )
            cls_label = f"`{cls.name}({bases})`" if bases else f"`{cls.name}`"
            lines.append(f"  - {cls_label}: {cls_summary}")

            for node in cls.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = _format_function_sig(node, indent=4)
                    if sig:
                        lines.append(sig)

    if functions:
        lines.append("**Functions**:")
        for func in functions:
            sig = _format_function_sig(func, indent=0)
            if sig:
                lines.append(sig)

    return "\n".join(lines)


def _format_function_sig(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    indent: int,
) -> str | None:
    """Format a single function/method as a one-line signature + docstring.

    Args:
        node (ast.FunctionDef | ast.AsyncFunctionDef): Function or method AST node.
        indent (int): Number of leading spaces for the formatted line.

    Returns:
        str | None: A one-line Markdown bullet with signature and docstring
        summary, or None for dunder methods other than lifecycle/context ones.
    """
    # Skip most dunder methods but keep lifecycle/context methods that matter in APIs.
    keep_dunder = {"__init__", "__call__", "__enter__", "__exit__", "__aenter__", "__aexit__"}
    if node.name.startswith("__") and node.name not in keep_dunder:
        return None

    prefix = " " * indent
    args = _format_args(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    doc = ast.get_docstring(node) or ""
    doc_summary = doc.split("\n")[0] if doc else ""
    is_async = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    decorators = _format_decorators(node.decorator_list)
    decorator_prefix = f"{decorators} " if decorators else ""
    return f"{prefix}- `{decorator_prefix}{is_async}{node.name}({args}){ret}`: {doc_summary}"


def _format_args(args: ast.arguments) -> str:
    """Format function argument list with type annotations.

    Handles positional-only, regular, ``*args``, keyword-only, and
    ``**kwargs`` parameters, including their defaults.

    Args:
        args (ast.arguments): AST arguments node from a function definition.

    Returns:
        str: Comma-separated, formatted argument list.
    """
    parts: list[str] = []
    posonly = args.posonlyargs
    regular = args.args
    all_positional = posonly + regular
    positional_defaults: list[ast.expr | None] = (
        [None] * (len(all_positional) - len(args.defaults)) + list(args.defaults)
    )
    posonly_defaults = positional_defaults[:len(posonly)]
    regular_defaults = positional_defaults[len(posonly):]

    for arg, default in zip(posonly, posonly_defaults):
        parts.append(_format_arg(arg, default))
    if posonly:
        parts.append("/")

    for arg, default in zip(regular, regular_defaults):
        parts.append(_format_arg(arg, default))

    if args.vararg:
        vararg = _format_arg(args.vararg, None)
        parts.append(f"*{vararg}")
    elif args.kwonlyargs:
        parts.append("*")

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(_format_arg(arg, default))

    if args.kwarg:
        kwarg = _format_arg(args.kwarg, None)
        parts.append(f"**{kwarg}")

    return ", ".join(parts)


def _format_arg(arg: ast.arg, default: ast.expr | None) -> str:
    """Format a single function argument with annotation and optional default.

    Args:
        arg (ast.arg): AST node for the argument.
        default (ast.expr | None): AST node for the argument's default value,
            or None if it has no default.

    Returns:
        str: Formatted ``name: annotation = default`` string (parts omitted
        when not present).
    """
    if arg.annotation:
        formatted = f"{arg.arg}: {ast.unparse(arg.annotation)}"
    else:
        formatted = arg.arg
    if default is not None:
        formatted += f" = {ast.unparse(default)}"
    return formatted


def _format_decorators(decorators: list[ast.expr]) -> str:
    """Format decorators into compact inline prefix for signature summaries.

    Args:
        decorators (list[ast.expr]): AST expression nodes for each decorator.

    Returns:
        str: Space-separated ``@decorator`` strings, or an empty string if
        there are none.
    """
    if not decorators:
        return ""
    return " ".join(f"@{ast.unparse(decorator)}" for decorator in decorators)


def update_index(file_path: Path, signatures: str) -> None:
    """Insert or replace the file's section in code_index.md.

    Creates code_index.md with a header if it does not already exist.

    Args:
        file_path (Path): Path of the source file the section describes.
        signatures (str): Markdown signature summary produced by
            ``extract_signatures``.
    """
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    if INDEX_PATH.exists():
        content = INDEX_PATH.read_text(encoding="utf-8")
    else:
        content = (
            "# Code Index\n\n"
            "Auto-updated by hooks. **Read this before reading any source file.**\n\n"
        )

    rel_path = normalize_path(str(file_path))
    start_marker = MARKER_START.format(rel_path)
    end_marker = MARKER_END.format(rel_path)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    new_section = (
        f"{start_marker}\n"
        f"## {rel_path}\n"
        f"*Updated: {timestamp}*\n\n"
        f"{signatures}\n"
        f"{end_marker}"
    )

    if start_marker in content and end_marker in content:
        start_idx = content.rindex(start_marker)
        end_idx = content.index(end_marker, start_idx) + len(end_marker)
        content = content[:start_idx] + new_section + content[end_idx:]
    else:
        content = content.rstrip() + "\n\n" + new_section + "\n"

    INDEX_PATH.write_text(content, encoding="utf-8")


def main() -> None:
    """Read the PostToolUse hook payload from stdin and re-index the written file.

    Ignores tool calls other than Edit/Write, non-Python files, test files,
    and files under ``.claude``. For qualifying files, extracts signatures via
    AST and updates code_index.md, bumping ``files_written_this_session`` in
    metrics.md on success.
    """
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name: str = payload.get("tool_name", "")
    tool_input: dict[str, Any] = payload.get("tool_input", {})

    if tool_name not in ("Edit", "Write"):
        sys.exit(0)

    file_path_str: str = tool_input.get("file_path", "")
    if not file_path_str or not file_path_str.endswith(".py"):
        sys.exit(0)

    file_path = Path(file_path_str)
    if not file_path.exists():
        sys.exit(0)

    # Skip test files and internal .claude hook scripts
    if file_path.name.startswith("test_") or ".claude" in str(file_path):
        sys.exit(0)

    signatures = extract_signatures(file_path)
    if signatures:
        update_index(file_path, signatures)
        increment_metric(METRICS_PATH, "files_written_this_session")


if __name__ == "__main__":
    main()
