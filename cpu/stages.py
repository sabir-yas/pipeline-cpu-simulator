from __future__ import annotations
from cpu.instruction import Instruction, make_nop
from cpu.isa import Opcode
from cpu.pipeline_regs import IF_ID, ID_EX, EX_MEM, MEM_WB
from cpu.registers import RegisterFile
from cpu.memory import InstructionMemory, DataMemory
from cpu.alu import ALU
from cpu.hazard import HazardSignals, ForwardingSource

MASK64 = 0xFFFF_FFFF_FFFF_FFFF


# ── Stage 1: Instruction Fetch ──────────────────────────────────────────────

def stage_if(pc: int, imem: InstructionMemory) -> tuple[IF_ID, int]:
    instr = imem.fetch(pc)
    new_pc = pc + 4
    return IF_ID(instruction=instr, pc_plus_4=new_pc, valid=True), new_pc


# ── Stage 2: Instruction Decode / Register Read ──────────────────────────────

def stage_id(if_id: IF_ID, regfile: RegisterFile) -> ID_EX:
    instr = if_id.instruction

    rn = instr.rn if instr.rn is not None else 31
    rm = instr.rm if instr.rm is not None else 31
    rd = instr.rd if instr.rd is not None else 31
    rt = instr.rt if instr.rt is not None else 31

    # CBZ/CBNZ: condition register is Rt, read into read_data1 so forwarding (forward_a) applies
    if instr.opcode in (Opcode.CBZ, Opcode.CBNZ):
        read_data1 = regfile.read(rt)
        read_data2 = 0
        fwd_rn = rt   # forwarding unit tracks rn for forward_a
    elif instr.opcode == Opcode.STR:
        read_data1 = regfile.read(rn)   # base address → ALU
        read_data2 = regfile.read(rt)   # data to store → forwarded via forward_b
        fwd_rn = rn
        rm = rt   # so forward_b matches the store-data register
    else:
        read_data1 = regfile.read(rn)
        read_data2 = regfile.read(rm)
        fwd_rn = rn

    # sign-extended immediate / offset
    if instr.opcode in (Opcode.ADDI, Opcode.SUBI):
        sign_ext = instr.imm
    elif instr.opcode in (Opcode.LDR, Opcode.STR):
        sign_ext = instr.offset
    else:
        sign_ext = instr.offset  # CB / B use offset for branch target calc

    return ID_EX(
        instruction=instr,
        pc_plus_4=if_id.pc_plus_4,
        read_data1=read_data1,
        read_data2=read_data2,
        sign_ext_imm=sign_ext,
        rn=fwd_rn, rm=rm, rd=rd, rt=rt,
        reg_write=instr.reg_write,
        mem_read=instr.mem_read,
        mem_write=instr.mem_write,
        mem_to_reg=instr.mem_to_reg,
        alu_src=instr.alu_src,
        branch=instr.branch,
        alu_op=instr.alu_op,
        valid=if_id.valid,
    )


# ── Stage 3: Execute ──────────────────────────────────────────────────────────

def stage_ex(
    id_ex: ID_EX,
    alu: ALU,
    ex_mem: EX_MEM,
    mem_wb: MEM_WB,
    hazard_signals: HazardSignals,
) -> EX_MEM:
    fwd = hazard_signals.forwarding

    # Resolve ALU input A (Rn)
    if fwd.forward_a == ForwardingSource.EX_MEM:
        alu_in_a = ex_mem.alu_result
    elif fwd.forward_a == ForwardingSource.MEM_WB:
        alu_in_a = mem_wb.mem_data if mem_wb.mem_to_reg else mem_wb.alu_result
    else:
        alu_in_a = id_ex.read_data1

    # Resolve forwarded read_data2 (Rm / Rt) before alu_src mux
    if fwd.forward_b == ForwardingSource.EX_MEM:
        fwd_data2 = ex_mem.alu_result
    elif fwd.forward_b == ForwardingSource.MEM_WB:
        fwd_data2 = mem_wb.mem_data if mem_wb.mem_to_reg else mem_wb.alu_result
    else:
        fwd_data2 = id_ex.read_data2

    # ALU input B: immediate or register
    alu_in_b = id_ex.sign_ext_imm if id_ex.alu_src else fwd_data2

    result, zero = alu.execute(id_ex.alu_op, alu_in_a, alu_in_b)

    # Branch resolution
    branch_taken = False
    branch_target = 0
    if id_ex.branch:
        instr = id_ex.instruction
        branch_target = (id_ex.instruction.pc + id_ex.sign_ext_imm * 4)
        if instr.opcode == Opcode.B:
            branch_taken = True
        elif instr.opcode == Opcode.CBZ:
            branch_taken = (alu_in_a == 0)
        elif instr.opcode == Opcode.CBNZ:
            branch_taken = (alu_in_a != 0)

    # Destination register
    if id_ex.mem_read:  # LDR: dest is Rt
        dest_reg = id_ex.rt
    elif id_ex.reg_write:
        dest_reg = id_ex.rd
    else:
        dest_reg = 31

    return EX_MEM(
        instruction=id_ex.instruction,
        alu_result=result,
        read_data2=fwd_data2,      # value to store (STR)
        dest_reg=dest_reg,
        branch_taken=branch_taken,
        branch_target=branch_target,
        zero=zero,
        reg_write=id_ex.reg_write,
        mem_read=id_ex.mem_read,
        mem_write=id_ex.mem_write,
        mem_to_reg=id_ex.mem_to_reg,
        valid=id_ex.valid,
    )


# ── Stage 4: Memory Access ───────────────────────────────────────────────────

def stage_mem(ex_mem: EX_MEM, dmem: DataMemory) -> MEM_WB:
    mem_data = 0
    if ex_mem.mem_read:
        mem_data = dmem.read(ex_mem.alu_result)
    if ex_mem.mem_write:
        dmem.write(ex_mem.alu_result, ex_mem.read_data2)

    return MEM_WB(
        instruction=ex_mem.instruction,
        alu_result=ex_mem.alu_result,
        mem_data=mem_data,
        dest_reg=ex_mem.dest_reg,
        reg_write=ex_mem.reg_write,
        mem_to_reg=ex_mem.mem_to_reg,
        valid=ex_mem.valid,
    )


# ── Stage 5: Write Back ──────────────────────────────────────────────────────

def stage_wb(mem_wb: MEM_WB, regfile: RegisterFile) -> None:
    if mem_wb.reg_write and mem_wb.valid:
        write_val = mem_wb.mem_data if mem_wb.mem_to_reg else mem_wb.alu_result
        regfile.write(mem_wb.dest_reg, write_val)
