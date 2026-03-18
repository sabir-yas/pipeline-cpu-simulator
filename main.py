from __future__ import annotations
import sys
import copy
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.rule import Rule
from rich import box

from utils.assembler import Assembler, AssemblerError
from simulator import PipelineSimulator, SimulationConfig, PerformanceMetrics
from output.terminal import TerminalRenderer
from output.html_report import HTMLReportGenerator

PROGRAMS_DIR = Path(__file__).parent / "programs"
console = Console()
renderer = TerminalRenderer(console)


# ── Helpers ───────────────────────────────────────────────────────────────────

def clear():
    console.print()


def list_programs() -> list[Path]:
    return sorted(PROGRAMS_DIR.glob("*.asm"))


def show_menu(
    programs: list[Path],
    selected_idx: int | None,
    forwarding: bool,
    run_mode: str,
    html: bool,
) -> None:
    console.clear()
    renderer.render_banner()

    # Status row
    prog_name = programs[selected_idx].name if selected_idx is not None else "[dim]none selected[/dim]"
    fwd_badge = "[bold green]ON[/bold green]" if forwarding else "[bold red]OFF[/bold red]"
    mode_badge = "[cyan]step-by-step[/cyan]" if run_mode == "step" else "[cyan]full run[/cyan]"
    html_badge = "[green]YES[/green]" if html else "[dim]no[/dim]"

    status = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    status.add_column("k", style="bold white")
    status.add_column("v")
    status.add_row("Program",    prog_name)
    status.add_row("Forwarding", fwd_badge)
    status.add_row("Run mode",   mode_badge)
    status.add_row("HTML report", html_badge)
    console.print(Panel(status, title="[bold cyan]Current Settings[/bold cyan]",
                        border_style="bright_black"))
    console.print()

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold cyan", width=4)
    table.add_column("Action", style="white")
    table.add_row("1", "Select program")
    table.add_row("2", f"Toggle forwarding  (currently: {fwd_badge})")
    table.add_row("3", f"Toggle run mode    (currently: {mode_badge})")
    table.add_row("4", f"Toggle HTML report (currently: {html_badge})")
    table.add_row("5", "[bold green]▶  RUN SIMULATION[/bold green]")
    table.add_row("6", "[dim]Exit[/dim]")
    console.print(Panel(table, title="[bold cyan]Menu[/bold cyan]", border_style="bright_black"))
    console.print()


def select_program(programs: list[Path]) -> int | None:
    if not programs:
        console.print("[red]No .asm files found in programs/ directory.[/red]")
        return None
    console.print(Rule("[bold]Select Program[/bold]", style="cyan"))
    for i, p in enumerate(programs, 1):
        console.print(f"  [bold cyan]{i}[/bold cyan]. {p.name}")
    console.print(f"  [bold cyan]0[/bold cyan]. Cancel")
    console.print()
    choice = Prompt.ask("Enter number", default="0")
    try:
        idx = int(choice)
        if idx == 0:
            return None
        if 1 <= idx <= len(programs):
            return idx - 1
    except ValueError:
        pass
    console.print("[red]Invalid choice.[/red]")
    return None


def assemble_program(path: Path) -> list | None:
    try:
        source = path.read_text(encoding="utf-8")
        asm = Assembler()
        instructions = asm.assemble(source)
        console.print(f"\n[green]✓ Assembled {len(instructions)} instructions from {path.name}[/green]")
        return instructions
    except AssemblerError as e:
        console.print(f"\n[red]Assembler error: {e}[/red]")
        return None


def show_assembled(instructions) -> None:
    console.print()
    table = Table(title="Assembled Program", box=box.ROUNDED, show_lines=False,
                  header_style="bold white on #1a1a2e")
    table.add_column("#",  justify="right", width=4)
    table.add_column("PC", width=8)
    table.add_column("Assembly", style="cyan")
    table.add_column("Opcode", style="yellow", width=8)
    table.add_column("Format", width=6)
    for i, instr in enumerate(instructions):
        table.add_row(
            str(i),
            f"0x{instr.pc:04X}",
            instr.raw_text,
            instr.opcode.name,
            instr.fmt.value,
        )
    console.print(table)
    console.print()


