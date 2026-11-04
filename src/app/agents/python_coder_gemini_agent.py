"""Gemini-backed professional Python coder agent."""
from __future__ import annotations

from pydantic import Field

from src.ai.base_gemini import BaseAgent


class PythonCoderGeminiAgent(BaseAgent):
    """Professional Python coder agent powered by Gemini."""

    name: str = Field(
        default="Professional Python coder",
        description="Name of the agent",
    )
    instructions: str = Field(
        default="You are a professional Python coder. Write clean, efficient, and well-documented Python code.",
        description="Instructions for the agent",
    )
