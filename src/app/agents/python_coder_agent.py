"""OpenAI-backed professional Python coder agent."""

from src.ai.base_openai import BaseAgent
from pydantic import Field

class PythonCoderAgent(BaseAgent):
    """Writes clean, efficient, and well-documented Python code, powered by OpenAI."""
    name: str = Field(default="Professional Python coder", description="Name of the agent")
    instructions: str = Field(default="You are a professional Python coder. Write clean, efficient, and well-documented Python code.", description="Instructions for the agent")
