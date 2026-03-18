from __future__ import annotations
from cpu.instruction import Instruction, make_nop

MASK64 = 0xFFFF_FFFF_FFFF_FFFF


class InstructionMemory:
    def __init__(self, instructions: list[Instruction]):
        self._mem = instructions

    def fetch(self, pc: int) -> Instruction:
        index = pc // 4
        if index < 0 or index >= len(self._mem):
            return make_nop(pc)
        return self._mem[index]

    def __len__(self) -> int:
        return len(self._mem)


class DataMemory:
    def __init__(self):
        self._mem: dict[int, int] = {}

    def read(self, address: int) -> int:
        return self._mem.get(address, 0)

    def write(self, address: int, value: int) -> None:
        self._mem[address] = value & MASK64

    def snapshot(self) -> dict[int, int]:
        return dict(sorted(self._mem.items()))
