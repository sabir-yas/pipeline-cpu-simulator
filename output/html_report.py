from __future__ import annotations
import datetime
from pathlib import Path
from simulator import CycleSnapshot, PerformanceMetrics
from cpu.instruction import Instruction

STAGE_CSS_CLASS = {
    "IF":  "s-if",
    "ID":  "s-id",
    "EX":  "s-ex",
    "MEM": "s-mem",
    "WB":  "s-wb",
    "---": "s-bubble",
    "***": "s-flush",
    "STA": "s-stall",
}

CSS = """
:root {
  --bg: #0f1117;
  --surface: #1a1d27;
  --border: #2d3148;
  --text: #e2e8f0;
  --muted: #718096;
  --accent: #4299e1;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 14px; line-height: 1.6;
}
.container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
h1 { font-size: 2rem; font-weight: 700; color: var(--accent); margin-bottom: .5rem; }
h2 { font-size: 1.25rem; font-weight: 600; color: var(--accent);
     margin: 2rem 0 .75rem; border-bottom: 1px solid var(--border); padding-bottom: .5rem; }
h3 { font-size: 1rem; font-weight: 600; color: #a0aec0; margin: 1rem 0 .5rem; }
.subtitle { color: var(--muted); margin-bottom: 2rem; }
.badge {
  display: inline-block; padding: .2rem .6rem; border-radius: 4px;
  font-size: .75rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .05em;
}
.badge-on  { background: #1c4532; color: #68d391; }
.badge-off { background: #5c2626; color: #fc8181; }

/* Pipeline diagram */
.pipeline-wrap { overflow-x: auto; }
table.pipeline {
  border-collapse: collapse; font-size: .8rem;
  margin-bottom: 1rem;
}
table.pipeline th, table.pipeline td {
  border: 1px solid var(--border);
  padding: .3rem .5rem; text-align: center;
  white-space: nowrap;
}
table.pipeline th { background: #1e2130; color: var(--accent); }
table.pipeline td.instr-label { text-align: left; font-family: monospace; color: var(--text); min-width: 220px; }
.s-if    { background: #1a3a6b; color: #90cdf4; font-weight: 700; }
.s-id    { background: #4a3800; color: #f6e05e; font-weight: 700; }
.s-ex    { background: #1a4a2e; color: #9ae6b4; font-weight: 700; }
.s-mem   { background: #2d1b5e; color: #d6bcfa; font-weight: 700; }
.s-wb    { background: #003344; color: #76e4f7; font-weight: 700; }
.s-bubble{ background: #1a1d27; color: #4a5568; }
.s-flush { background: #4a1010; color: #fc8181; font-weight: 700; }
.s-stall { background: #2d2a1a; color: #d69e2e; font-weight: 700; }

/* Metrics */
table.metrics {
  border-collapse: collapse; width: 100%;
}
table.metrics th, table.metrics td {
  border: 1px solid var(--border); padding: .5rem .75rem;
}
table.metrics th { background: #1e2130; color: var(--accent); text-align: left; }
table.metrics td { text-align: right; }
table.metrics td.label { text-align: left; color: var(--text); }
.val-green { color: #68d391; font-weight: 700; }
.val-yellow{ color: #f6e05e; font-weight: 700; }
.val-cyan  { color: #76e4f7; font-weight: 700; }
.speedup-row td { border-top: 2px solid var(--accent); }

/* Register trace */
table.regtrace {
  border-collapse: collapse; font-size: .75rem;
  width: 100%;
}
table.regtrace th, table.regtrace td {
  border: 1px solid var(--border); padding: .25rem .4rem; text-align: right;
}
table.regtrace th { background: #1e2130; color: var(--accent); }
table.regtrace td.cycle-label { text-align: center; color: var(--muted); }
.changed { background: #1a3a1a; color: #9ae6b4; }

/* Program listing */
table.listing {
  border-collapse: collapse; width: 100%; font-family: monospace; font-size: .82rem;
}
table.listing th, table.listing td {
  border: 1px solid var(--border); padding: .3rem .6rem;
}
table.listing th { background: #1e2130; color: var(--accent); text-align: left; }
table.listing td.pc   { color: var(--muted); }
table.listing td.text { color: #90cdf4; }

/* Legend */
.legend { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem; }
.legend-item { padding: .2rem .6rem; border-radius: 3px; font-size: .75rem; font-weight: 700; }

/* Tabs for fwd ON/OFF */
.tabs { display: flex; gap: .5rem; margin-bottom: 1rem; }
.tab-btn {
  padding: .4rem 1rem; border: 1px solid var(--border);
  background: var(--surface); color: var(--muted);
  border-radius: 4px; cursor: pointer; font-size: .85rem;
}
.tab-btn.active { background: var(--accent); color: white; border-color: var(--accent); }
.tab-content { display: none; }
.tab-content.active { display: block; }

footer {
  margin-top: 4rem; padding-top: 1rem; border-top: 1px solid var(--border);
  color: var(--muted); font-size: .8rem; text-align: center;
}
"""

