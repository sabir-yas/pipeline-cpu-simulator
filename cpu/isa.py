from enum import Enum, auto


class Opcode(Enum):
    ADD  = auto()
    ADDI = auto()
    SUB  = auto()
    SUBI = auto()
    AND  = auto()
    ORR  = auto()
    LDR  = auto()
    STR  = auto()
    CBZ  = auto()
    CBNZ = auto()
    B    = auto()
    HALT = auto()
    NOP  = auto()  # pipeline bubble


class InstructionFormat(Enum):
    R  = "R"
    I  = "I"
    D  = "D"
    CB = "CB"
    B  = "B"
    X  = "X"  # HALT / NOP


# Maps opcode -> (format, alu_op_string, reg_write, mem_read, mem_write, mem_to_reg, alu_src, branch)
OPCODE_META: dict = {
    Opcode.ADD:  (InstructionFormat.R,  "add", True,  False, False, False, False, False),
    Opcode.ADDI: (InstructionFormat.I,  "add", True,  False, False, False, True,  False),
    Opcode.SUB:  (InstructionFormat.R,  "sub", True,  False, False, False, False, False),
    Opcode.SUBI: (InstructionFormat.I,  "sub", True,  False, False, False, True,  False),
    Opcode.AND:  (InstructionFormat.R,  "and", True,  False, False, False, False, False),
    Opcode.ORR:  (InstructionFormat.R,  "orr", True,  False, False, False, False, False),
    Opcode.LDR:  (InstructionFormat.D,  "add", True,  True,  False, True,  True,  False),
    Opcode.STR:  (InstructionFormat.D,  "add", False, False, True,  False, True,  False),
    Opcode.CBZ:  (InstructionFormat.CB, "pass",False, False, False, False, False, True),
    Opcode.CBNZ: (InstructionFormat.CB, "pass",False, False, False, False, False, True),
    Opcode.B:    (InstructionFormat.B,  "none",False, False, False, False, False, True),
    Opcode.HALT: (InstructionFormat.X,  "none",False, False, False, False, False, False),
    Opcode.NOP:  (InstructionFormat.X,  "none",False, False, False, False, False, False),
}
