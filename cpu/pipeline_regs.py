from __future__ import annotations
from dataclasses import dataclass, field
from cpu.instruction import Instruction, make_nop


@dataclass
class IF_ID:
    instruction: Instruction = field(default_factory=make_nop)
    pc_plus_4: int = 0
    valid: bool = False


@dataclass
class ID_EX:
    instruction: Instruction = field(default_factory=make_nop)
    pc_plus_4: int = 0
    read_data1: int = 0
    read_data2: int = 0
    sign_ext_imm: int = 0
    rn: int = 31
    rm: int = 31
    rd: int = 31
    rt: int = 31
    # Control signals
    reg_write: bool = False
    mem_read: bool = False
    mem_write: bool = False
    mem_to_reg: bool = False
    alu_src: bool = False
    branch: bool = False
    alu_op: str = "none"
    valid: bool = False


@dataclass
class EX_MEM:
    instruction: Instruction = field(default_factory=make_nop)
    alu_result: int = 0
    read_data2: int = 0
    dest_reg: int = 31
    branch_taken: bool = False
    branch_target: int = 0
    zero: bool = False
    reg_write: bool = False
    mem_read: bool = False
    mem_write: bool = False
    mem_to_reg: bool = False
    valid: bool = False


@dataclass
class MEM_WB:
    instruction: Instruction = field(default_factory=make_nop)
    alu_result: int = 0
    mem_data: int = 0
    dest_reg: int = 31
    reg_write: bool = False
    mem_to_reg: bool = False
    valid: bool = False
