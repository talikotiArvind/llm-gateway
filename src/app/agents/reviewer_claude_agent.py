"""Claude-backed code reviewer — usable standalone or as an A2A peer."""

from __future__ import annotations

from pydantic import Field

from src.ai.base_claude import ClaudeBaseAgent


class ReviewerClaudeAgent(ClaudeBaseAgent):
    """Reviews code for correctness, style, and security; returns structured feedback."""

    name: str = Field(default="Code Reviewer")
    description: str = Field(
        default="Reviews code for correctness, style, and security issues."
    )
    instructions: str = Field(
        default=(
            "You are a senior software engineer performing a code review. "
            "For the code provided, give structured feedback covering: "
            "1) Correctness — logic bugs or edge cases missed. "
            "2) Style — naming, readability, unnecessary complexity. "
            "3) Security — injection risks, secrets, unsafe operations. "
            "4) Verdict — APPROVE / REQUEST_CHANGES with a one-line summary. "
            "Be direct and specific. Reference line numbers when possible."
        )
    )
