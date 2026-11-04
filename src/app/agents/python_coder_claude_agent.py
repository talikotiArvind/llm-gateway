"""Claude-backed professional Python coder agent."""

from src.resource.base_claude import BaseAgent
from pydantic import Field


class PythonCoderClaudeAgent(BaseAgent):
    """Writes clean, efficient, and well-documented Python code, powered by Claude."""

    name: str = Field(default="Professional Python coder", description="Name of the agent")
    instructions: str = Field(
        default="You are a professional Python coder. Write clean, efficient, and well-documented Python code.",
        description="Instructions for the agent",
    )
