"""Gemini-backed fact-checker agent — usable as a standalone or as an A2A peer."""

from __future__ import annotations

from pydantic import Field

from src.resource.base_gemini import GeminiBaseAgent


class FactCheckerGeminiAgent(GeminiBaseAgent):
    """Verifies factual claims and returns a concise verdict with supporting evidence."""

    name: str = Field(default="Fact Checker")
    description: str = Field(
        default="Verifies factual claims and returns a verdict with supporting evidence."
    )
    instructions: str = Field(
        default=(
            "You are a rigorous fact-checker. "
            "When given a claim or statement, evaluate its accuracy. "
            "Respond with: VERDICT (True/False/Unverified), one-sentence justification, "
            "and up to two supporting evidence points. Be concise."
        )
    )
