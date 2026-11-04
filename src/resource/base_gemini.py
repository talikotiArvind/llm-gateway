"""Google Gemini provider base — inherits AbstractBaseAgent."""

from __future__ import annotations

import os
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv
from pydantic import Field

from src.resource.base_agent import AbstractBaseAgent

load_dotenv()


class GeminiBaseAgent(AbstractBaseAgent):
    """Base for all Gemini-backed agents.

    Extends AbstractBaseAgent with:
    - google.generativeai GenerativeModel execution
    - A2A peer injection as Gemini FunctionDeclarations
    - Automatic function-call loop when peers are declared
    """

    model: str = Field(default="gemini-2.0-flash", description="Gemini model to use")

    def model_post_init(self, __context: object) -> None:
        """Configure the genai client once per instance.

        Args:
            __context (object): Pydantic post-init context; unused.
        """
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    # ------------------------------------------------------------------
    # A2A tool injection helpers
    # ------------------------------------------------------------------

    def _build_gemini_tools(self) -> list[Any]:
        """Build Gemini Tool objects for this agent's declared peers.

        Returns:
            list[Any]: Gemini Tool objects, or an empty list when no peers are
                declared.
        """
        if not self.peers:
            return []
        from src.resource.a2a.tool_adapter import to_gemini_tools
        return to_gemini_tools(self.peers)

    def _handle_function_call(self, function_name: str, function_args: dict[str, Any]) -> str:
        """Execute the peer agent targeted by a Gemini function_call part.

        Args:
            function_name (str): Name of the function Gemini invoked.
            function_args (dict[str, Any]): Function call arguments; expects a
                ``message`` key.

        Returns:
            str: The peer's output, or a placeholder string if function_name
                does not match any declared peer.
        """
        from src.resource.a2a.tool_adapter import handle_gemini_function_call
        result = handle_gemini_function_call(function_name, function_args, self.peers)
        if result is None:
            return f"[function '{function_name}' not found in peers]"
        return result

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def run(self, message: str, **kwargs: object) -> str:
        """Execute the agent synchronously via a Gemini GenerativeModel chat.

        Auto-injects declared peers as Gemini function tools and handles the
        function-call loop until Gemini produces a final text response.

        Args:
            message (str): The task or prompt to send to Gemini.
            **kwargs (object): Unused; present for interface compatibility.

        Returns:
            str: Gemini's final text response.
        """
        tools = self._build_gemini_tools()

        model_kwargs: dict[str, Any] = dict(
            model_name=self.model,
            system_instruction=self.instructions,
        )
        if tools:
            model_kwargs["tools"] = tools

        gemini_model = genai.GenerativeModel(**model_kwargs)
        chat = gemini_model.start_chat()

        response = chat.send_message(message)

        # Function-call loop: Gemini may request peer calls before final text
        while True:
            # Collect any function_call parts in this response
            function_calls = [
                part.function_call
                for candidate in response.candidates
                for part in candidate.content.parts
                if part.function_call.name
            ]

            if not function_calls:
                break

            # Execute each function call and send results back
            function_responses = []
            for fc in function_calls:
                peer_output = self._handle_function_call(fc.name, dict(fc.args))
                function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fc.name,
                            response={"result": peer_output},
                        )
                    )
                )

            response = chat.send_message(function_responses)

        return str(response.text)


# Backward-compatible alias
BaseAgent = GeminiBaseAgent
