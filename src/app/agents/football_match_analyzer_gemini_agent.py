"""Football match analyzer agent powered by Gemini."""
from __future__ import annotations

from pydantic import Field

from src.resource.base_gemini import BaseAgent


class FootballMatchAnalyzerGeminiAgent(BaseAgent):
    """Football match analyzer agent powered by Gemini."""

    name: str = Field(
        default="Football match analyzer",
        description="Name of the agent",
    )
    instructions: str = Field(
        default=(
            "You are a football match analyst. "
            "Analyze football matches and provide detailed insights."
        ),
        description="Instructions for the agent",
    )
