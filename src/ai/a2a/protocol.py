"""Typed protocol models for A2A (Agent-to-Agent) communication."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class A2AMessage(BaseModel):
    """Envelope sent from one agent to a peer agent.

    Attributes:
        id (str): Unique identifier for this message.
        sender (str): agent_id of the originating agent.
        payload (str): The message/task text.
        trace_id (str): Correlation id shared across a request/response pair.
        metadata (dict[str, Any]): Arbitrary additional context.
        created_at (datetime): UTC timestamp of message creation.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str  # agent_id of the originating agent
    payload: str  # the message/task text
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class A2AResponse(BaseModel):
    """Response returned by a peer agent after handling an A2AMessage.

    Attributes:
        message_id (str): id of the A2AMessage this responds to.
        sender (str): agent_id of the responding agent.
        output (str): The peer agent's output text.
        trace_id (str): Correlation id shared with the originating A2AMessage.
        duration_ms (float): Time taken to produce the response, in milliseconds.
        metadata (dict[str, Any]): Arbitrary additional context.
    """

    message_id: str  # id of the A2AMessage this responds to
    sender: str  # agent_id of the responding agent
    output: str
    trace_id: str
    duration_ms: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2APeer(BaseModel):
    """Declares a peer agent reachable by name via delegate().

    Attributes:
        name (str): Logical name used in delegate(peer_name, ...).
        description (str): Human-readable description; used as tool description
            for LLM-native injection.
        agent (Any): AbstractBaseAgent instance; typed as Any to avoid a circular
            import at module load time.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(description="Logical name used in delegate(peer_name, ...)")
    description: str = Field(
        default="",
        description="Human-readable description; used as tool description for LLM-native injection",
    )
    # AbstractBaseAgent instance — typed as Any to avoid circular import at module load time
    agent: Any = Field(description="AbstractBaseAgent instance")
