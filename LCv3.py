# TODO:
# Add memory allocation (malloc and free in C basically but with syscalls)
# Add BIOS
# Rewrite kernel in the assembly

import asyncio
import js
from pyodide.ffi import create_proxy

print("init")
# Error codes:
# 0x00 = KERNEL PANIC
# 0x01 = SegFault
# 0x02 = InvalidOpcode
# 0x03 = InvalidRegister
# 0x04 = DivideByZero
# 0x05 = InvalidParam
print("loading...")
print("Starting BIOS")

# Errors

class KernelPanic(Exception):
    pass


class CPUFault(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class SegFault(CPUFault):
    def __init__(self, addr):
        super().__init__(0x01, f"Segmentation fault at {hex(addr)}")


class InvalidOpcode(CPUFault):
    def __init__(self, opcode, addr):
        super().__init__(0x02, f"Invalid opcode {hex(opcode)} at {hex(addr)}")


class InvalidRegister(CPUFault):
    def __init__(self, reg, addr):
        super().__init__(0x03, f"Invalid register index {reg} at {hex(addr)}")


class DivideByZero(CPUFault):
    def __init__(self, addr):
        super().__init__(0x04, f"Division by zero at {hex(addr)}")


class InvalidParam(CPUFault):
    def __init__(self, addr):
        super().__init__(0x05, f"Invalid parameter at {hex(addr)}")


class SyscallInterrupt(Exception):
    pass


# Classes

class ByteList(list):
    def __init__(self, iterable=()):
        super().__init__(x & 0xFF for x in iterable)

    def __setitem__(self, index, value):
        super().__setitem__(index, value & 0xFF)

    def append(self, value):
        super().append(value & 0xFF)


class MemoryBus:
    def __init__(self):
        self.size = 0
        self.mappings = []

    def _resolve(self, addr):  # Finds matching device and translates to local offset
        for start, end, device in self.mappings:
            if start <= addr <= end:
                return device, addr - start
        raise SegFault(addr)

    def register_memory_device(self, start_addr, end_addr, device):
        if not isinstance(device, RAM):  # Covers both RAM and ROM (since ROM inherits RAM)
            raise ValueError("Device must be a RAM or ROM instance")
        if (end_addr - start_addr + 1) != device.size:
            raise ValueError("Address range length does not match device size")

        self.mappings.append((start_addr, end_addr, device))
        self.size = max(self.size, end_addr + 1)

    def read(self, addr):
        device, offset = self._resolve(addr)
        return device.read(offset)

    def write(self, addr, val):
        device, offset = self._resolve(addr)
        device.write(offset, val)


class RAM:
    def __init__(self, size):
        self.data = ByteList([0x0] * size)
        self.size = size

    def read(self, addr):
        if addr < 0 or addr >= self.size:
            raise SegFault(addr)
        return self.data[addr]

    def write(self, addr, val):
        if addr < 0 or addr >= self.size:
            raise SegFault(addr)
        self.data[addr] = val


class ROM(RAM):
    def __init__(self, bytecode):
        super().__init__(len(bytecode))
        self.data = ByteList(bytecode)

    def write(self, addr, val):
        raise SegFault(addr)


class Keyboard(ROM):
    def __init__(self):
        super().__init__([0x00])
        self.buffer = []
        self._on_key_proxy = create_proxy(self._on_keydown)
        js.window.addEventListener("keydown", self._on_key_proxy)

    def _on_keydown(self, event):
        key = event.key
        if key == "Enter":
            self.buffer.append(0x0A)
        elif key == "Backspace":
            self.buffer.append(0x08)
        elif key == "Escape":
            self.buffer.append(0x1B)
        elif len(key) == 1:
            self.buffer.append(ord(key) & 0xFF)

    def read(self, addr):
        if self.buffer:
            self.data[0] = self.buffer.pop(0)
        else:
            self.data[0] = 0x00
        return self.data[0]


class Program:
    def __init__(self, name, bytecode, start_addr, end_addr):
        self.name = name
        self.bytecode = ByteList(bytecode)
        self.start = start_addr
        self.end = end_addr


class Task:
    READY = 0x0
    RUNNING = 0x1
    DEAD = 0x2

    STATE_NAMES = {
        READY: "READY",
        RUNNING: "RUNNING",
        DEAD: "DEAD"
    }

    PERMS = {
        "print": True,
        "mem_write": True,
        "mem_read": True,
        "mem_global": False,
    }

    def __init__(self, pid, name, program, stack_top, stack_size=64, daemon=False):
        self.pid = pid
        self.name = name
        self.program = program
        self.state = Task.READY
        self.daemon = daemon

        # Saved CPU Context
        self.ip = program.start
        self.sp = stack_top
        self.stack_top = stack_top
        self.stack_limit = stack_top - stack_size + 1
        self.regs = ByteList([0x0] * 5)
        self.zero_flag = False

    def save_context(self, cpu):
        self.ip = cpu.ip
        self.sp = cpu.sp
        self.regs = ByteList(cpu.regs)
        self.zero_flag = cpu.zero_flag

    def restore_context(self, cpu):
        cpu.ip = self.ip
        cpu.sp = self.sp
        cpu.stack_top = self.stack_top
        cpu.stack_limit = self.stack_limit
        cpu.regs = ByteList(self.regs)
        cpu.zero_flag = self.zero_flag

    def kill(self):
        self.state = Task.DEAD

    def can(self, action):
        return Task.PERMS.get(action, True)

    def __repr__(self):
        state_str = self.STATE_NAMES.get(self.state, "UNKNOWN")
        return f"<Task pid={self.pid} name='{self.name}' state={state_str} ip={hex(self.ip)}>"


class vCPU:
    def __init__(self, ram, clock_speed):
        self.ram = ram
        self.ip = 0x0
        self.sp = ram.size - 2
        self.stack_top = ram.size - 2
        self.stack_limit = 0x0000
        # 0: acc/syscall, 1: arg1/counter, 2: arg2/pointer, 3: scratch1, 4: scratch2
        self.regs = ByteList([0x0] * 5)
        self.zero_flag = False
        self.running = False
        self.clock_speed = clock_speed

        self.opcodes = {
            0x00: self.halt,
            0x01: self.mov,
            0x02: lambda: self._alu_process(lambda a, b: a + b),
            0x03: lambda: self._alu_process(lambda a, b: a - b),
            0x04: lambda: self._alu_process(lambda a, b: a * b),
            0x05: lambda: self._alu_process(self._safe_div),
            0x06: self.jmp,
            0x07: self.jiz,
            0x08: self.jnz,
            0x09: self.syscall,
            0x0A: self.load,
            0x0B: self.store,
            0x0C: self.push,
            0x0D: self.pop,
            0x0E: self.call,
            0x0F: self.ret
        }

    def fetch(self):
        val = self.ram.read(self.ip)
        self.ip += 1
        return val

    def halt(self):
        self.running = False

    def _check_reg(self, reg_idx):
        if reg_idx >= len(self.regs):
            raise InvalidRegister(reg_idx, self.ip - 2)

    def _resolve_operand(self):
        mode = self.fetch()
        val = self.fetch()
        if mode == 0x0:
            return val
        elif mode == 0x1:
            self._check_reg(val)
            return self.regs[val]
        else:
            raise InvalidParam(self.ip - 2)

    def mov(self):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        self.regs[reg_idx] = self._resolve_operand()

    def _alu_process(self, op_fn):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        operand = self._resolve_operand()
        self.regs[reg_idx] = op_fn(self.regs[reg_idx], operand)
        self.zero_flag = (self.regs[reg_idx] == 0)

    def _safe_div(self, a, b):
        if b == 0:
            raise DivideByZero(self.ip - 4)
        return a // b

    def jmp(self):
        self.ip = self.fetch_addr()

    def jiz(self):
        addr = self.fetch_addr()
        if self.zero_flag:
            self.ip = addr

    def jnz(self):
        addr = self.fetch_addr()
        if not self.zero_flag:
            self.ip = addr

    def syscall(self):
        raise SyscallInterrupt()

    def fetch_addr(self):
        big = self.fetch()
        little = self.fetch()
        return (big << 8) | little

    def load(self):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        addr = self.fetch_addr()
        self.regs[reg_idx] = self.ram.read(addr)

    def store(self):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        addr = self.fetch_addr()
        self.ram.write(addr, self.regs[reg_idx])

    def push(self):
        val = self._resolve_operand()
        if self.sp < self.stack_limit:
            raise SegFault(self.sp)
        self.ram.write(self.sp, val)
        self.sp -= 1

    def pop(self):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        if self.sp >= self.stack_top:
            raise SegFault(self.sp)
        self.sp += 1
        val = self.ram.read(self.sp)
        self.regs[reg_idx] = val
        
    def call(self):
        target_addr = self.fetch_addr()
        if self.sp - 1 < self.stack_limit:
            raise SegFault(self.sp)
        self.ram.write(self.sp, (self.ip >> 8) & 0xFF)
        self.sp -= 1
        self.ram.write(self.sp, (self.ip) & 0xFF)
        self.sp -= 1
        self.ip = target_addr
        
    def ret(self):
        if self.sp + 2 > self.stack_top:
            raise SegFault(self.ip)
        self.sp += 1
        low = self.ram.read(self.sp)
        self.sp += 1
        high = self.ram.read(self.sp)
        self.ip = (high << 8) | low

    def step(self):
        opcode = self.fetch()
        if opcode in self.opcodes:
            self.opcodes[opcode]()
        else:
            raise InvalidOpcode(opcode, self.ip - 1)

    async def run(self):
        self.running = True
        delay = 1.0 / self.clock_speed if self.clock_speed > 0 else 0
        while self.running:
            self.step()
            if delay > 0:
                await asyncio.sleep(delay)


class Kernel:
    def __init__(self, bootloader, ram_size=1024, clock_speed=1024):
        self.bus = MemoryBus()
        self.rom = bootloader
        self.keyboard = Keyboard()
        self.ram_device = RAM(ram_size - self.rom.size - self.keyboard.size)

        self.bus.register_memory_device(0x000, self.rom.size - 1, self.rom)
        self.bus.register_memory_device(self.rom.size, ram_size - 2, self.ram_device)
        self.bus.register_memory_device(ram_size - 1, ram_size - 1, self.keyboard)
        self.ram = self.bus

        self.tasks = []
        self.named_tasks = {}
        self.next_pid = 0
        self.cpu = vCPU(self.ram, clock_speed)

        if self.cpu is None:
            self.panic("unloaded cpu")

        # Load the default idle task (gets pid 0, stack_top 1022)
        idle_program = self.create_program("idle", [0x00], start_addr=0x00)
        idle_task = self.create_task("idle", idle_program)
        self.current_task = idle_task
        self.log("KERNEL", "Loaded successfully!")

    def create_program(self, name, bytecode, start_addr=0x10):
        prog_bytes = ByteList(bytecode)
        end_addr = start_addr + len(prog_bytes) - 1
        program = Program(name, prog_bytes, start_addr, end_addr)
        if start_addr >= self.rom.size:
            for offset, byte in enumerate(program.bytecode):
                self.ram.write(start_addr + offset, byte)
        return program

    def create_task(self, name, program, stack_top=None, daemon=False):
        pid = self.next_pid
        self.next_pid += 1

        # Automatically allocate a 64-byte stack per task if not specified (below 0x3FF keyboard port)
        if stack_top is None:
            stack_top = (self.ram.size - 2) - (pid * 64)

        new_task = Task(pid, f"{name}_worker", program, stack_top, daemon=daemon)
        self.named_tasks[f"{name}_task"] = new_task
        self.tasks.append(new_task)
        return new_task

    async def boot(self, task=None):
        if task is not None:
            self.current_task = task

        self.current_task.state = Task.RUNNING
        self.current_task.restore_context(self.cpu)
        self.log("KERNEL", f"Booting {self.current_task}")

        while True:
            try:
                await self.cpu.run()
                self.current_task.save_context(self.cpu)
                if self.current_task.state != Task.DEAD:
                    self.current_task.state = Task.READY
                break
            except SyscallInterrupt:
                self.handle_syscall()
            except CPUFault as e:
                self.log("KERNEL", f"Task '{self.current_task.name}' (PID {self.current_task.pid}) crashed -> CPU Fault {hex(e.code)}: {e}")
                self.current_task.kill()
                self.cpu.halt()
                self.current_task = self.tasks[0]
                self.current_task.restore_context(self.cpu)
                break
            except Exception as e:
                self.panic(f"Unrecoverable kernel error: {e}")
                break

    def handle_syscall(self):
        syscall_id = self.cpu.regs[0]
        arg1 = self.cpu.regs[1]
        if syscall_id == 0x00:
            self.current_task.kill()
            self.cpu.halt()
        elif syscall_id == 0x01:      # Print integer
            self.log(self.current_task.name, arg1)
        elif syscall_id == 0x02:      # Print ASCII character
            print(chr(arg1), end="")
        else:
            self.log("KERNEL", f"Unknown syscall: {hex(syscall_id)}")

    def panic(self, err):
        self.log("KERNEL", "CRITICAL ERROR: KILLING ALL PROCESSES. ERROR:", err)
        for t in self.tasks:
            try:
                t.kill()
            except Exception:
                pass
        raise KernelPanic("[KERNEL] KERNEL PANIC: CRITICAL SYSTEM ERROR. CODE 000")

    def log(self, name, text, *args):
        extra = " ".join(str(a) for a in args)
        msg = f"[{name}] {text} {extra}".strip()
        print(msg)

    async def run_quantum(self, task, quantum_size=5):
        self.current_task = task
        task.state = Task.RUNNING
        task.restore_context(self.cpu)
        self.cpu.running = True

        for _ in range(quantum_size):
            if not self.cpu.running:
                break
            try:
                self.cpu.step()
                if self.cpu.clock_speed > 0:
                    await asyncio.sleep(1.0 / self.cpu.clock_speed)
            except SyscallInterrupt:
                self.handle_syscall()
                if not self.cpu.running:
                    break
            except CPUFault as e:
                if task.daemon:
                    self.log("KERNEL", f"Daemon {task.name} crashed ({e}). Restarting.")
                    self.cpu.ip = task.program.start
                    self.cpu.regs = ByteList([0x0] * 5)
                    self.cpu.zero_flag = False
                    self.cpu.running = True
                else:
                    self.log("KERNEL", f"Task {task.name} crashed {e}. Terminating task.")
                    task.kill()
                    self.cpu.running = False
                break

        task.save_context(self.cpu)
        if task.state != Task.DEAD:
            if not self.cpu.running:
                if task.daemon:
                    task.ip = task.program.start
                    task.state = Task.READY
                else:
                    task.kill()
            else:
                task.state = Task.READY

    async def schedule(self, quantum_size=5):
        while True:
            ready_tasks = [t for t in self.tasks[1:] if t.state == Task.READY]
            if not ready_tasks or all(t.daemon for t in ready_tasks):
                self.log("KERNEL", "No foreground tasks left.")
                break

            for task in ready_tasks:
                await self.run_quantum(task, quantum_size=quantum_size)

            await asyncio.sleep(0)


# --- Example Usage ---
async def main():
    bootcode = [0x00]
    bootloader = ROM(bootcode)

    kernel = Kernel(bootloader, ram_size=1024, clock_speed=0)

    # PUSH 10 -> POP R2 -> MOV R0, 1 -> MOV R1, R2 -> SYSCALL -> HALT
    math_bytecode = [0x01, 0x01, 0x00, 0x05, 0x0E, 0x00, 0x1D, 0x01, 0x00, 0x00, 0x01, 0x09, 0x00, 0x02, 0x01, 0x01, 0x01, 0x0F]

    math_program = kernel.create_program("math", math_bytecode, start_addr=0x10)
    math_task = kernel.create_task("math", math_program)

    await kernel.schedule(quantum_size=5)


if __name__ == "__main__":
    asyncio.ensure_future(main())