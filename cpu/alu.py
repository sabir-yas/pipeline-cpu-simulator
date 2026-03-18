MASK64 = 0xFFFF_FFFF_FFFF_FFFF


class ALU:
    def execute(self, op: str, a: int, b: int) -> tuple[int, bool]:
        """Returns (result, zero_flag)."""
        match op:
            case "add":
                result = (a + b) & MASK64
            case "sub":
                result = (a - b) & MASK64
            case "and":
                result = (a & b) & MASK64
            case "orr":
                result = (a | b) & MASK64
            case "pass":
                result = a & MASK64
            case _:
                result = 0
        return result, (result == 0)
