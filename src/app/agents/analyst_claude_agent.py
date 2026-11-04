"""Claude-backed analyst agent — delegates fact-checking to a Gemini peer via A2A."""

from __future__ import annotations

from pydantic import Field

from src.ai.base_claude import ClaudeBaseAgent


class AnalystClaudeAgent(ClaudeBaseAgent):
    """Analyzes topics in depth; delegates factual verification to a declared peer.

    Typical wiring::

        from src.ai.a2a.protocol import A2APeer
        from src.app.agents.fact_checker_gemini_agent import FactCheckerGeminiAgent

        analyst = AnalystClaudeAgent(
            peers=[A2APeer(
                name="fact_checker",
                description="Verifies factual claims via Gemini",
                agent=FactCheckerGeminiAgent(),
            )]
        )
        result = analyst.run("Analyze the impact of LLMs on software engineering.")
    """

    name: str = Field(default="Analyst")
    description: str = Field(
        default="Performs in-depth analysis and delegates fact verification to peers."
    )
    instructions: str = Field(
        default=(
            "You are a senior research analyst. "
            "When asked to analyze a topic, provide a structured analysis with: "
            "an executive summary, key findings (3-5 bullet points), risks, and a recommendation. "
            "If you have a fact_checker peer available, use it to verify key factual claims "
            "before including them in your analysis."
        )
    )
