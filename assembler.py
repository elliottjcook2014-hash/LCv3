class assemblerException(Exception):
    pass

OPCODES = {
    "HALT": 0x00,
    "MOV":  0x01,
    "ADD":  0x02,
    "SUB":  0x03,
    "MUL":  0x04,
    "DIV":  0x05,
}

REGS = {
    "R0": 0x00,
    "R1": 0x01,
    "R2": 0x02,
    "R3": 0x03,
    "R4": 0x04,
    "R5": 0x05
}

def assemble(source):
    bytecode = []
    for line_num, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.split(';')[0].strip()
        if not line:
            continue

        parts = [p.strip() for p in line.replace(',', " ").split()]
        mnemonic = parts[0].upper()

        if mnemonic not in OPCODES:
            raise ValueError(f"Line {line_num}: Unknown instruction '{mnemonic}'")

        opcode = OPCODES[mnemonic]
        bytecode.append(opcode)

        if mnemonic != "HALT":
            if len(parts) != 3:
                raise ValueError(f"Line {line_num}: {mnemonic} needs 2 arguments, {len(parts)} were given.")

            reg_name = parts[1].upper()
            if reg_name not in REGS:
                raise ValueError(f"Line {line_num}: Unknown register {reg_name}. The registers start at R0!")

            val = int(parts[2], 0) & 0xFF

            bytecode.append(REGS[reg_name])
            bytecode.append(val)
    return bytecode


if __name__ == "__main__":
    program = """
    ; calc 3*4
    MOV R0, 0x3
    MUL R0, 4
    HALT
    """

    result = assemble(program)
    formatted = ", ".join(f"0x{b:02X}" for b in result)
    print(f"bytecode: [{formatted}]")