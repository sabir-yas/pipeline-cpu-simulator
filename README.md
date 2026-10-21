# LEGv8 Pipeline CPU Simulator

A cycle-accurate simulation of a **5-stage pipelined LEGv8 CPU** in Python. LEGv8 is the simplified ARMv8 subset used in Patterson & Hennessy's *Computer Organization and Design*.

Simulates instruction fetch through write-back with full hazard handling: data forwarding, load-use stalls, and branch flushes. Includes an interactive terminal UI and HTML report generation.

It also has a **C++ port** that is checked against the Python model by a **differential validation harness**. The harness compares state every cycle, runs random programs, and injects faults to show it catches bugs. The C++ sim runs **125–203× faster** than Python. See [C++ Port + Differential Validation Harness](#c-port--differential-validation-harness).

---

## Features

- 5-stage pipeline: IF → ID → EX → MEM → WB
- Data hazard handling via **forwarding** (EX/MEM and MEM/WB paths) and **stalling**
- Control hazard handling via **branch flush** (2-cycle penalty)
- Load-use hazard detection (1-cycle stall, unavoidable even with forwarding)
- Toggle forwarding ON/OFF to compare performance
- Step-by-step or full-run mode
- Rich terminal output: pipeline diagram, register state, metrics
- HTML report generation
- C++ port, compared against the Python reference model every cycle (PC, stall, flush, registers, stores)
- 9 injectable pipeline faults, used to show the harness catches each one
- Random-program fuzzer and a ~1M-cycle C++ vs Python benchmark

---

## Supported Instructions

| Instruction | Format | Description |
|-------------|--------|-------------|
| `ADD`, `SUB`, `AND`, `ORR` | R | Register arithmetic/logic |
| `ADDI`, `SUBI` | I | Immediate arithmetic |
| `LDR`, `STR` | D | Load/store (base + offset) |
| `CBZ`, `CBNZ` | CB | Conditional branch if zero/non-zero |
| `B` | B | Unconditional branch |
| `HALT` | — | Stop simulation |

---

## Requirements

```
pip install rich
```

Requires Python 3.10+ (uses `match` statement).

For the C++ port and harness, you also need a C++17 compiler (g++ or clang++). On Windows, use MSYS2:

```
winget install MSYS2.MSYS2
C:\msys64\usr\bin\bash.exe -lc "pacman -S --noconfirm mingw-w64-ucrt-x86_64-gcc"
```

Add `C:\msys64\ucrt64\bin` to PATH. Without it, g++ fails with no error message.

---

## Running

```bash
cd pipeline-cpu-simulator
python main.py
```

### Interactive Menu

```
1. Select program        — choose a .asm file from programs/
2. Toggle forwarding     — ON (default) or OFF
3. Toggle run mode       — full run (default) or step-by-step
4. Toggle HTML report    — generates report_<name>.html
5. Run simulation
6. Exit
```

---

## Test Programs

### `test1_data_hazards.asm` — RAW Data Hazards
Exercises EX/MEM and MEM/WB forwarding paths.

```
ADDI X1, XZR, #10
ADDI X2, XZR, #20
ADD  X3, X1, X2      // EX/MEM fwd X1, MEM/WB fwd X2
SUB  X4, X3, X1      // EX/MEM fwd X3
AND  X5, X3, X4      // EX/MEM fwd X4, MEM/WB fwd X3
ORR  X6, X5, X1      // EX/MEM fwd X5
HALT
```

Expected: X1=10, X2=20, X3=30, X4=20, X5=20, X6=30 | Speedup ~2.09x

---

### `test2_load_use.asm` — Load-Use Hazard
Demonstrates the unavoidable 1-cycle stall after a load instruction.

```
LDR  X2, [X1, #0]
ADD  X3, X2, X2      // stall 1 cycle: X2 not yet available
```

Expected: X2=100, X3=200, X6=99, X7=99 | Speedup ~1.53x

---

### `test3_branches.asm` — Branch Hazards + Loop
Loop computing 5+4+3+2+1=15, demonstrating 2-cycle flush penalties on taken branches.

```
LOOP:
  ADD  X2, X2, X1
  SUBI X1, X1, #1
  CBZ  X1, DONE      // flush on last iteration
  B    LOOP          // flush every iteration
DONE:
  ADD  X4, X2, XZR
HALT
```

Expected: X1=0, X2=15, X4=15 | Speedup ~1.45x

---

### `test4_corner_cases.asm` — Forwarding Corner Cases
Covers the paths tests 1–3 don't reach. Each one is the target of an injected fault in the harness.

```
ADDI XZR, XZR, #5    // write to XZR must be discarded
ADDI X1, XZR, #1
ADDI X1, XZR, #2     // X1 written twice back to back
ADD  X2, X1, XZR     // EX/MEM (newest) must beat MEM/WB -> X2 = 2
ADDI X4, XZR, #7
STR  X4, [X3, #0]    // store data forwarded from EX/MEM
LDR  X5, [X3, #0]
CBZ  X5, SKIP        // branch on a just-loaded reg: load-use stall + MEM/WB fwd
```

Expected: X1=2, X2=2, X3=64, X4=7, X5=7, X6=1, X7=0 | Speedup ~1.47x

---

### `test5_stall_flush.asm` — Stall + Flush in the Same Cycle
Regression test for a bug the harness work found. With forwarding OFF, `ADD` stalls on X1 while `B` is taken. The flush must win, so the wrong-path `ADD` never executes.

```
ADDI X1, XZR, #1
B    DONE
ADD  X2, X1, X1      // wrong path: must be squashed
DONE:
HALT
```

Expected: X1=1, X2=0 | Speedup 1.00x (only the stall differs, and the flush squashes it)

---

## C++ Port + Differential Validation Harness

`cpp/legv8.cpp` is a C++ port of the pipeline. The Python simulator is the reference model.
`harness.py` runs every program in `programs/` through both, with forwarding ON and OFF, and checks three things:

1. **Hand-computed results.** Each program's `// EXPECT X1=10 ...` line is checked against the Python model's final registers. Every register not listed must be 0. This is the check that is independent of both simulators.
2. **Per-cycle diff.** PC, stall, flush, X0–X30, and stores are compared every cycle. The first mismatch is reported as cycle + field, e.g. `c=7: python x3=1e vs c++ x3=a`.
3. **Fault injection.** 9 bugs can be injected into the C++ side (`no_fwd_exmem`, `no_fwd_memwb`, `fwd_priority`, `no_load_use_stall`, `no_flush`, `short_flush`, `str_no_data_fwd`, `cbz_reads_rn`, `xzr_writable`). The harness must catch each one.

4. **Random programs** (`--fuzz N`): ALU, load/store, and forward-only branch code, so every program halts. A small register pool keeps hazards frequent. Programs run through the same diff and fault matrix with no hand-written tests. Divergent programs are saved to `build/fuzz_fail_*.asm`.
5. **Benchmark** (`--bench`): `bench/bench_loop.asm`, ~1M cycles, forwarding on, median of 5 runs. Only the simulation loop is timed, with per-cycle tracing off on both sides (`SimulationConfig(record=False)` / `legv8 ... -q`).

```bash
g++ -O2 -std=c++17 -static cpp/legv8.cpp -o build/legv8
# or: cmake -S cpp -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build
python harness.py                       # directed tests + fault matrix
python harness.py --fuzz 2000 --bench   # + random programs + speed
```

### Results

| Check | Result |
|---|---|
| Directed programs (5 × fwd on/off) | 10/10 pass EXPECT and match the Python reference model every cycle |
| Injected faults, directed tests | 9/9 detected |
| Random programs (2000 × fwd on/off, seed 1) | 4000 runs, 96,613 cycles compared, 0 divergences |
| Injected faults, random programs only | 9/9 detected, each within the first 23 runs |
| Speed, `bench_loop.asm`: 1,001,504 cycles, CPI 1.599 | Python 7.23 s (0.139 M cycles/s), C++ 0.058 s (17.3 M cycles/s): **125× speedup** |

Benchmark: MSYS2 g++ 16.1 `-O2`, Python 3.13, Windows 11, same machine. The speedup varied from 125× to 203× across runs, depending on machine load. The table shows the lower one.
`short_flush` (a 1-cycle branch penalty) leaves the final state correct, so only the per-cycle comparison catches it.

"Match" means the C++ port matches the Python reference model, not that either is verified against the LEGv8 spec. The fault matrix shows the harness is sensitive to these bug classes.

**Bug found in the reference model:** with forwarding OFF, a stall and a taken-branch flush in the same cycle let the stall win. The wrong-path instruction was kept in IF/ID and executed. Fixed so the flush wins (`test5_stall_flush.asm` covers it). The C++ port alone would have mirrored the bug. The EXPECT check is what catches it. With the bug put back into the Python model, the fuzzer also flags it at the 4th random program. That only works because the two models now disagree on this path.

---

## Project Structure

```
main.py               — interactive menu and UI
harness.py            — Python-vs-C++ differential validation + fault injection
cpp/legv8.cpp         — C++ port of the pipeline (fault-injectable)
simulator.py          — PipelineSimulator: orchestrates all stages per cycle
cpu/
  isa.py              — Opcode enum and instruction format metadata
  instruction.py      — Instruction dataclass
  registers.py        — 32-register file (X0–X30, XZR)
  memory.py           — instruction and data memory
  alu.py              — ALU operations
  pipeline_regs.py    — pipeline latch structs (IF_ID, ID_EX, EX_MEM, MEM_WB)
  hazard.py           — HazardUnit: forwarding, stall, and flush detection
  stages.py           — stage_if, stage_id, stage_ex, stage_mem, stage_wb
utils/
  assembler.py        — LEGv8 assembler: .asm text -> Instruction objects
output/
  terminal.py         — Rich terminal rendering
  html_report.py      — HTML report generator
programs/
  test1_data_hazards.asm
  test2_load_use.asm
  test3_branches.asm
  test4_corner_cases.asm  — forwarding priority, store-data fwd, CBZ on loaded reg, XZR writes
  test5_stall_flush.asm   — stall + flush in the same cycle
bench/
  bench_loop.asm          — ~1M-cycle benchmark (harness.py --bench)
```

---

## Performance Metrics

The simulator reports for both forwarding ON and OFF:

- **Total cycles**
- **Instructions retired**
- **CPI** (cycles per instruction)
- **Stall count** and **flush count**
- **Speedup** (cycles_off / cycles_on)
