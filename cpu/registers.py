MASK64 = 0xFFFF_FFFF_FFFF_FFFF
REG_NAMES = [f"X{i}" for i in range(31)] + ["XZR"]


class RegisterFile:
    NUM_REGS = 32

    def __init__(self):
        self._regs: list[int] = [0] * self.NUM_REGS

    def read(self, index: int) -> int:
        if index == 31:
            return 0
        return self._regs[index]

    def write(self, index: int, value: int) -> None:
        if index == 31:
            return
        self._regs[index] = value & MASK64

    def snapshot(self) -> dict[str, int]:
        result = {}
        for i in range(31):
            result[f"X{i}"] = self._regs[i]
        result["XZR"] = 0
        return result
