from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ForwardingSource(Enum):
    NONE   = "none"
    EX_MEM = "EX/MEM"
    MEM_WB = "MEM/WB"


@dataclass
class ForwardingDecision:
    forward_a: ForwardingSource = ForwardingSource.NONE
    forward_b: ForwardingSource = ForwardingSource.NONE


@dataclass
class HazardSignals:
    stall: bool = False
    flush: bool = False
    forwarding: ForwardingDecision = field(default_factory=ForwardingDecision)


class HazardUnit:
    def __init__(self, forwarding_enabled: bool = True):
        self.forwarding_enabled = forwarding_enabled

    def detect(self, id_ex, ex_mem, mem_wb, if_id) -> HazardSignals:
        signals = HazardSignals()
        signals.forwarding = self._forwarding_mux(id_ex, ex_mem, mem_wb)

        if self.forwarding_enabled:
            signals.stall = self._load_use_stall(id_ex, if_id)
        else:
            signals.stall = self._raw_stall_no_forwarding(id_ex, ex_mem, mem_wb, if_id)

        return signals

    # ── Load-use stall (always needed even with forwarding) ──
    def _load_use_stall(self, id_ex, if_id) -> bool:
        if not id_ex.mem_read:
            return False
        load_dest = id_ex.rt
        if load_dest == 31:
            return False
        src_regs = if_id.instruction.source_regs
        return load_dest in src_regs

    # ── RAW stall when forwarding is OFF ──
    def _raw_stall_no_forwarding(self, id_ex, ex_mem, mem_wb, if_id) -> bool:
        src_regs = if_id.instruction.source_regs
        for stage_reg in (id_ex, ex_mem, mem_wb):
            dest = getattr(stage_reg, 'dest_reg', None)
            if dest is None:
                # ID_EX uses rd/rt — compute dest
                instr = stage_reg.instruction
                dest = instr.dest_reg
            if stage_reg.reg_write and dest is not None and dest != 31:
                if dest in src_regs:
                    return True
        return False

    # ── Forwarding MUX ──
    def _forwarding_mux(self, id_ex, ex_mem, mem_wb) -> ForwardingDecision:
        if not self.forwarding_enabled:
            return ForwardingDecision()

        decision = ForwardingDecision()
        rn = id_ex.rn
        rm = id_ex.rm

        # EX hazard (highest priority)
        if ex_mem.reg_write and ex_mem.dest_reg != 31:
            if ex_mem.dest_reg == rn:
                decision.forward_a = ForwardingSource.EX_MEM
            if ex_mem.dest_reg == rm:
                decision.forward_b = ForwardingSource.EX_MEM

        # MEM hazard (lower priority — only if EX didn't cover it)
        if mem_wb.reg_write and mem_wb.dest_reg != 31:
            if mem_wb.dest_reg == rn and decision.forward_a == ForwardingSource.NONE:
                decision.forward_a = ForwardingSource.MEM_WB
            if mem_wb.dest_reg == rm and decision.forward_b == ForwardingSource.NONE:
                decision.forward_b = ForwardingSource.MEM_WB

        return decision
