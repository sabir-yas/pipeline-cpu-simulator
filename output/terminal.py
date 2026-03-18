from __future__ import annotations
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich import box
from simulator import CycleSnapshot, PerformanceMetrics, StageInfo
from cpu.instruction import Instruction

# ── Color palette ─────────────────────────────────────────────────────────────
STAGE_STYLE = {
    "IF":    ("bold white on #0d6efd", "IF "),
    "ID":    ("bold black on #ffc107", "ID "),
    "EX":    ("bold white on #198754", "EX "),
    "MEM":   ("bold white on #6f42c1", "MEM"),
    "WB":    ("bold black on #0dcaf0", "WB "),
    "---":   ("dim white on #333333", "---"),  # bubble
    "***":   ("bold white on #dc3545", "***"),  # flush
    "stall": ("dim white on #555555", "STA"),   # stall hold
}


def _stage_text(stage: StageInfo) -> Text:
    """Return a rich Text for a cell in the pipeline diagram."""
    if stage.is_flush:
        style, label = STAGE_STYLE["***"]
    elif stage.is_stall:
        style, label = STAGE_STYLE["stall"]
    elif stage.is_bubble:
        style, label = STAGE_STYLE["---"]
    else:
        style, label = STAGE_STYLE.get(stage.name, ("white", stage.name))
    return Text(label, style=style)


