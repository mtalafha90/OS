from __future__ import annotations

import json
from typing import Any


class Agent:
    """Base class for LLM agents that interact with Ollama."""

    def __init__(
        self,
        name: str,
        role_description: str,
        config: Any,
        ollama_client: Any,
    ) -> None:
        self.name = name
        self.role_description = role_description
        self.config = config
        self.ollama = ollama_client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _system_message(self) -> dict:
        return {
            "role": "system",
            "content": (
                f"You are {self.name}, a specialized AI agent within LLM-OS.\n\n"
                f"Your role: {self.role_description}\n\n"
                "Respond concisely and precisely. Produce actionable results only."
            ),
        }

    def _build_user_message(self, task: str, context: str | None) -> str:
        if context:
            return f"Context:\n{context}\n\nTask:\n{task}"
        return task

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, task: str, context: str | None = None) -> str:
        """Send *task* to Ollama with the agent's role-specific system prompt.

        Returns the raw text response from the model.
        """
        messages = [
            self._system_message(),
            {"role": "user", "content": self._build_user_message(task, context)},
        ]
        resp = self.ollama.chat(
            model=self.config.model,
            messages=messages,
        )
        return resp.get("message", {}).get("content", "")

    def run_with_tools(
        self,
        task: str,
        context: str | None = None,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        """Run with tool-calling enabled.

        Returns a tuple of (final_response_text, list_of_tool_calls_made).
        Each element of the tool calls list is a dict with keys:
          ``name``, ``arguments``, ``result``.
        """
        messages = [
            self._system_message(),
            {"role": "user", "content": self._build_user_message(task, context)},
        ]
        tool_calls_made: list[dict] = []

        while True:
            resp = self.ollama.chat(
                model=self.config.model,
                messages=messages,
                tools=tools or [],
            )
            message = resp.get("message", {})
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                final_text = message.get("content", "")
                return final_text, tool_calls_made

            # Append the assistant turn that contains tool_calls
            messages.append(message)

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                # Dispatch through the global registry so agents can use all
                # registered OS tools without importing them explicitly.
                try:
                    from llmos.tools.registry import dispatch_tool
                    result = dispatch_tool(name, args)
                except Exception as exc:
                    result = f"Error executing {name}: {exc}"

                tool_calls_made.append({"name": name, "arguments": args, "result": result})
                messages.append({"role": "tool", "content": result})
