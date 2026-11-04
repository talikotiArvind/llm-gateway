"""Anthropic Claude provider base — inherits AbstractBaseAgent."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import Field

from src.resource.base_agent import AbstractBaseAgent

load_dotenv()


class ClaudeBaseAgent(AbstractBaseAgent):
    """Base for all Claude-backed agents.

    Extends AbstractBaseAgent with:
    - Vault (Second Brain) read/write integration
    - A2A peer injection as native Anthropic tool definitions
    - Backward-compatible run(message, project_id) signature
    """

    model: str = Field(default="claude-sonnet-4-6", description="Claude model to use")

    # Second Brain integration (optional)
    retriever: object | None = Field(default=None, exclude=True)
    role_topic: str = Field(default="", exclude=True)
    vault_folder: str = Field(default="", exclude=True)
    agent_name: str = Field(default="", exclude=True)

    # ------------------------------------------------------------------
    # Second Brain hooks
    # ------------------------------------------------------------------

    def _get_vault_context(self) -> str:
        """Fetch relevant Second Brain notes for this agent's role topic.

        Returns:
            str: Formatted vault context to prepend to the system prompt, or an
                empty string when no retriever/topic is configured or the query
                fails/returns nothing.
        """
        if self.retriever is None or not self.role_topic:
            return ""
        try:
            context = self.retriever.query(self.role_topic, top_k=3)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return ""
        if not context:
            return ""
        return (
            "\n## Relevant Knowledge from Second Brain\n"
            "The following notes from past projects are relevant to your task.\n"
            "Use them as reference — do not repeat them verbatim.\n\n"
            f"{context}\n\n---\n"
        )

    def _write_to_vault(self, output: str, project_id: str) -> None:
        """Persist the agent's output as a note in the Second Brain vault.

        Silently no-ops when no retriever/vault_folder is configured or the
        write fails.

        Args:
            output (str): The agent's generated output text to store.
            project_id (str): Identifier of the project this output belongs to.
        """
        if self.retriever is None or not self.vault_folder:
            return
        _agent_name = self.agent_name or self.name.lower().replace(" ", "_")
        try:
            self.retriever.write_note(  # type: ignore[attr-defined]
                title=f"{project_id}-{_agent_name}",
                content=output,
                folder=self.vault_folder,
                metadata={
                    "agent": _agent_name,
                    "project": project_id,
                    "date": datetime.utcnow().isoformat(),
                    "tags": ["second-brain", _agent_name, project_id],
                    "status": "draft",
                },
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # A2A tool injection helpers
    # ------------------------------------------------------------------

    def _build_anthropic_tools(self) -> list[dict[str, Any]]:
        """Build Anthropic tool definitions for this agent's declared peers.

        Returns:
            list[dict[str, Any]]: Anthropic tool definitions, or an empty list
                when no peers are declared.
        """
        if not self.peers:
            return []
        from src.resource.a2a.tool_adapter import to_anthropic_tools
        return to_anthropic_tools(self.peers)

    def _handle_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute the peer agent targeted by an Anthropic tool_use block.

        Args:
            tool_name (str): Name of the tool Claude invoked.
            tool_input (dict[str, Any]): Tool input payload; expects a
                ``message`` key.

        Returns:
            str: The peer's output, or a placeholder string if tool_name does
                not match any declared peer.
        """
        from src.resource.a2a.tool_adapter import handle_anthropic_tool_call
        result = handle_anthropic_tool_call(tool_name, tool_input, self.peers)
        if result is None:
            return f"[tool '{tool_name}' not found in peers]"
        return result

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def run(self, message: str, project_id: str = "default", **kwargs: object) -> str:  # type: ignore[override]
        """Execute the agent synchronously via the Anthropic Messages API.

        Auto-injects declared peers as Anthropic tools and runs an agentic
        tool-use loop until Claude produces a final text response. Writes the
        result to the Second Brain vault when vault integration is configured.

        Args:
            message (str): The task or prompt to send to Claude.
            project_id (str): Identifier used when persisting output to the
                vault. Defaults to "default".
            **kwargs (object): Unused; present for interface compatibility.

        Returns:
            str: Claude's final text response.
        """
        vault_context = self._get_vault_context()
        system_prompt = vault_context + self.instructions if vault_context else self.instructions

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        tools = self._build_anthropic_tools()

        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]

        # Agentic tool-use loop: Claude may call peer tools before producing final text
        while True:
            kwargs_call: dict[str, Any] = dict(
                model=self.model,
                max_tokens=8096,
                system=system_prompt,
                messages=messages,
            )
            if tools:
                kwargs_call["tools"] = tools

            response = client.messages.create(**kwargs_call)

            # No tool use — final text response
            if response.stop_reason != "tool_use":
                output: str = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                self._write_to_vault(output, project_id)
                return output

            # Process all tool_use blocks, then feed results back
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    peer_output = self._handle_tool_use(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": peer_output,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})


# Backward-compatible alias — existing concrete agents importing BaseAgent keep working
BaseAgent = ClaudeBaseAgent
