from __future__ import annotations
from cpu.isa import Opcode
from cpu.instruction import Instruction, make_nop

REGISTER_MAP: dict[str, int] = {
    **{f"X{i}": i for i in range(31)},
    "XZR": 31,
    "LR":  30,
    "FP":  29,
    "SP":  28,
}


class AssemblerError(Exception):
    pass


def _reg(token: str) -> int:
    token = token.strip().upper().rstrip(",")
    if token not in REGISTER_MAP:
        raise AssemblerError(f"Unknown register: {token!r}")
    return REGISTER_MAP[token]


def _imm(token: str) -> int:
    token = token.strip().lstrip("#").rstrip(",")
    try:
        return int(token, 0)
    except ValueError:
        raise AssemblerError(f"Bad immediate: {token!r}")


def _sign_extend(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    value = value & mask
    if value & (1 << (bits - 1)):
        value -= (1 << bits)
    return value


class Assembler:
    def assemble(self, source: str) -> list[Instruction]:
        lines = self._strip_and_normalize(source)
        labels = self._scan_labels(lines)
        instructions: list[Instruction] = []
        pc = 0
        for line in lines:
            # Strip label prefix if present
            if ":" in line:
                rest = line.split(":", 1)[1].strip()
                if not rest:
                    continue  # label-only line
                line = rest
            if not line:
                continue
            instr = self._parse_line(line, pc, labels)
            instr.pc = pc
            instructions.append(instr)
            pc += 4
        return instructions

    # ── Preprocessing ──────────────────────────────────────────────────────

    def _strip_and_normalize(self, source: str) -> list[str]:
        result = []
        for raw in source.splitlines():
            line = raw.split("//")[0].strip().upper()
            if line:
                result.append(line)
        return result

    def _scan_labels(self, lines: list[str]) -> dict[str, int]:
        labels: dict[str, int] = {}
        pc = 0
        for line in lines:
            if ":" in line:
                label = line.split(":")[0].strip()
                labels[label] = pc
                rest = line.split(":", 1)[1].strip()
                if not rest:
                    continue  # label-only line — no instruction, don't advance PC
            pc += 4
        return labels

    # ── Line parser ────────────────────────────────────────────────────────

    def _parse_line(self, line: str, pc: int, labels: dict[str, int]) -> Instruction:
        # Normalize: replace commas with spaces for uniform splitting
        # But preserve bracket notation for LDR/STR
        tokens = line.replace(",", " ").split()
        if not tokens:
            return make_nop(pc)

        op_str = tokens[0].upper()
        try:
            opcode = Opcode[op_str]
        except KeyError:
            raise AssemblerError(f"Unknown opcode: {op_str!r} at PC={pc}")

        raw = line
        instr = Instruction(opcode=opcode, raw_text=raw)

        match opcode:
            # ── R-format: ADD Rd, Rn, Rm ─────────────────────────────────
            case Opcode.ADD | Opcode.SUB | Opcode.AND | Opcode.ORR:
                if len(tokens) < 4:
                    raise AssemblerError(f"Expected: {op_str} Rd, Rn, Rm")
                instr.rd = _reg(tokens[1])
                instr.rn = _reg(tokens[2])
                instr.rm = _reg(tokens[3])

            # ── I-format: ADDI Rd, Rn, #imm ──────────────────────────────
            case Opcode.ADDI | Opcode.SUBI:
                if len(tokens) < 4:
                    raise AssemblerError(f"Expected: {op_str} Rd, Rn, #imm")
                instr.rd = _reg(tokens[1])
                instr.rn = _reg(tokens[2])
                instr.imm = _sign_extend(_imm(tokens[3]), 12)

            # ── D-format: LDR/STR Rt, [Rn, #offset] ─────────────────────
            case Opcode.LDR | Opcode.STR:
                # Rejoin and re-parse to handle bracket syntax cleanly
                bracket_str = " ".join(tokens[2:])
                bracket_str = bracket_str.replace("[", "").replace("]", "")
                parts = bracket_str.replace(",", " ").split()
                if len(parts) < 1:
                    raise AssemblerError(f"Expected: {op_str} Rt, [Rn, #offset]")
                instr.rt = _reg(tokens[1])
                instr.rn = _reg(parts[0])
                instr.offset = _sign_extend(_imm(parts[1]) if len(parts) > 1 else 0, 9)

            # ── CB-format: CBZ/CBNZ Rt, LABEL ────────────────────────────
            case Opcode.CBZ | Opcode.CBNZ:
                if len(tokens) < 3:
                    raise AssemblerError(f"Expected: {op_str} Rt, LABEL")
                instr.rt = _reg(tokens[1])
                label = tokens[2].strip()
                if label not in labels:
                    raise AssemblerError(f"Undefined label: {label!r}")
                instr.offset = (labels[label] - pc) // 4  # word offset

            # ── B-format: B LABEL ─────────────────────────────────────────
            case Opcode.B:
                if len(tokens) < 2:
                    raise AssemblerError("Expected: B LABEL")
                label = tokens[1].strip()
                if label not in labels:
                    raise AssemblerError(f"Undefined label: {label!r}")
                instr.offset = (labels[label] - pc) // 4

            # ── HALT ──────────────────────────────────────────────────────
            case Opcode.HALT | Opcode.NOP:
                pass  # no operands

            case _:
                raise AssemblerError(f"Unhandled opcode: {op_str}")

        return instr
