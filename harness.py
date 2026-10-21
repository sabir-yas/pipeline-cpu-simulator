"""Differential validation harness.

Runs every program in programs/ through the Python reference model and the C++ port
(forwarding ON and OFF), diffs register/memory/PC/stall/flush state every cycle, then
injects each C++ fault and checks the diff catches it.

Build first:  g++ -O2 -std=c++17 -static cpp/legv8.cpp -o build/legv8
Run:          python harness.py
"""
from __future__ import annotations
import subprocess
import sys
import tempfile
from pathlib import Path

from cpu.registers import MASK64
from simulator import PipelineSimulator, SimulationConfig
from utils.assembler import Assembler

ROOT = Path(__file__).parent
EXE = ROOT / "build" / ("legv8.exe" if sys.platform == "win32" else "legv8")
FAULTS = [
    "no_fwd_exmem", "no_fwd_memwb", "fwd_priority", "no_load_use_stall", "no_flush",
    "short_flush", "str_no_data_fwd", "cbz_reads_rn", "xzr_writable",
]


def dump_program(instructions) -> str:
    """Decoded program for the C++ sim: 'OP rd rn rm rt imm offset pc', -1 = unused reg."""
    n = lambda r: -1 if r is None else r
    return "".join(
        f"{i.opcode.name} {n(i.rd)} {n(i.rn)} {n(i.rm)} {n(i.rt)} {i.imm} {i.offset} {i.pc}\n"
        for i in instructions
    )


def py_trace(instructions, fwd: bool) -> list[str]:
    sim = PipelineSimulator(SimulationConfig(forwarding_enabled=fwd))
    sim.load_program(instructions)

    stores: list[str] = []
    write = sim.dmem.write
    def logged_write(addr, value):
        stores.append(f"{addr:x}:{value & MASK64:x}")
        write(addr, value)
    sim.dmem.write = logged_write

    lines = []
    while not sim.halted and sim.metrics.total_cycles < sim.config.max_cycles:
        snap = sim.step()
        regs = " ".join(f"x{i}={snap.reg_snapshot[f'X{i}']:x}" for i in range(31))
        lines.append(f"c={snap.cycle} pc={snap.pc} s={int(snap.stalled)} f={int(snap.flushed)} "
                     f"{regs} m={','.join(stores) or '-'}")
        stores.clear()
    m = sim.metrics
    lines.append(f"END cycles={m.total_cycles} retired={m.instructions_retired} "
                 f"stalls={m.stall_count} flushes={m.flush_count}")
    return lines


def cpp_trace(prog: Path, fwd: bool, fault: str = "none") -> list[str]:
    out = subprocess.run([str(EXE), str(prog), str(int(fwd)), fault],
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def first_diff(ref: list[str], dut: list[str]) -> str | None:
    """First mismatching cycle and field, or None if traces are identical."""
    for a, b in zip(ref, dut):
        if a != b:
            fa, fb = a.split(), b.split()
            for x, y in zip(fa, fb):
                if x != y:
                    return f"{fa[0]}: python {x} vs c++ {y}"
            return f"python {a!r} vs c++ {b!r}"
    if len(ref) != len(dut):
        return f"trace length: python {len(ref)} lines vs c++ {len(dut)}"
    return None


def expected_regs(source: str) -> dict[str, int]:
    """Hand-computed '// EXPECT X1=10 X2=20' line; every register not listed must be 0."""
    exp = {}
    for line in source.splitlines():
        if line.startswith("// EXPECT"):
            for kv in line.split()[2:]:
                reg, val = kv.split("=")
                exp[reg.lower()] = int(val, 0)
    return exp


def check_expected(ref: list[str], exp: dict[str, int]) -> str | None:
    """Final register state of the reference model vs hand-computed values."""
    final = dict(kv.split("=") for kv in ref[-2].split() if kv.startswith("x"))
    bad = [f"{r}={int(v, 16)} (expected {exp.get(r, 0)})"
           for r, v in final.items() if int(v, 16) != exp.get(r, 0)]
    return ", ".join(bad) or None


def main() -> int:
    if not EXE.exists():
        print(f"missing {EXE}; build: g++ -O2 -std=c++17 -static cpp/legv8.cpp -o build/legv8")
        return 2

    asm = Assembler()
    with tempfile.TemporaryDirectory() as tmp:
        runs = []  # (name, fwd, decoded file, python trace, expected regs)
        for path in sorted((ROOT / "programs").glob("*.asm")):
            source = path.read_text()
            instrs = asm.assemble(source)
            prog = Path(tmp) / f"{path.stem}.txt"
            prog.write_text(dump_program(instrs))
            for fwd in (True, False):
                runs.append((path.stem, fwd, prog, py_trace(instrs, fwd), expected_regs(source)))

        print("Python reference vs hand-computed EXPECT, then vs C++ every cycle:")
        mismatches = 0
        for name, fwd, prog, ref, exp in runs:
            bad = check_expected(ref, exp)
            diff = first_diff(ref, cpp_trace(prog, fwd))
            mismatches += bad is not None or diff is not None
            print(f"  {name:22} fwd={'on ' if fwd else 'off'} {ref[-1]:52} "
                  f"{'EXPECT FAIL ' + bad if bad else 'EXPECT ok'}  "
                  f"{'MISMATCH ' + diff if diff else 'MATCH'}")

        print("\nFault injection (C++ only; each must be caught):")
        caught = 0
        for fault in FAULTS:
            hits = [(name, fwd, d) for name, fwd, prog, ref, _ in runs
                    if (d := first_diff(ref, cpp_trace(prog, fwd, fault)))]
            if hits:
                caught += 1
                name, fwd, d = hits[0]
                print(f"  {fault:18} CAUGHT in {len(hits)}/{len(runs)} runs, "
                      f"first: {name} fwd={'on' if fwd else 'off'} {d}")
            else:
                print(f"  {fault:18} MISSED")

    print(f"\n{len(runs) - mismatches}/{len(runs)} runs pass EXPECT and match the Python reference model; "
          f"{caught}/{len(FAULTS)} injected faults detected")
    return 0 if mismatches == 0 and caught == len(FAULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
