"""Shared abstract base for all provider-specific agent implementations."""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from src.resource.a2a.protocol import A2AMessage, A2APeer, A2AResponse


class AbstractBaseAgent(BaseModel, ABC):
    """Provider-agnostic contract shared by ClaudeBaseAgent, OpenAIBaseAgent, GeminiBaseAgent.

    Concrete agents subclass one of the provider bases, never this class directly.
    A2A capability is opt-in: declare peers to enable cross-agent delegation.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable unique identifier for routing and trace logs",
    )
    name: str = Field(description="Display name of the agent")
    instructions: str = Field(description="System prompt / role instructions")
    description: str = Field(
        default="",
        description="Short description used as tool description when this agent is a peer",
    )
    peers: list[A2APeer] = Field(
        default_factory=list,
        description="Peer agents reachable via delegate(). Empty = A2A disabled.",
    )

    # ------------------------------------------------------------------
    # Core execution — must be implemented by each provider base
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, message: str, **kwargs: object) -> str:
        """Execute the agent synchronously.

        Args:
            message (str): The task or prompt to send to the agent.
            **kwargs (object): Provider-specific execution options.

        Returns:
            str: The agent's output text.
        """

    async def run_async(self, message: str, **kwargs: object) -> str:
        """Execute the agent asynchronously.

        Default implementation wraps the synchronous run() via asyncio.to_thread.
        Provider bases that natively support async may override this.

        Args:
            message (str): The task or prompt to send to the agent.
            **kwargs (object): Provider-specific execution options.

        Returns:
            str: The agent's output text.
        """
        return await asyncio.to_thread(self.run, message, **kwargs)

    # ------------------------------------------------------------------
    # A2A delegation
    # ------------------------------------------------------------------

    def delegate(self, peer_name: str, message: str, trace_id: str | None = None) -> A2AResponse:
        """Send a sub-task to a named peer agent and return its response.

        Args:
            peer_name (str): Logical name of the peer to delegate to; must be
                declared in self.peers.
            message (str): The sub-task or question to send to the peer.
            trace_id (str | None): Optional correlation id to propagate; a new
                one is generated when omitted.

        Returns:
            A2AResponse: The peer agent's response.

        Raises:
            KeyError: If peer_name is not in self.peers.
            Exception: Propagates any exception raised by the peer.
        """
        from src.resource.a2a.router import A2ARouter

        router = A2ARouter(peers=self.peers)
        if trace_id:
            envelope = A2AMessage(sender=self.agent_id, payload=message, trace_id=trace_id)
        else:
            envelope = A2AMessage(sender=self.agent_id, payload=message)
        return router.dispatch(peer_name, envelope)

    async def delegate_async(
        self, peer_name: str, message: str, trace_id: str | None = None
    ) -> A2AResponse:
        """Send a sub-task to a named peer agent asynchronously.

        Async variant of :meth:`delegate` — awaits the peer's run_async().

        Args:
            peer_name (str): Logical name of the peer to delegate to; must be
                declared in self.peers.
            message (str): The sub-task or question to send to the peer.
            trace_id (str | None): Optional correlation id to propagate; a new
                one is generated when omitted.

        Returns:
            A2AResponse: The peer agent's response.

        Raises:
            KeyError: If peer_name is not in self.peers.
            Exception: Propagates any exception raised by the peer.
        """
        from src.resource.a2a.router import A2ARouter

        router = A2ARouter(peers=self.peers)
        if trace_id:
            envelope = A2AMessage(sender=self.agent_id, payload=message, trace_id=trace_id)
        else:
            envelope = A2AMessage(sender=self.agent_id, payload=message)
        return await router.dispatch_async(peer_name, envelope)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def peer_names(self) -> list[str]:
        """Return the sorted list of declared peer names.

        Returns:
            list[str]: Sorted names of peers declared on this agent.
        """
        return sorted(p.name for p in self.peers)

    def has_peers(self) -> bool:
        """Check whether this agent has any declared peers.

        Returns:
            bool: True when this agent has at least one declared peer.
        """
        return bool(self.peers)