class TerminalRenderer:
    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    # ── Banner ────────────────────────────────────────────────────────────────

    def render_banner(self) -> None:
        self.console.print()
        self.console.print(Panel.fit(
            "[bold cyan]LEGv8 5-Stage Pipeline CPU Simulator[/bold cyan]\n"
            "[dim]Honors Project · CSCI 4591 · CU Denver[/dim]",
            border_style="cyan",
            padding=(1, 4),
        ))
        self.console.print()

    # ── Cycle panel (step mode) ───────────────────────────────────────────────

    def render_cycle(self, snap: CycleSnapshot) -> None:
        c = self.console
        flags = []
        if snap.stalled:
            flags.append("[bold yellow]STALL[/bold yellow]")
        if snap.flushed:
            flags.append("[bold red]FLUSH[/bold red]")
        flag_str = "  ".join(flags) if flags else "[dim]─[/dim]"

        c.print(Rule(
            f"[bold]Cycle {snap.cycle}[/bold]  PC=0x{snap.pc:04X}  {flag_str}",
            style="bright_black",
        ))

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Stage", style="bold", width=5)
        table.add_column("Instruction", width=38)
        table.add_column("Notes", width=28)

        stage_order = ["WB", "MEM", "EX", "ID", "IF"]
        for sname in stage_order:
            si = snap.stages[sname]
            notes = []
            if si.forward_a:
                notes.append(f"[cyan]FwdA←{si.forward_a}[/cyan]")
            if si.forward_b:
                notes.append(f"[cyan]FwdB←{si.forward_b}[/cyan]")
            if si.is_flush:
                notes.append("[red]flushed[/red]")
            if si.is_stall:
                notes.append("[yellow]frozen[/yellow]")
            if si.is_bubble:
                notes.append("[dim]bubble[/dim]")

            style, _ = STAGE_STYLE.get(sname, ("white", sname))
            if si.is_flush:
                style = STAGE_STYLE["***"][0]
            elif si.is_bubble or si.is_stall:
                style = STAGE_STYLE["---"][0]

            table.add_row(
                Text(sname, style=style),
                Text(si.instruction[:38], style="white" if not si.is_bubble else "dim"),
                Text("  ".join(notes)),
            )

        c.print(table)
        self._render_reg_row(snap)
        c.print()

    def _render_reg_row(self, snap: CycleSnapshot) -> None:
        """Print a compact register summary (non-zero regs only)."""
        non_zero = {k: v for k, v in snap.reg_snapshot.items() if v != 0 and k != "XZR"}
        if not non_zero:
            self.console.print("[dim]  Registers: (all zero)[/dim]")
            return
        parts = [f"[bold cyan]{k}[/bold cyan]=[yellow]{v}[/yellow]" for k, v in list(non_zero.items())[:12]]
        self.console.print("  " + "  ".join(parts))

    # ── Pipeline diagram (classic instruction×cycle grid) ─────────────────────

    def render_pipeline_diagram(
        self,
        cycle_log: list[CycleSnapshot],
        instructions: list[Instruction],
    ) -> None:
        c = self.console
        c.print()
        c.print(Rule("[bold]Pipeline Execution Diagram[/bold]", style="cyan"))
        c.print()

        if not cycle_log:
            c.print("[dim]No cycles recorded.[/dim]")
            return

        # Build instruction → list of (cycle, stage_name, StageInfo)
        # We track which instruction label appears in which stage at each cycle
        total_cycles = len(cycle_log)
        instr_labels = [i.raw_text[:30] for i in instructions]

        # Map: instr_index -> dict[cycle -> cell_label]
        instr_cycle: dict[int, dict[int, str]] = {i: {} for i in range(len(instructions))}

        # Stage order in pipeline progression
        stage_order = ["IF", "ID", "EX", "MEM", "WB"]

        for snap in cycle_log:
            cycle = snap.cycle
            for stage_name, si in snap.stages.items():
                # Find which instruction index this is
                raw = si.instruction
                for idx, instr in enumerate(instructions):
                    if instr.raw_text == raw or str(instr) == raw:
                        if instr_cycle[idx].get(cycle) is None:
                            cell = stage_name
                            if si.is_flush:
                                cell = "***"
                            elif si.is_stall:
                                cell = "STA"
                            elif si.is_bubble:
                                cell = "---"
                            instr_cycle[idx][cycle] = cell
                        break

        table = Table(
            title="[bold cyan]Stage per Cycle[/bold cyan]",
            box=box.ROUNDED,
            show_lines=True,
            header_style="bold white on #1a1a2e",
        )
        table.add_column("Instruction", style="white", no_wrap=True, min_width=28)
        max_cycle = max(s.cycle for s in cycle_log)
        for c_num in range(1, max_cycle + 1):
            table.add_column(str(c_num), justify="center", min_width=4)

        for idx, label in enumerate(instr_labels):
            row_cells = [Text(label, style="white")]
            for c_num in range(1, max_cycle + 1):
                cell = instr_cycle[idx].get(c_num, "")
                if cell in STAGE_STYLE:
                    style, display = STAGE_STYLE[cell]
                    row_cells.append(Text(display.strip(), style=style))
                elif cell == "STA":
                    row_cells.append(Text("STA", style=STAGE_STYLE["stall"][0]))
                else:
                    row_cells.append(Text("", style="dim"))
            table.add_row(*row_cells)

        self.console.print(table)
        self.console.print()
        self._render_legend()

    def _render_legend(self) -> None:
        items = []
        for key, (style, label) in STAGE_STYLE.items():
            if key in ("IF", "ID", "EX", "MEM", "WB"):
                items.append(Text(f" {label.strip()} ", style=style) + Text(f" {key}  "))
        items.append(Text(" --- ", style=STAGE_STYLE["---"][0]) + Text(" bubble  "))
        items.append(Text(" *** ", style=STAGE_STYLE["***"][0]) + Text(" flush  "))
        items.append(Text(" STA ", style=STAGE_STYLE["stall"][0]) + Text(" stall  "))
        self.console.print(Columns(items, equal=False, expand=False))
        self.console.print()

    # ── Metrics table ─────────────────────────────────────────────────────────

    def render_metrics(
        self,
        metrics: PerformanceMetrics,
        metrics_no_fwd: PerformanceMetrics | None = None,
        forwarding_on: bool = True,
    ) -> None:
        c = self.console
        c.print(Rule("[bold]Performance Metrics[/bold]", style="cyan"))
        c.print()

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold white on #1a1a2e")
        table.add_column("Metric", style="bold white", min_width=28)
        table.add_column(
            "Forwarding ON" if forwarding_on else "Current Run",
            justify="right", style="bold green", min_width=16,
        )
        if metrics_no_fwd:
            table.add_column("Forwarding OFF", justify="right", style="bold yellow", min_width=16)
            if metrics_no_fwd.instructions_retired > 0:
                table.add_column("Speedup", justify="right", style="bold cyan", min_width=12)

        def row(label: str, v1, v2=None, extra=None):
            r = [label, str(v1)]
            if v2 is not None:
                r.append(str(v2))
            if extra is not None:
                r.append(str(extra))
            table.add_row(*r)

        row("Total Cycles", metrics.total_cycles,
            metrics_no_fwd.total_cycles if metrics_no_fwd else None)
        row("Instructions Retired", metrics.instructions_retired,
            metrics_no_fwd.instructions_retired if metrics_no_fwd else None)
        row("CPI", f"{metrics.cpi:.3f}",
            f"{metrics_no_fwd.cpi:.3f}" if metrics_no_fwd else None)
        row("Stall Cycles", metrics.stall_count,
            metrics_no_fwd.stall_count if metrics_no_fwd else None)
        row("Flush Cycles (branch penalty)", metrics.flush_count,
            metrics_no_fwd.flush_count if metrics_no_fwd else None)

        if metrics_no_fwd and metrics_no_fwd.total_cycles > 0:
            speedup = metrics_no_fwd.total_cycles / metrics.total_cycles
            table.add_row(
                "[bold cyan]Speedup (fwd ON / fwd OFF)[/bold cyan]",
                "", "",
                f"[bold cyan]{speedup:.2f}×[/bold cyan]",
            )

        c.print(table)
        c.print()

    # ── Register file display ─────────────────────────────────────────────────

    def render_registers(self, reg_snapshot: dict[str, int]) -> None:
        c = self.console
        c.print(Rule("[bold]Final Register State[/bold]", style="cyan"))
        c.print()

        table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold cyan")
        cols = 4
        headers = ["Register", "Value (dec)", "Value (hex)"] * cols
        for h in headers:
            table.add_column(h, justify="right", min_width=12)

        items = [(k, v) for k, v in reg_snapshot.items() if k != "XZR"]
        # Chunk into rows of `cols`
        for start in range(0, len(items), cols):
            chunk = items[start:start + cols]
            row_cells = []
            for name, val in chunk:
                row_cells += [
                    f"[bold cyan]{name}[/bold cyan]",
                    f"[yellow]{val}[/yellow]",
                    f"[dim]0x{val:016X}[/dim]",
                ]
            # Pad if needed
            while len(row_cells) < cols * 3:
                row_cells += ["", "", ""]
            table.add_row(*row_cells)

        c.print(table)
        c.print()

    # ── Memory display ────────────────────────────────────────────────────────

    def render_memory(self, mem_snapshot: dict[int, int]) -> None:
        if not mem_snapshot:
            return
        c = self.console
        c.print(Rule("[bold]Data Memory State[/bold]", style="cyan"))
        c.print()
        table = Table(box=box.SIMPLE_HEAD, header_style="bold cyan")
        table.add_column("Address", justify="right")
        table.add_column("Value (dec)", justify="right")
        table.add_column("Value (hex)", justify="right")
        for addr, val in mem_snapshot.items():
            table.add_row(
                f"[cyan]0x{addr:04X}[/cyan]",
                f"[yellow]{val}[/yellow]",
                f"[dim]0x{val:016X}[/dim]",
            )
        c.print(table)
        c.print()
