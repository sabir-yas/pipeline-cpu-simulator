from __future__ import annotations
from dataclasses import dataclass, field
from cpu.instruction import Instruction, make_nop
from cpu.isa import Opcode
from cpu.registers import RegisterFile
from cpu.memory import InstructionMemory, DataMemory
from cpu.alu import ALU
from cpu.pipeline_regs import IF_ID, ID_EX, EX_MEM, MEM_WB
from cpu.hazard import HazardUnit, HazardSignals, ForwardingDecision, ForwardingSource
from cpu.stages import stage_if, stage_id, stage_ex, stage_mem, stage_wb


# ── Simulation config ─────────────────────────────────────────────────────────

@dataclass
class SimulationConfig:
    forwarding_enabled: bool = True
    max_cycles: int = 10_000
    program_name: str = ""


# ── Per-cycle snapshot (for rendering) ───────────────────────────────────────

@dataclass
class StageInfo:
    name: str          # "IF", "ID", "EX", "MEM", "WB"
    instruction: str   # raw_text of the instruction in this stage
    is_bubble: bool = False
    is_stall: bool = False
    is_flush: bool = False
    forward_a: str = ""
    forward_b: str = ""


@dataclass
class CycleSnapshot:
    cycle: int
    stages: dict[str, StageInfo]   # keyed by stage name
    pc: int
    stalled: bool
    flushed: bool
    reg_snapshot: dict[str, int]
    forwarding: ForwardingDecision


# ── Performance metrics ───────────────────────────────────────────────────────

@dataclass
class PerformanceMetrics:
    total_cycles: int = 0
    instructions_retired: int = 0
    stall_count: int = 0
    flush_count: int = 0
    cpi: float = 0.0

    def compute(self):
        if self.instructions_retired > 0:
            self.cpi = self.total_cycles / self.instructions_retired
        else:
            self.cpi = 0.0


# ── Main simulator ────────────────────────────────────────────────────────────

class PipelineSimulator:
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.regfile = RegisterFile()
        self.dmem = DataMemory()
        self.imem: InstructionMemory | None = None
        self.alu = ALU()
        self.hazard_unit = HazardUnit(config.forwarding_enabled)

        # Pipeline registers
        self.if_id  = IF_ID()
        self.id_ex  = ID_EX()
        self.ex_mem = EX_MEM()
        self.mem_wb = MEM_WB()

        self.pc: int = 0
        self.metrics = PerformanceMetrics()
        self.halted: bool = False
        self.cycle_log: list[CycleSnapshot] = []

        # Track which original instruction is in each stage for the diagram
        self._instructions: list[Instruction] = []

    def load_program(self, instructions: list[Instruction]) -> None:
        self._instructions = instructions
        self.imem = InstructionMemory(instructions)

    def reset(self) -> None:
        self.__init__(self.config)

    def step(self) -> CycleSnapshot:
        """Advance one clock cycle. Returns a snapshot for logging/rendering."""
        assert self.imem is not None, "No program loaded"

        # 1. Hazard detection (reads current pipeline regs)
        hazard_signals = self.hazard_unit.detect(
            self.id_ex, self.ex_mem, self.mem_wb, self.if_id
        )

        # 2. WB — side-effect: writes register file
        stage_wb(self.mem_wb, self.regfile)

        # 3. MEM
        new_mem_wb = stage_mem(self.ex_mem, self.dmem)

        # 4. EX
        new_ex_mem = stage_ex(
            self.id_ex, self.alu,
            self.ex_mem, self.mem_wb,
            hazard_signals,
        )

        # 5. Branch resolution — may redirect PC and trigger flush
        flushed_this_cycle = False
        if new_ex_mem.branch_taken:
            hazard_signals.flush = True
            flushed_this_cycle = True
            self.metrics.flush_count += 1
            self.pc = new_ex_mem.branch_target

        # 6. ID
        if hazard_signals.stall:
            new_id_ex = ID_EX()      # insert bubble
        elif hazard_signals.flush:
            new_id_ex = ID_EX()      # flush
        else:
            new_id_ex = stage_id(self.if_id, self.regfile)

        # 7. IF
        if hazard_signals.stall:
            new_if_id = self.if_id   # freeze — don't advance PC
            # (PC was not incremented yet for this stall cycle)
        elif hazard_signals.flush:
            new_if_id = IF_ID()      # flush
            # PC already redirected above
        else:
            new_if_id, self.pc = stage_if(self.pc, self.imem)

        # 8. Retire instructions in WB
        if self.mem_wb.valid and self.mem_wb.instruction.opcode != Opcode.NOP:
            if self.mem_wb.instruction.opcode == Opcode.HALT:
                self.halted = True
            else:
                self.metrics.instructions_retired += 1

        if hazard_signals.stall:
            self.metrics.stall_count += 1

        # 9. Build snapshot before advancing
        fwd = hazard_signals.forwarding
        snapshot = CycleSnapshot(
            cycle=self.metrics.total_cycles + 1,
            stages={
                "IF":  StageInfo("IF",  str(new_if_id.instruction),
                                 is_flush=flushed_this_cycle and not hazard_signals.stall),
                "ID":  StageInfo("ID",  str(self.if_id.instruction),
                                 is_bubble=not self.if_id.valid,
                                 is_stall=hazard_signals.stall,
                                 is_flush=flushed_this_cycle),
                "EX":  StageInfo("EX",  str(self.id_ex.instruction),
                                 is_bubble=not self.id_ex.valid,
                                 forward_a=fwd.forward_a.value if fwd.forward_a != ForwardingSource.NONE else "",
                                 forward_b=fwd.forward_b.value if fwd.forward_b != ForwardingSource.NONE else ""),
                "MEM": StageInfo("MEM", str(self.ex_mem.instruction),
                                 is_bubble=not self.ex_mem.valid),
                "WB":  StageInfo("WB",  str(self.mem_wb.instruction),
                                 is_bubble=not self.mem_wb.valid),
            },
            pc=self.pc,
            stalled=hazard_signals.stall,
            flushed=flushed_this_cycle,
            reg_snapshot=self.regfile.snapshot(),
            forwarding=fwd,
        )

        # 10. Advance pipeline registers
        self.if_id  = new_if_id
        self.id_ex  = new_id_ex
        self.ex_mem = new_ex_mem
        self.mem_wb = new_mem_wb
        self.metrics.total_cycles += 1

        self.cycle_log.append(snapshot)
        return snapshot

    def run(self) -> PerformanceMetrics:
        """Run until HALT reaches WB or max_cycles."""
        while not self.halted and self.metrics.total_cycles < self.config.max_cycles:
            self.step()
        self.metrics.compute()
        return self.metrics