def run_step_mode(sim: PipelineSimulator) -> None:
    console.print(Rule("[bold]Step-by-Step Mode[/bold]  (Enter=next  q=finish)", style="cyan"))
    console.print()
    while not sim.halted and sim.metrics.total_cycles < sim.config.max_cycles:
        snap = sim.step()
        renderer.render_cycle(snap)
        if sim.halted:
            break
        try:
            key = console.input("[dim]Press Enter for next cycle (q to finish):[/dim] ")
            if key.strip().lower() == "q":
                break
        except (EOFError, KeyboardInterrupt):
            break
    # Drain pipeline
    for _ in range(4):
        if not sim.halted:
            snap = sim.step()
            renderer.render_cycle(snap)
        else:
            sim.step()
    sim.metrics.compute()


def run_simulation(
    instructions,
    forwarding: bool,
    run_mode: str,
    generate_html: bool,
    program_name: str,
) -> None:
    console.print()
    console.print(Rule(f"[bold]Running: {program_name}[/bold]", style="cyan"))

    # Primary run
    config = SimulationConfig(forwarding_enabled=forwarding, program_name=program_name)
    sim = PipelineSimulator(config)
    sim.load_program(copy.deepcopy(instructions))

    if run_mode == "step":
        run_step_mode(sim)
    else:
        console.print("[dim]Simulating...[/dim]")
        sim.run()

    metrics_primary = sim.metrics

    # Comparison run (opposite forwarding setting)
    config_alt = SimulationConfig(forwarding_enabled=not forwarding, program_name=program_name)
    sim_alt = PipelineSimulator(config_alt)
    sim_alt.load_program(copy.deepcopy(instructions))
    sim_alt.run()
    metrics_alt = sim_alt.metrics

    # Decide which is "on" and "off" for display
    if forwarding:
        m_on, m_off = metrics_primary, metrics_alt
        log_on, log_off = sim.cycle_log, sim_alt.cycle_log
    else:
        m_on, m_off = metrics_alt, metrics_primary
        log_on, log_off = sim_alt.cycle_log, sim.cycle_log

    # Terminal output
    renderer.render_pipeline_diagram(sim.cycle_log, instructions)
    renderer.render_metrics(m_on, m_off, forwarding_on=True)
    renderer.render_registers(sim.regfile.snapshot())
    renderer.render_memory(sim.dmem.snapshot())

    # HTML report
    if generate_html:
        output_file = f"report_{program_name.replace('.asm','')}.html"
        report = HTMLReportGenerator()
        report.add_program_info(program_name, instructions)
        report.add_pipeline_diagram(log_on, log_off, instructions)
        report.add_metrics(m_on, m_off)
        report.add_register_trace(log_on)
        report.add_memory_state(sim_alt.dmem.snapshot() if not forwarding else sim.dmem.snapshot())
        report.generate(output_file, forwarding_on=True)
        console.print(f"[bold green]✓ HTML report saved to:[/bold green] [cyan]{output_file}[/cyan]")
        console.print()


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    programs = list_programs()
    selected_idx: int | None = None
    forwarding = True
    run_mode = "full"
    html = True

    while True:
        show_menu(programs, selected_idx, forwarding, run_mode, html)
        choice = Prompt.ask("[bold cyan]Choice[/bold cyan]", default="5")

        match choice.strip():
            case "1":
                idx = select_program(programs)
                if idx is not None:
                    selected_idx = idx

            case "2":
                forwarding = not forwarding

            case "3":
                run_mode = "step" if run_mode == "full" else "full"

            case "4":
                html = not html

            case "5":
                if selected_idx is None:
                    console.print("[yellow]Please select a program first (option 1).[/yellow]")
                    console.input("Press Enter to continue...")
                    continue
                path = programs[selected_idx]
                instructions = assemble_program(path)
                if instructions is None:
                    console.input("Press Enter to continue...")
                    continue
                show_assembled(instructions)
                run_simulation(instructions, forwarding, run_mode, html, path.name)
                console.input("\n[dim]Press Enter to return to menu...[/dim]")

            case "6" | "q" | "exit":
                console.print("\n[dim]Goodbye.[/dim]\n")
                sys.exit(0)

            case _:
                pass


if __name__ == "__main__":
    main()
