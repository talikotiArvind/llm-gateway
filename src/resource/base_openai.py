"""OpenAI provider base — inherits AbstractBaseAgent."""

from __future__ import annotations

import os
from typing import Any, cast

from agents import Agent, Runner, set_default_openai_key
from dotenv import load_dotenv
from pydantic import Field

from src.resource.base_agent import AbstractBaseAgent

load_dotenv()


class OpenAIBaseAgent(AbstractBaseAgent):
    """Base for all OpenAI-backed agents.

    Extends AbstractBaseAgent with:
    - openai-agents SDK (Runner.run_sync) execution
    - A2A peer injection as openai-agents handoffs
    - Explicit model field (default: gpt-4o)
    """

    model: str = Field(default="gpt-4o", description="OpenAI model to use")

    # ------------------------------------------------------------------
    # A2A handoff helpers
    # ------------------------------------------------------------------

    def _build_openai_handoffs(self) -> list[Any]:
        """Build openai-agents handoff objects for this agent's declared peers.

        Returns:
            list[Any]: openai-agents SDK Agent objects usable as handoffs, or
                an empty list when no peers are declared.
        """
        if not self.peers:
            return []
        from src.resource.a2a.tool_adapter import to_openai_handoffs
        return to_openai_handoffs(self.peers)

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def run(self, message: str, **kwargs: object) -> str:
        """Execute the agent synchronously via the openai-agents Runner.

        Wires declared peers as handoffs so the SDK can delegate to them
        autonomously.

        Args:
            message (str): The task or prompt to send to the agent.
            **kwargs (object): Unused; present for interface compatibility.

        Returns:
            str: The agent's final output text.
        """
        set_default_openai_key(os.getenv("OPENAI_API_KEY"))

        handoffs = self._build_openai_handoffs()

        agent_kwargs: dict[str, Any] = dict(
            name=self.name,
            instructions=self.instructions,
            model=self.model,
        )
        if handoffs:
            agent_kwargs["handoffs"] = handoffs

        agent = Agent(**agent_kwargs)
        result = Runner.run_sync(agent, message)
        return cast(str, result.final_output)


# Backward-compatible alias
BaseAgent = OpenAIBaseAgent
