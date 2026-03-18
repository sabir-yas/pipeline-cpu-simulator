from __future__ import annotations
from dataclasses import dataclass, field
from cpu.isa import Opcode, InstructionFormat, OPCODE_META


@dataclass
class Instruction:
    opcode: Opcode = Opcode.NOP
    fmt: InstructionFormat = InstructionFormat.X

    # Register fields (None if unused)
    rd: int | None = None      # destination (R/I)
    rn: int | None = None      # source 1 (R/I/D)
    rm: int | None = None      # source 2 (R)
    rt: int | None = None      # transfer register (D/CB)

    # Immediate / offset (sign-extended)
    imm: int = 0               # ADDI/SUBI immediate
    offset: int = 0            # D/CB/B address offset (in words)

    # Metadata
    raw_text: str = ""
    pc: int = 0

    # ── Derived control signals (set by assembler from OPCODE_META) ──
    alu_op: str = "none"
    reg_write: bool = False
    mem_read: bool = False
    mem_write: bool = False
    mem_to_reg: bool = False
    alu_src: bool = False      # True = use imm, False = use rm
    branch: bool = False

    def __post_init__(self):
        if self.opcode in OPCODE_META:
            meta = OPCODE_META[self.opcode]
            self.fmt       = meta[0]
            self.alu_op    = meta[1]
            self.reg_write = meta[2]
            self.mem_read  = meta[3]
            self.mem_write = meta[4]
            self.mem_to_reg= meta[5]
            self.alu_src   = meta[6]
            self.branch    = meta[7]

    # ── Convenience predicates ──
    @property
    def is_nop(self) -> bool:
        return self.opcode in (Opcode.NOP, Opcode.HALT)

    @property
    def is_load(self) -> bool:
        return self.opcode == Opcode.LDR

    @property
    def is_store(self) -> bool:
        return self.opcode == Opcode.STR

    @property
    def is_branch(self) -> bool:
        return self.opcode in (Opcode.CBZ, Opcode.CBNZ, Opcode.B)

    @property
    def dest_reg(self) -> int | None:
        if self.opcode == Opcode.LDR:
            return self.rt
        if self.reg_write:
            return self.rd
        return None

    @property
    def source_regs(self) -> set[int]:
        regs: set[int] = set()
        for r in (self.rn, self.rm):
            if r is not None:
                regs.add(r)
        # STR reads Rt as data source; CBZ/CBNZ read Rt for branch condition
        if self.opcode in (Opcode.STR, Opcode.CBZ, Opcode.CBNZ):
            if self.rt is not None:
                regs.add(self.rt)
        return regs

    def __str__(self) -> str:
        return self.raw_text or self.opcode.name


def make_nop(pc: int = 0) -> Instruction:
    return Instruction(opcode=Opcode.NOP, raw_text="NOP", pc=pc)
