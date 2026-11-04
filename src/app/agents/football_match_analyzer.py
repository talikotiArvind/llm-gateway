"""OpenAI-backed football match analyzer agent."""

from src.ai.base_openai import BaseAgent
from pydantic import Field

class FootballMatchAnalyzerAgent(BaseAgent):
    """Analyzes football matches and provides detailed insights, powered by OpenAI."""
    name: str = Field(default="Football match analyzer", description="Name of the agent")
    instructions: str = Field(default="You are a football match analyst. Analyze football matches and provide detailed insights.", description="Instructions for the agent")