JS = """
function switchTab(groupId, tabId) {
  document.querySelectorAll('#' + groupId + ' .tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#' + groupId + ' .tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById(tabId + '-btn').classList.add('active');
  document.getElementById(tabId + '-content').classList.add('active');
}
"""


class HTMLReportGenerator:
    def __init__(self):
        self._sections: list[str] = []
        self._program_name: str = ""

    def add_program_info(self, program_name: str, instructions: list[Instruction]) -> None:
        self._program_name = program_name
        rows = ""
        for i, instr in enumerate(instructions):
            rows += (
                f'<tr><td class="pc">0x{instr.pc:04X}</td>'
                f'<td>{i}</td>'
                f'<td class="text">{instr.raw_text}</td>'
                f'<td>{instr.opcode.name}</td>'
                f'<td>{instr.fmt.value}</td>'
                f'<td>{"✓" if instr.reg_write else ""}</td>'
                f'<td>{"✓" if instr.mem_read else ""}</td>'
                f'<td>{"✓" if instr.mem_write else ""}</td>'
                f'</tr>\n'
            )
        self._sections.append(f"""
<h2>Program Listing — {program_name}</h2>
<table class="listing">
  <thead>
    <tr><th>PC</th><th>#</th><th>Assembly</th><th>Opcode</th><th>Format</th>
        <th>RegWrite</th><th>MemRead</th><th>MemWrite</th></tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
""")

    def add_pipeline_diagram(
        self,
        cycle_log_on: list[CycleSnapshot],
        cycle_log_off: list[CycleSnapshot] | None,
        instructions: list[Instruction],
    ) -> None:
        html_on = self._build_diagram_table(cycle_log_on, instructions, "on")
        tabs = f"""
<h2>Pipeline Execution Diagram</h2>
{self._legend_html()}
<div id="diag-tabs" class="tabs">
  <button class="tab-btn active" id="diag-fwd-on-btn"
          onclick="switchTab('diag-tabs','diag-fwd-on')">
    Forwarding ON
  </button>"""
        if cycle_log_off:
            html_off = self._build_diagram_table(cycle_log_off, instructions, "off")
            tabs += """
  <button class="tab-btn" id="diag-fwd-off-btn"
          onclick="switchTab('diag-tabs','diag-fwd-off')">
    Forwarding OFF
  </button>"""
        tabs += "</div>"
        tabs += f'<div id="diag-fwd-on-content" class="tab-content active pipeline-wrap">{html_on}</div>'
        if cycle_log_off:
            tabs += f'<div id="diag-fwd-off-content" class="tab-content pipeline-wrap">{html_off}</div>'
        self._sections.append(tabs)

    def _build_diagram_table(
        self,
        cycle_log: list[CycleSnapshot],
        instructions: list[Instruction],
        suffix: str,
    ) -> str:
        if not cycle_log:
            return "<p>No data.</p>"
        max_cycle = max(s.cycle for s in cycle_log)

        # Build instr_cycle map same logic as terminal renderer
        instr_cycle: dict[int, dict[int, str]] = {i: {} for i in range(len(instructions))}
        for snap in cycle_log:
            cycle = snap.cycle
            for stage_name, si in snap.stages.items():
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

        header = "<tr><th>Instruction</th>" + "".join(f"<th>{c}</th>" for c in range(1, max_cycle + 1)) + "</tr>\n"
        body = ""
        for idx, instr in enumerate(instructions):
            body += f'<tr><td class="instr-label">{instr.raw_text}</td>'
            for c_num in range(1, max_cycle + 1):
                cell = instr_cycle[idx].get(c_num, "")
                css = STAGE_CSS_CLASS.get(cell, "")
                label = cell if cell not in ("---", "") else ("·" if cell == "---" else "")
                body += f'<td class="{css}">{label}</td>'
            body += "</tr>\n"

        return f'<table class="pipeline"><thead>{header}</thead><tbody>{body}</tbody></table>'

    def _legend_html(self) -> str:
        items = [
            ('<span class="legend-item s-if">IF</span>', "Instruction Fetch"),
            ('<span class="legend-item s-id">ID</span>', "Instruction Decode"),
            ('<span class="legend-item s-ex">EX</span>', "Execute"),
            ('<span class="legend-item s-mem">MEM</span>', "Memory Access"),
            ('<span class="legend-item s-wb">WB</span>', "Write Back"),
            ('<span class="legend-item s-bubble">·</span>', "Bubble"),
            ('<span class="legend-item s-flush">***</span>', "Flushed"),
            ('<span class="legend-item s-stall">STA</span>', "Stalled/Frozen"),
        ]
        parts = "".join(f'{badge} <small style="color:#718096;margin-right:.75rem">{desc}</small>' for badge, desc in items)
        return f'<div class="legend">{parts}</div>'

    def add_metrics(
        self,
        metrics_on: PerformanceMetrics,
        metrics_off: PerformanceMetrics | None,
    ) -> None:
        speedup_row = ""
        if metrics_off and metrics_off.total_cycles > 0:
            speedup = metrics_off.total_cycles / metrics_on.total_cycles
            speedup_row = f"""
<tr class="speedup-row">
  <td class="label"><strong>Speedup (Fwd ON ÷ Fwd OFF cycles)</strong></td>
  <td class="val-cyan">—</td>
  <td class="val-cyan">—</td>
  <td class="val-cyan"><strong>{speedup:.2f}×</strong></td>
</tr>"""

        def v(val, style):
            return f'<td class="{style}">{val}</td>'

        off_cycles   = metrics_off.total_cycles if metrics_off else "—"
        off_retired  = metrics_off.instructions_retired if metrics_off else "—"
        off_cpi      = f"{metrics_off.cpi:.3f}" if metrics_off else "—"
        off_stalls   = metrics_off.stall_count if metrics_off else "—"
        off_flushes  = metrics_off.flush_count if metrics_off else "—"

        self._sections.append(f"""
<h2>Performance Metrics</h2>
<table class="metrics">
  <thead>
    <tr><th>Metric</th><th>Forwarding ON</th><th>Forwarding OFF</th><th>Notes</th></tr>
  </thead>
  <tbody>
    <tr><td class="label">Total Cycles</td>
        {v(metrics_on.total_cycles,'val-green')}
        {v(off_cycles,'val-yellow')}<td>—</td></tr>
    <tr><td class="label">Instructions Retired</td>
        {v(metrics_on.instructions_retired,'val-green')}
        {v(off_retired,'val-yellow')}<td>—</td></tr>
    <tr><td class="label">CPI</td>
        {v(f"{metrics_on.cpi:.3f}",'val-green')}
        {v(off_cpi,'val-yellow')}<td>Lower is better</td></tr>
    <tr><td class="label">Stall Cycles</td>
        {v(metrics_on.stall_count,'val-green')}
        {v(off_stalls,'val-yellow')}<td>—</td></tr>
    <tr><td class="label">Flush Cycles (branch penalty)</td>
        {v(metrics_on.flush_count,'val-green')}
        {v(off_flushes,'val-yellow')}<td>Always 2/taken branch</td></tr>
    {speedup_row}
  </tbody>
</table>
""")

    def add_register_trace(self, cycle_log: list[CycleSnapshot]) -> None:
        if not cycle_log:
            return
        # Show only registers that ever change
        all_regs = list(cycle_log[0].reg_snapshot.keys())
        changed_regs = [
            r for r in all_regs
            if r != "XZR" and any(
                s.reg_snapshot[r] != 0 for s in cycle_log
            )
        ]
        if not changed_regs:
            return

        header = "<tr><th>Cycle</th>" + "".join(f"<th>{r}</th>" for r in changed_regs) + "</tr>\n"
        body = ""
        prev = {r: 0 for r in changed_regs}
        for snap in cycle_log:
            body += f'<tr><td class="cycle-label">{snap.cycle}</td>'
            for r in changed_regs:
                val = snap.reg_snapshot[r]
                changed = val != prev[r]
                cls = "changed" if changed else ""
                body += f'<td class="{cls}">{val if val != 0 else "·"}</td>'
                prev[r] = val
            body += "</tr>\n"

        self._sections.append(f"""
<h2>Register Value Trace</h2>
<p style="color:var(--muted);margin-bottom:.5rem">
  Highlighted cells indicate value changed this cycle. Only non-zero registers shown.
</p>
<div style="overflow-x:auto">
<table class="regtrace">
  <thead>{header}</thead>
  <tbody>{body}</tbody>
</table>
</div>
""")

    def add_memory_state(self, mem_snapshot: dict[int, int]) -> None:
        if not mem_snapshot:
            return
        rows = "".join(
            f'<tr><td>0x{addr:04X}</td><td>{val}</td><td>0x{val:016X}</td></tr>'
            for addr, val in mem_snapshot.items()
        )
        self._sections.append(f"""
<h2>Final Data Memory State</h2>
<table class="metrics">
  <thead><tr><th>Address</th><th>Value (dec)</th><th>Value (hex)</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
""")

    def generate(self, output_path: str, forwarding_on: bool = True) -> None:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        fwd_badge = (
            '<span class="badge badge-on">Forwarding ON</span>'
            if forwarding_on else
            '<span class="badge badge-off">Forwarding OFF</span>'
        )
        body = "\n".join(self._sections)
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LEGv8 Pipeline Simulator Report — {self._program_name}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <h1>LEGv8 Pipeline CPU Simulator</h1>
  <p class="subtitle">
    CSCI 4591 Computer Architecture · Honors Project · CU Denver &nbsp;|&nbsp;
    Program: <strong>{self._program_name}</strong> &nbsp;|&nbsp;
    {fwd_badge} &nbsp;|&nbsp;
    Generated: {now}
  </p>
  {body}
  <footer>
    LEGv8 5-Stage Pipeline CPU Simulator · Yaseer Sabir · CSCI 4591 Honors Contract
  </footer>
</div>
<script>{JS}</script>
</body>
</html>"""
        Path(output_path).write_text(html, encoding="utf-8")
