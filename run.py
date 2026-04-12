#!/usr/bin/env python3
"""
XDART-Φ × XHEART — Runner

Usage:
  python run.py "Why do organizations fail to change?"
  python run.py --interactive
  python run.py --server
  python run.py --server --port 8000

«Δεν χρειαζόμαστε LLMs που ξέρουν περισσότερα.
 Χρειαζόμαστε LLMs που βλέπουν βαθύτερα.»

© Panos Skouras — Salimov MON IKE, 2026
"""

import argparse
import io
import json
import logging
import sys

# ── Force UTF-8 on Windows console (fixes Greek / non-ASCII in logs) ──
if sys.platform == "win32":
    import ctypes
    # Tell the Windows console to interpret output bytes as UTF-8
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)
    # Tell Python to encode output as UTF-8
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
        else:
            setattr(
                sys,
                stream_name,
                io.TextIOWrapper(
                    getattr(sys, stream_name).buffer,
                    encoding="utf-8",
                    errors="replace",
                ),
            )

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s │ %(name)-25s │ %(levelname)-5s │ %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    logging.basicConfig(level=level, handlers=[handler])
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def print_banner() -> None:
    console.print()
    console.print(
        Panel(
            "[bold gold1]XDART-Φ × XHEART[/]\n"
            "[dim]Epistemological Architecture for AI Reasoning[/]\n\n"
            "[italic]«Δεν χρειαζόμαστε LLMs που ξέρουν περισσότερα.\n"
            " Χρειαζόμαστε LLMs που βλέπουν βαθύτερα.»[/]",
            border_style="gold1",
            padding=(1, 4),
        )
    )
    console.print()


def run_problem(problem: str, verbose: bool = False) -> None:
    """Run the full framework on a single problem."""
    from xdart.core import XDARTFramework

    framework = XDARTFramework()

    phase_names = {
        "phase0_ontology": "Φ  Ontological Grounding",
        "phase1_xdart": "01 XDART-Φ Cross-Domain",
        "phase2_views": "02 Multiple Views",
        "phase3_xheart": "♥  XHEART Distillation",
        "phase4_memory": "∞  Episodic Memory",
    }

    current_phase = {"name": "Initializing..."}

    def on_phase(name: str, _result) -> None:
        current_phase["name"] = phase_names.get(name, name)

    with Progress(
        SpinnerColumn(style="gold1"),
        TextColumn("[bold]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Processing...", total=None)

        def callback(name, result):
            on_phase(name, result)
            progress.update(task, description=phase_names.get(name, name))

        result = framework.run(problem, callback=callback)
        progress.update(task, description="Complete ✓")

    # ── Display results ──
    console.print()

    # Phase 0
    console.print(
        Panel(
            f"[dim]Original:[/] {result.problem}\n\n"
            f"[bold]Reframed:[/] {result.phase0_ontology.reframed_problem}",
            title="[gold1]Φ — ONTOLOGICAL GROUNDING[/]",
            border_style="dim",
        )
    )

    # Phase 1
    domain_table = Table(show_header=True, header_style="bold gold1", border_style="dim")
    domain_table.add_column("Domain", style="bold")
    domain_table.add_column("Strength")
    domain_table.add_column("Dist", justify="center")
    domain_table.add_column("Spec", justify="center")
    domain_table.add_column("Transfer Hypothesis")

    for d in result.phase1_xdart.domains_analyzed:
        strength_color = {
            "STRONG": "green", "WEAK": "yellow", "NONE": "red"
        }.get(d.analogy_strength.value, "white")

        domain_table.add_row(
            d.domain,
            f"[{strength_color}]{d.analogy_strength.value}[/]",
            str(d.domain_distance),
            str(d.mechanistic_specificity),
            d.transfer_hypothesis[:80],
        )

    console.print(Panel(domain_table, title="[gold1]01 — XDART-Φ CROSS-DOMAIN[/]", border_style="dim"))

    if result.phase1_xdart.layer_3_hypothesis:
        console.print(
            Panel(
                f"[bold red]Layer-3 Hypothesis:[/] {result.phase1_xdart.layer_3_hypothesis}",
                border_style="red",
            )
        )

    # Phase 2
    views_text = ""
    for v in result.phase2_views.views_applied:
        views_text += f"**[{v.view_id}] {v.view_name}:** {v.insight}\n"
        views_text += f"*→ Reveals: {v.reveals_hidden}*\n\n"

    if result.phase2_views.convergent_patterns:
        views_text += "**Convergent Patterns:**\n"
        for p in result.phase2_views.convergent_patterns:
            views_text += f"- {p}\n"

    views_text += f"\n**Dominant:** {result.phase2_views.dominant_pattern}"

    console.print(
        Panel(
            Markdown(views_text),
            title="[gold1]02 — MULTIPLE VIEWS[/]",
            border_style="dim",
        )
    )

    # XHEART — internal state indicator (NOT the actual content)
    synthesis_status = (
        "[green]✓ Synthesis survived — Layer-3 confirmed[/]"
        if result.phase3_xheart.synthesis
        else "[yellow]⚠ No synthesis — speculation only[/]"
    )
    console.print(
        Panel(
            f"[dim]XHEART internal state processed (not shown — shapes output)[/]\n"
            f"Dialectical status: {synthesis_status}",
            title="[bold red]♥ — XHEART[/]",
            border_style="red",
        )
    )

    # Final Output — THE distillate
    console.print()
    console.print(
        Panel(
            f"[bold]{result.final_output}[/]\n\n"
            f"[dim italic]Falsifiability: {result.falsifiability}[/]",
            title=f"[bold gold1]◈ FINAL OUTPUT — {result.layer.value}[/]",
            border_style="gold1",
            padding=(1, 3),
        )
    )

    # Memory
    console.print(
        f"\n  [dim blue]∞ Stored in episodic memory "
        f"(total experiences: {framework.memory.entry_count})[/]"
    )
    console.print()

    # Export option
    if verbose:
        export = result.model_dump(mode="json")
        export["phase3_xheart"] = "[INTERNAL — not exported]"
        console.print(Panel(json.dumps(export, indent=2, ensure_ascii=False)[:3000], title="Raw JSON"))


def interactive_mode(verbose: bool = False) -> None:
    """Interactive REPL mode."""
    print_banner()
    console.print("[dim]Type a problem and press Enter. Type 'quit' to exit.[/]\n")

    while True:
        try:
            problem = console.input("[gold1]› [/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/]")
            break

        if not problem:
            continue
        if problem.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye.[/]")
            break

        run_problem(problem, verbose=verbose)


def start_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start FastAPI server."""
    import uvicorn
    print_banner()
    console.print(f"[bold]Starting API server on {host}:{port}[/]\n")
    uvicorn.run("xdart.api:app", host=host, port=port, reload=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="XDART-Φ × XHEART — Epistemological Architecture for AI Reasoning"
    )
    parser.add_argument("problem", nargs="?", help="Problem to analyze")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--server", "-s", action="store_true", help="Start API server")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.server:
        start_server(args.host, args.port)
    elif args.interactive:
        interactive_mode(args.verbose)
    elif args.problem:
        print_banner()
        if args.json:
            from xdart.core import XDARTFramework
            fw = XDARTFramework()
            result = fw.run(args.problem)
            output = result.model_dump(mode="json")
            output["phase3_xheart"] = "[INTERNAL]"
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            run_problem(args.problem, verbose=args.verbose)
    else:
        interactive_mode(args.verbose)


if __name__ == "__main__":
    main()
