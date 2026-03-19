# LEGv8 Pipeline CPU Simulator

A cycle-accurate simulation of a **5-stage pipelined LEGv8 CPU** in Python. LEGv8 is the simplified ARMv8 subset used in Patterson & Hennessy's *Computer Organization and Design*.

Simulates instruction fetch through write-back with full hazard handling: data forwarding, load-use stalls, and branch flushes. Includes an interactive terminal UI and HTML report generation.

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

Expected: X1=10, X2=20, X3=30, X4=20, X5=20, X6=26 | Speedup ~2.09x

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

## Project Structure

```
main.py               — interactive menu and UI
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
```

---

## Performance Metrics

The simulator reports for both forwarding ON and OFF:

- **Total cycles**
- **Instructions retired**
- **CPI** (cycles per instruction)
- **Stall count** and **flush count**
- **Speedup** (cycles_off / cycles_on)
