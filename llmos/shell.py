from __future__ import annotations

import json
import os
import platform

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import Config
from .ollama_client import OllamaClient, OllamaError
from .tools import dispatch_tool, get_tool_schemas

_PROMPT_STYLE = Style.from_dict({"prompt": "bold ansicyan"})
_HISTORY_FILE = os.path.expanduser("~/.config/llmos/history")


def _detect_gpu_brief() -> str:
    """Return a one-line GPU summary for the system prompt."""
    import subprocess

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpus = [line.strip() for line in r.stdout.strip().splitlines()]
            return "NVIDIA: " + " | ".join(gpus)
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["rocm-smi", "--showproductname"], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            return "AMD ROCm: " + r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return "No GPU detected (CPU-only mode)"


def _build_system_message(config: Config) -> dict:
    try:
        hostname = os.uname().nodename
    except AttributeError:
        hostname = os.environ.get("COMPUTERNAME", "unknown")
    user = os.environ.get("USER", os.environ.get("USERNAME", "user"))
    cwd = os.getcwd()
    try:
        with open("/etc/os-release") as f:
            os_info = dict(line.strip().split("=", 1) for line in f if "=" in line)
        os_release = os_info.get("PRETTY_NAME", "").strip('"') or platform.platform()
    except Exception:
        os_release = platform.platform()

    gpu_info = _detect_gpu_brief()

    content = config.system_prompt.format(
        hostname=hostname,
        user=user,
        cwd=cwd,
        os_release=os_release,
        gpu_info=gpu_info,
    )
    return {"role": "system", "content": content}


class LLMShell:
    def __init__(self, config: Config, ollama: OllamaClient):
        self.config = config
        self.ollama = ollama
        self.console = Console()
        self.history: list[dict] = []
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        self.session: PromptSession = PromptSession(
            history=FileHistory(_HISTORY_FILE),
            style=_PROMPT_STYLE,
        )

    def _chat(self, user_content: str) -> str:
        """Send a user message and handle tool call loops."""
        self.history.append({"role": "user", "content": user_content})
        messages = [_build_system_message(self.config)] + self.history

        tools = get_tool_schemas()

        while True:
            resp = self.ollama.chat(
                model=self.config.model,
                messages=messages,
                tools=tools,
            )
            message = resp.get("message", {})
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                content = message.get("content", "")
                self.history.append({"role": "assistant", "content": content})
                if len(self.history) > self.config.max_history * 2:
                    self.history = self.history[-self.config.max_history * 2 :]
                return content

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

                if self.config.show_tool_calls:
                    arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
                    self.console.print(f"[dim cyan]  ↳ {name}({arg_str})[/]")

                result = dispatch_tool(name, args)

                if self.config.show_tool_calls and result:
                    preview = result[:200] + "…" if len(result) > 200 else result
                    self.console.print(f"[dim]    {preview}[/]")

                messages.append({"role": "tool", "content": result})

    def _print_welcome(self) -> None:
        try:
            self.ollama.list_models()
        except Exception:
            pass
        model_line = (
            f"[dim]Model: [cyan]{self.config.model}[/] | Ollama: {self.config.ollama_url}[/]"
        )
        self.console.print(
            Panel(
                f"[bold cyan]LLM-OS[/]  —  Natural Language Operating System\n{model_line}",
                subtitle="[dim]Type your request in plain English. 'exit' to quit.[/]",
                border_style="cyan",
                expand=False,
            )
        )

    def run(self) -> None:
        self._print_welcome()

        while True:
            try:
                user_input = self.session.prompt([("class:prompt", "llmos> ")]).strip()
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Use 'exit' to quit.[/]")
                continue
            except EOFError:
                self.console.print("\n[yellow]Goodbye.[/]")
                break

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "bye", "shutdown"):
                self.console.print("[yellow]Shutting down LLM-OS. Goodbye.[/]")
                break

            if user_input.lower() in ("clear", "cls"):
                self.console.clear()
                continue

            if user_input.lower() == "history clear":
                self.history.clear()
                self.console.print("[green]Conversation history cleared.[/]")
                continue

            if user_input.lower().startswith("model "):
                new_model = user_input.split(None, 1)[1].strip()
                self.config.model = new_model
                self.console.print(f"[green]Switched to model: {new_model}[/]")
                continue

            if user_input.lower() == "models":
                try:
                    models = self.ollama.list_models()
                    self.console.print(
                        "[cyan]Available models:[/]\n" + "\n".join(f"  • {m}" for m in models)
                    )
                except Exception as e:
                    self.console.print(f"[red]Could not list models: {e}[/]")
                continue

            try:
                with self.console.status("[cyan]Thinking…[/]", spinner="dots"):
                    response = self._chat(user_input)
                if response:
                    self.console.print(Markdown(response))
                self.console.print()
            except OllamaError as e:
                self.console.print(f"[red]Ollama error: {e}[/]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/]")
