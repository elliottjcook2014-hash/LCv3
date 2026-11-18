class assemblerException(Exception):
    pass


OPCODES = {
    "HALT":    0x00,
    "MOV":     0x01,
    "ADD":     0x02,
    "SUB":     0x03,
    "MUL":     0x04,
    "DIV":     0x05,
    "JMP":     0x06,
    "JIZ":     0x07,
    "JNZ":     0x08,
    "SYSCALL": 0x09,
    "LOAD":    0x0A,
    "STORE":   0x0B,
    "PUSH":    0x0C,
    "POP":     0x0D,
    "CALL":    0x0E,
    "RET":     0x0F,
}

NO_ARGS  = {"HALT", "SYSCALL", "RET"}     # 1 byte:  [opcode]
REG_ONLY = {"POP"}                        # 2 bytes: [opcode, reg]
ONE_VAL  = {"PUSH"}                       # 3 bytes: [opcode, mode, val/reg]
JUMPS    = {"JMP", "JIZ", "JNZ", "CALL"}  # 3 bytes: [opcode, addr_high, addr_low]
MEM_OPS  = {"LOAD", "STORE"}              # 4 bytes: [opcode, reg, addr_high, addr_low]
# Else (MOV, ADD, SUB, MUL, DIV)          # 4 bytes: [opcode, reg, mode, val/reg]

REGS = {
    "R0": 0x00,
    "R1": 0x01,
    "R2": 0x02,
    "R3": 0x03,
    "R4": 0x04,
}


def assemble(source, start_addr=0x10):
    labels = {}
    instructions = []
    addr = start_addr

    # Pass 1: Record label addresses and measure instruction byte sizes
    for line_num, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.split(";")[0].strip()
        if not line:
            continue

        if line.endswith(":"):
            label_name = line[:-1].strip().upper()
            if not label_name:
                raise assemblerException(f"Line {line_num}: Empty label name.")
            labels[label_name] = addr
            continue

        parts = [p.strip() for p in line.replace(",", " ").split()]
        mnemonic = parts[0].upper()

        if mnemonic not in OPCODES:
            raise assemblerException(f"Line {line_num}: Unknown instruction '{mnemonic}'")

        instructions.append((line_num, mnemonic, parts))

        if mnemonic in NO_ARGS:
            addr += 1                     # 1 byte: [opcode]
        elif mnemonic in REG_ONLY:
            addr += 2                     # 2 bytes: [opcode, reg]
        elif mnemonic in ONE_VAL:
            addr += 3                     # 3 bytes: [opcode, mode, val/reg]
        elif mnemonic in JUMPS:
            addr += 3                     # 3 bytes: [opcode, addr_high, addr_low]
        elif mnemonic in MEM_OPS:
            addr += 4                     # 4 bytes: [opcode, reg, addr_high, addr_low]
        else:
            addr += 4                     # 4 bytes: [opcode, reg, mode, val/reg]

    # Pass 2: Emit bytecode
    bytecode = []
    for line_num, mnemonic, parts in instructions:
        bytecode.append(OPCODES[mnemonic])

        if mnemonic in NO_ARGS:           # 1 byte: [opcode]
            continue

        elif mnemonic in REG_ONLY:        # 2 bytes: [opcode, reg]
            if len(parts) != 2:
                raise assemblerException(f"Line {line_num}: {mnemonic} needs 1 register, {len(parts) - 1} were given.")
            reg_name = parts[1].upper()
            if reg_name not in REGS:
                raise assemblerException(f"Line {line_num}: Unknown register {reg_name}. The registers start at R0!")
            bytecode.append(REGS[reg_name])

        elif mnemonic in ONE_VAL:         # 3 bytes: [opcode, mode, val/reg]
            if len(parts) != 2:
                raise assemblerException(f"Line {line_num}: {mnemonic} needs 1 argument, {len(parts) - 1} were given.")
            arg = parts[1].upper()
            if arg in REGS:
                bytecode.append(0x01)     # Mode 1: Register
                bytecode.append(REGS[arg])
            else:
                val = int(parts[1], 0) & 0xFF
                bytecode.append(0x00)     # Mode 0: Immediate number
                bytecode.append(val)

        elif mnemonic in JUMPS:           # 3 bytes: [opcode, addr_high, addr_low]
            if len(parts) != 2:
                raise assemblerException(f"Line {line_num}: {mnemonic} needs 1 target, {len(parts) - 1} were given.")
            target = parts[1].upper()
            target_addr = labels[target] if target in labels else int(parts[1], 0)
            bytecode.append((target_addr >> 8) & 0xFF)
            bytecode.append(target_addr & 0xFF)

        elif mnemonic in MEM_OPS:         # 4 bytes: [opcode, reg, addr_high, addr_low]
            if len(parts) != 3:
                raise assemblerException(f"Line {line_num}: {mnemonic} needs 2 arguments, {len(parts) - 1} were given.")
            reg_name = parts[1].upper()
            if reg_name not in REGS:
                raise assemblerException(f"Line {line_num}: Unknown register {reg_name}. The registers start at R0!")
            bytecode.append(REGS[reg_name])
            target = parts[2].upper()
            mem_addr = labels[target] if target in labels else int(parts[2], 0)
            bytecode.append((mem_addr >> 8) & 0xFF)
            bytecode.append(mem_addr & 0xFF)

        else:                             # 4 bytes: [opcode, reg, mode, val/reg]
            if len(parts) != 3:
                raise assemblerException(f"Line {line_num}: {mnemonic} needs 2 arguments, {len(parts) - 1} were given.")

            reg_name = parts[1].upper()
            if reg_name not in REGS:
                raise assemblerException(f"Line {line_num}: Unknown register {reg_name}. The registers start at R0!")

            bytecode.append(REGS[reg_name])

            arg2 = parts[2].upper()
            if arg2 in REGS:
                bytecode.append(0x01)     # Mode 1: Register
                bytecode.append(REGS[arg2])
            else:
                val = int(parts[2], 0) & 0xFF
                bytecode.append(0x00)     # Mode 0: Immediate number
                bytecode.append(val)

    return bytecode


if __name__ == "__main__":
    recovery_menu = """
    MOV R1, 5
    CALL DOUBLE
    MOV R0, 1
    SYSCALL
    HALT
    
    DOUBLE:
        ADD R1, R1
        RET
"""

    result = assemble(recovery_menu, start_addr=0x10)
    formatted = ", ".join(f"0x{b:02X}" for b in result)
    print(f"bytecode: [{formatted}]")