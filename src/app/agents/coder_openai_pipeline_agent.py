"""OpenAI-backed coder agent — delegates code review to a Claude peer via A2A."""

from __future__ import annotations

from pydantic import Field

from src.ai.base_openai import OpenAIBaseAgent


class CoderOpenAIPipelineAgent(OpenAIBaseAgent):
    """Writes Python code and hands off to a reviewer peer for quality validation.

    Typical wiring::

        from src.ai.a2a.protocol import A2APeer
        from src.app.agents.reviewer_claude_agent import ReviewerClaudeAgent

        coder = CoderOpenAIPipelineAgent(
            peers=[A2APeer(
                name="reviewer",
                description="Reviews code for correctness and style",
                agent=ReviewerClaudeAgent(),
            )]
        )
        result = coder.run("Write a Python function to binary-search a sorted list.")
    """

    name: str = Field(default="Python Coder")
    description: str = Field(
        default="Writes clean Python code and delegates review to a peer agent."
    )
    instructions: str = Field(
        default=(
            "You are a professional Python software engineer. "
            "When asked to write code, produce clean, typed, and well-structured Python. "
            "After writing code, if a reviewer peer is available, request a review "
            "by handing off the code. Incorporate any REQUEST_CHANGES feedback before "
            "delivering the final implementation."
        )
    )
