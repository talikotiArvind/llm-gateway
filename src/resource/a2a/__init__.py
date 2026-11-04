"""A2A (Agent-to-Agent) communication layer."""

from src.resource.a2a.protocol import A2AMessage, A2APeer, A2AResponse
from src.resource.a2a.router import A2ARouter
from src.resource.a2a.tool_adapter import (
    handle_anthropic_tool_call,
    handle_gemini_function_call,
    to_anthropic_tools,
    to_gemini_tools,
    to_openai_handoffs,
)

__all__ = [
    "A2AMessage",
    "A2APeer",
    "A2AResponse",
    "A2ARouter",
    "to_anthropic_tools",
    "handle_anthropic_tool_call",
    "to_openai_handoffs",
    "to_gemini_tools",
    "handle_gemini_function_call",
]
