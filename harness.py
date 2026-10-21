"""Differential validation harness.

Runs every program in programs/ through the Python reference model and the C++ port
(forwarding ON and OFF), checks hand-computed EXPECT values, diffs register/memory/PC/
stall/flush state every cycle, then injects each C++ fault and checks the diff catches it.

Build first:  g++ -O2 -std=c++17 -static cpp/legv8.cpp -o build/legv8
Run:          python harness.py                  directed tests + fault matrix
              python harness.py --fuzz 1000      + random programs (no hand-written tests)
              python harness.py --bench          + C++ vs Python speed on bench/bench_loop.asm
"""
from __future__ import annotations
import argparse
import random
import statistics
import subprocess
import sys
import tempfile
import time
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


def cpp_run(prog: Path, fwd: bool, *args: str) -> list[str]:
    out = subprocess.run([str(EXE), str(prog), str(int(fwd)), *args],
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


def fwd_name(fwd: bool) -> str:
    return "on " if fwd else "off"


# ── Directed tests ────────────────────────────────────────────────────────────

def directed(tmp: Path) -> bool:
    asm = Assembler()
    runs = []  # (name, fwd, decoded file, python trace, expected regs)
    for path in sorted((ROOT / "programs").glob("*.asm")):
        source = path.read_text()
        instrs = asm.assemble(source)
        prog = tmp / f"{path.stem}.txt"
        prog.write_text(dump_program(instrs))
        for fwd in (True, False):
            runs.append((path.stem, fwd, prog, py_trace(instrs, fwd), expected_regs(source)))

    print("Python reference vs hand-computed EXPECT, then vs C++ every cycle:")
    mismatches = 0
    for name, fwd, prog, ref, exp in runs:
        bad = check_expected(ref, exp)
        diff = first_diff(ref, cpp_run(prog, fwd))
        mismatches += bad is not None or diff is not None
        print(f"  {name:22} fwd={fwd_name(fwd)} {ref[-1]:52} "
              f"{'EXPECT FAIL ' + bad if bad else 'EXPECT ok'}  "
              f"{'MISMATCH ' + diff if diff else 'MATCH'}")

    print("\nFault injection (C++ only; each must be caught):")
    caught = 0
    for fault in FAULTS:
        hits = [(name, fwd, d) for name, fwd, prog, ref, _ in runs
                if (d := first_diff(ref, cpp_run(prog, fwd, fault)))]
        if hits:
            caught += 1
            name, fwd, d = hits[0]
            print(f"  {fault:18} CAUGHT in {len(hits)}/{len(runs)} runs, "
                  f"first: {name} fwd={fwd_name(fwd).strip()} {d}")
        else:
            print(f"  {fault:18} MISSED")

    print(f"\n{len(runs) - mismatches}/{len(runs)} runs pass EXPECT and match the Python "
          f"reference model; {caught}/{len(FAULTS)} injected faults detected")
    return mismatches == 0 and caught == len(FAULTS)


# ── Random programs ───────────────────────────────────────────────────────────

REGS = ["X1", "X2", "X3", "X4", "X5", "X6"]  # small pool so hazards are frequent


def random_program(rng: random.Random, n: int) -> str:
    """Random ALU/memory code with forward-only branches, so it always reaches HALT."""
    src = lambda: rng.choice(REGS + ["XZR"])
    dst = lambda: "XZR" if rng.random() < 0.1 else rng.choice(REGS)
    body, labels = [], set()
    for i in range(n):
        r = rng.random()
        if r < 0.35:
            body.append(f"{rng.choice(['ADD', 'SUB', 'AND', 'ORR'])} {dst()}, {src()}, {src()}")
        elif r < 0.6:
            body.append(f"{rng.choice(['ADDI', 'SUBI'])} {dst()}, {src()}, #{rng.randint(0, 50)}")
        elif r < 0.8:
            base = "XZR" if rng.random() < 0.7 else src()  # mostly fixed addresses so loads alias stores
            op, rt = ("LDR", dst()) if rng.random() < 0.5 else ("STR", src())
            body.append(f"{op} {rt}, [{base}, #{rng.choice([0, 8, 16, 24])}]")
        else:
            target = rng.randint(i + 1, n)
            labels.add(target)
            op = rng.choice(["CBZ", "CBNZ", "B"])
            body.append(f"B L{target}" if op == "B" else f"{op} {src()}, L{target}")
    lines = []
    for i, line in enumerate(body):
        if i in labels:
            lines.append(f"L{i}:")
        lines.append(line)
    if n in labels:
        lines.append(f"L{n}:")
    lines.append("HALT")
    return "\n".join(lines)


def fuzz(tmp: Path, count: int, seed: int) -> bool:
    rng = random.Random(seed)
    asm = Assembler()
    runs = []  # (program index, fwd, decoded file, python trace)
    for k in range(count):
        source = random_program(rng, rng.randint(8, 40))
        instrs = asm.assemble(source)
        prog = tmp / f"fuzz{k}.txt"
        prog.write_text(dump_program(instrs))
        for fwd in (True, False):
            runs.append((k, fwd, prog, py_trace(instrs, fwd), source))

    print(f"\nFuzz: {count} random programs (seed {seed}), forwarding on + off")
    divergences = 0
    for k, fwd, prog, ref, source in runs:
        diff = first_diff(ref, cpp_run(prog, fwd))
        if diff:
            divergences += 1
            repro = ROOT / "build" / f"fuzz_fail_{seed}_{k}.asm"
            repro.write_text(source + "\n")
            print(f"  DIVERGENCE program {k} fwd={fwd_name(fwd).strip()}: {diff}  (saved {repro.name})")
    cycles = sum(int(ref[-1].split()[1].split("=")[1]) for *_, ref, _ in runs)
    print(f"  {len(runs)} runs, {cycles} cycles compared, {divergences} divergences")

    print("Fault injection against random programs only (runs until first catch):")
    caught = 0
    for fault in FAULTS:
        hit = next(((i, k, fwd, d) for i, (k, fwd, prog, ref, _) in enumerate(runs)
                    if (d := first_diff(ref, cpp_run(prog, fwd, fault)))), None)
        if hit:
            caught += 1
            i, k, fwd, d = hit
            print(f"  {fault:18} CAUGHT after {i + 1} runs (program {k} fwd={fwd_name(fwd).strip()}) {d}")
        else:
            print(f"  {fault:18} MISSED in {len(runs)} runs")
    print(f"  fuzzer alone detected {caught}/{len(FAULTS)} injected faults")
    return divergences == 0


# ── Benchmark ─────────────────────────────────────────────────────────────────

def bench(tmp: Path, repeats: int = 5) -> bool:
    path = ROOT / "bench" / "bench_loop.asm"
    instrs = Assembler().assemble(path.read_text())
    prog = tmp / "bench.txt"
    prog.write_text(dump_program(instrs))
    max_cycles = 100_000_000

    py_times, cpp_times = [], []
    for _ in range(repeats):
        sim = PipelineSimulator(SimulationConfig(max_cycles=max_cycles, record=False))
        sim.load_program(instrs)
        t0 = time.perf_counter()
        m = sim.run()
        py_times.append(time.perf_counter() - t0)

        end = dict(kv.split("=") for kv in cpp_run(prog, True, "none", str(max_cycles), "-q")[-1].split()[1:])
        cpp_times.append(float(end["time_s"]))

    same = (int(end["cycles"]), int(end["retired"])) == (m.total_cycles, m.instructions_retired)
    py_t, cpp_t = statistics.median(py_times), statistics.median(cpp_times)
    print(f"\nBenchmark: {path.name}, forwarding on, median of {repeats} runs, simulation loop only")
    print(f"  cycles={m.total_cycles}  retired={m.instructions_retired}  CPI={m.cpi:.3f}  "
          f"stalls={m.stall_count}  flushes={m.flush_count}  "
          f"{'C++ agrees' if same else 'C++ DISAGREES: ' + str(end)}")
    print(f"  Python {py_t:8.3f} s  {m.total_cycles / py_t / 1e6:8.3f} M cycles/s")
    print(f"  C++    {cpp_t:8.3f} s  {m.total_cycles / cpp_t / 1e6:8.3f} M cycles/s")
    print(f"  speedup {py_t / cpp_t:.0f}x")
    return same


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fuzz", type=int, metavar="N", help="also run N random programs")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bench", action="store_true", help="also benchmark C++ vs Python")
    args = ap.parse_args()

    if not EXE.exists():
        print(f"missing {EXE}; build: g++ -O2 -std=c++17 -static cpp/legv8.cpp -o build/legv8")
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        ok = directed(Path(tmp))
        if args.fuzz:
            ok &= fuzz(Path(tmp), args.fuzz, args.seed)
        if args.bench:
            ok &= bench(Path(tmp))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
