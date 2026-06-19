"""LLM-OS entry point."""

from __future__ import annotations

import argparse
import sys

from .config import Config
from .ollama_client import OllamaClient
from .shell import LLMShell


def _wait_for_ollama(client: OllamaClient, model: str, console) -> bool:
    """Ensure Ollama is running and the target model is available."""
    from rich.progress import Progress, SpinnerColumn, TextColumn

    if not client.is_available():
        console.print(
            "[red]Error: Ollama is not running.[/]\n"
            "Start it with:  [cyan]ollama serve[/]\n"
            "Or install:     [cyan]curl -fsSL https://ollama.com/install.sh | sh[/]"
        )
        return False

    models = client.list_models()
    if not any(m.startswith(model.split(":")[0]) for m in models):
        console.print(f"[yellow]Model '{model}' not found. Pulling…[/]")
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                task = progress.add_task(f"Pulling {model}", total=None)
                for status in client.pull_model(model):
                    progress.update(task, description=status[:60])
        except Exception as e:
            console.print(f"[red]Pull failed: {e}[/]")
            return False
        console.print(f"[green]Model '{model}' ready.[/]")

    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llmos",
        description="LLM-OS — natural language shell powered by Ollama",
    )
    parser.add_argument("--model", "-m", default=None, help="Override the default model")
    parser.add_argument("--ollama-url", "-u", default=None, help="Override Ollama URL")
    parser.add_argument("--config", "-c", default=None, help="Path to config file")
    parser.add_argument(
        "--no-tool-output",
        action="store_true",
        help="Hide tool call details",
    )
    parser.add_argument(
        "--cmd",
        "-x",
        metavar="PROMPT",
        help="Run a single prompt non-interactively and exit",
    )
    parser.add_argument(
        "--web",
        "-w",
        action="store_true",
        help="Start the Ubuntu-style web UI instead of the terminal shell",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Web UI port (default: 8080, only used with --web)",
    )
    args = parser.parse_args(argv)

    config = Config.load(args.config)
    if args.model:
        config.model = args.model
    if args.ollama_url:
        config.ollama_url = args.ollama_url
    if args.no_tool_output:
        config.show_tool_calls = False

    from rich.console import Console

    console = Console()

    if args.web:
        try:
            from .webui.server import run as run_web
        except ImportError:
            console.print(
                "[red]Web UI dependencies missing.[/]\n"
                "Install with: [cyan]pip install 'llmos[web]'[/]"
            )
            return 1

        with OllamaClient(base_url=config.ollama_url, timeout=config.request_timeout) as ollama:
            if not _wait_for_ollama(ollama, config.model, console):
                return 1

        url = f"http://localhost:{args.port}"
        console.print(
            f"[bold cyan]LLM-OS Web UI[/] starting at [underline cyan]{url}[/]\n"
            "[dim]Open this URL in your browser. Ctrl+C to stop.[/]"
        )
        try:
            import threading
            import webbrowser

            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        except Exception:
            pass

        run_web(host="0.0.0.0", port=args.port, config=config)
        return 0

    with OllamaClient(base_url=config.ollama_url, timeout=config.request_timeout) as ollama:
        if not _wait_for_ollama(ollama, config.model, console):
            return 1

        shell = LLMShell(config=config, ollama=ollama)

        if args.cmd:
            try:
                response = shell._chat(args.cmd)
                console.print(response)
                return 0
            except Exception as e:
                console.print(f"[red]Error: {e}[/]")
                return 1

        shell.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
