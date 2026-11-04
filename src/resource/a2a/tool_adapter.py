"""Per-provider adapters that expose A2APeer agents as native tool definitions.

Each adapter converts the list of declared peers into the format expected by the
provider's SDK so the LLM can autonomously decide to delegate to a peer.

Anthropic  → tools=[{"name": ..., "description": ..., "input_schema": {...}}]
OpenAI     → handoffs=[Agent(...)] via the openai-agents SDK
Gemini     → tools=[genai.protos.Tool(function_declarations=[...])]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.resource.a2a.protocol import A2APeer


# ---------------------------------------------------------------------------
# Anthropic tool definitions
# ---------------------------------------------------------------------------

def to_anthropic_tools(peers: list[A2APeer]) -> list[dict[str, Any]]:
    """Convert peers to Anthropic tool definitions.

    Each peer becomes a tool that accepts a single ``message`` string input.
    Claude will call the tool when it decides to delegate to that peer.

    Args:
        peers (list[A2APeer]): Declared peer agents to expose as tools.

    Returns:
        list[dict[str, Any]]: Anthropic-format tool definitions, one per peer.
    """
    return [
        {
            "name": _safe_tool_name(peer.name),
            "description": peer.description or f"Delegate to the '{peer.name}' agent.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": f"The task or question to send to the '{peer.name}' agent.",
                    }
                },
                "required": ["message"],
            },
        }
        for peer in peers
    ]


def handle_anthropic_tool_call(
    tool_name: str,
    tool_input: dict[str, Any],
    peers: list[A2APeer],
) -> str | None:
    """Execute the peer agent for an Anthropic tool_use block.

    Args:
        tool_name (str): Name of the tool Claude invoked.
        tool_input (dict[str, Any]): Tool input payload; expects a ``message`` key.
        peers (list[A2APeer]): Declared peer agents available for delegation.

    Returns:
        str | None: The peer's output string, or None if tool_name doesn't match
            any peer.
    """
    peer_map = {_safe_tool_name(p.name): p for p in peers}
    peer = peer_map.get(tool_name)
    if peer is None:
        return None
    message: str = tool_input.get("message", "")
    return cast(str, peer.agent.run(message))


# ---------------------------------------------------------------------------
# OpenAI handoff definitions (openai-agents SDK)
# ---------------------------------------------------------------------------

def to_openai_handoffs(peers: list[A2APeer]) -> list[Any]:
    """Convert peers to openai-agents SDK Agent objects for use as handoffs.

    The inner Agent wraps the peer via a run_sync shim so the SDK's handoff
    mechanism transparently calls our AbstractBaseAgent.run().

    Args:
        peers (list[A2APeer]): Declared peer agents to expose as handoffs.

    Returns:
        list[Any]: openai-agents SDK Agent objects, one per peer. Returns an
            empty list if the ``agents`` package is not installed.
    """
    try:
        from agents import Agent
    except ImportError:
        return []

    handoffs = []
    for peer in peers:
        # Capture peer in closure
        _peer = peer

        class _PeerHandoffAgent(Agent):  # type: ignore[misc]
            """Placeholder Agent subclass used to bind a peer to a handoff."""

        handoff_agent = Agent(
            name=_peer.name,
            instructions=_peer.description or f"Peer agent: {_peer.name}",
        )
        # Attach the actual run callable so the SDK's runner can invoke it
        handoff_agent._a2a_peer = _peer
        handoffs.append(handoff_agent)
    return handoffs


# ---------------------------------------------------------------------------
# Gemini FunctionDeclaration definitions
# ---------------------------------------------------------------------------

def to_gemini_tools(peers: list[A2APeer]) -> list[Any]:
    """Convert peers to Gemini FunctionDeclaration tools.

    Args:
        peers (list[A2APeer]): Declared peer agents to expose as function tools.

    Returns:
        list[Any]: A list containing a single ``genai.protos.Tool`` that can be
            passed directly to ``GenerativeModel(tools=...)``. Returns an empty
            list if ``google.generativeai`` is not installed or no peers are
            declared.
    """
    try:
        import google.generativeai as genai
        import google.generativeai.protos as protos
    except ImportError:
        return []

    declarations = []
    for peer in peers:
        declarations.append(
            protos.FunctionDeclaration(
                name=_safe_tool_name(peer.name),
                description=peer.description or f"Delegate to the '{peer.name}' agent.",
                parameters=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "message": protos.Schema(
                            type=protos.Type.STRING,
                            description=f"Task to send to '{peer.name}'.",
                        )
                    },
                    required=["message"],
                ),
            )
        )

    if not declarations:
        return []
    return [genai.protos.Tool(function_declarations=declarations)]


def handle_gemini_function_call(
    function_name: str,
    function_args: dict[str, Any],
    peers: list[A2APeer],
) -> str | None:
    """Execute the peer agent for a Gemini function_call part.

    Args:
        function_name (str): Name of the function Gemini invoked.
        function_args (dict[str, Any]): Function call arguments; expects a
            ``message`` key.
        peers (list[A2APeer]): Declared peer agents available for delegation.

    Returns:
        str | None: The peer's output string, or None if function_name doesn't
            match any peer.
    """
    peer_map = {_safe_tool_name(p.name): p for p in peers}
    peer = peer_map.get(function_name)
    if peer is None:
        return None
    message: str = function_args.get("message", "")
    return cast(str, peer.agent.run(message))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_tool_name(name: str) -> str:
    """Normalize a peer name to a valid tool identifier.

    Args:
        name (str): Raw peer name, e.g. "Fact Checker".

    Returns:
        str: Lowercase identifier with spaces/hyphens replaced by underscores.
    """
    return name.strip().replace(" ", "_").replace("-", "_").lower()
