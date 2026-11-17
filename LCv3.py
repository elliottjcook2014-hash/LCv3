import asyncio

print("init")
# Error codes:
# 0x00 = KERNEL PANIC
# 0x01 = SegFault
# 0x02 = InvalidOpcode
# 0x03 = InvalidRegister
# 0x04 = DivideByZero
# 0x05 = InvalidParam
print("loading kernel and virtual CPU")

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


class Task:
    READY = 0x0
    RUNNING = 0x1
    DEAD = 0x2

    STATE_NAMES = {
        READY: "READY",
        RUNNING: "RUNNING",
        DEAD: "DEAD"
    }

    def __init__(self, pid, name, bytecode, entry_point=0x0, stack_top=1023):
        self.pid = pid
        self.name = name
        self.bytecode = ByteList(bytecode)
        self.state = Task.READY

        # Saved CPU Context
        self.ip = entry_point
        self.sp = stack_top
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
        cpu.regs = ByteList(self.regs)
        cpu.zero_flag = self.zero_flag

    def kill(self):
        self.state = Task.DEAD

    def __repr__(self):
        state_str = self.STATE_NAMES.get(self.state, "UNKNOWN")
        return f"<Task pid={self.pid} name='{self.name}' state={state_str} ip={hex(self.ip)}>"


class vCPU:
    def __init__(self, ram, clock_speed):
        self.ram = ram
        self.ip = 0x0
        self.sp = ram.size - 1
        # 0: acc/syscall, 1: arg1/counter, 2: arg2/pointer, 3: scratch1, 4: scratch2
        self.regs = ByteList([0x0] * 5)
        self.zero_flag = False
        self.running = False
        self.clock_speed = clock_speed

        self.opcodes = {
            0x0: self.halt,
            0x1: self.mov,
            0x2: lambda: self._alu_process(lambda a, b: a + b),
            0x3: lambda: self._alu_process(lambda a, b: a - b),
            0x4: lambda: self._alu_process(lambda a, b: a * b),
            0x5: lambda: self._alu_process(self._safe_div),
            0x6: self.jmp,
            0x7: self.jiz,
            0x8: self.jnz,
            0x9: self.syscall,
            0xA: self.load,
            0xB: self.store,
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
        self.ip = self.fetch()

    def jiz(self):
        addr = self.fetch()
        if self.zero_flag:
            self.ip = addr

    def jnz(self):
        addr = self.fetch()
        if not self.zero_flag:
            self.ip = addr

    def syscall(self):
        raise SyscallInterrupt()

    def load(self):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        addr = self.fetch()
        self.regs[reg_idx] = self.ram.read(addr)

    def store(self):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        addr = self.fetch()
        self.ram.write(addr, self.regs[reg_idx])

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
    def __init__(self, ram_size=1024, clock_speed=1024):
        self.ram = RAM(ram_size)
        self.tasks = []
        self.named_tasks = {}
        self.next_pid = 0
        self.cpu = vCPU(self.ram, clock_speed)

        if self.cpu is None:
            self.panic("unloaded cpu")

        # Load the default idle task at 0x00 (gets pid 0, stack_top 1023)
        idle_task = self.create_task("idle", [0x00], start_addr=0x00)
        self.current_task = idle_task
        self.log("KERNEL", "Loaded successfully!")

    def load_program(self, task, start_addr=0x10):
        task.ip = start_addr
        for offset, byte in enumerate(task.bytecode):
            self.ram.write(start_addr + offset, byte)
        self.tasks.append(task)

    def create_task(self, name, bytecode, start_addr=0x10, stack_top=None):
        pid = self.next_pid
        self.next_pid += 1

        # Automatically allocate a 64-byte stack per task if not specified
        if stack_top is None:
            stack_top = (self.ram.size - 1) - (pid * 64)

        new_task = Task(pid, f"{name}_worker", bytecode, entry_point=start_addr, stack_top=stack_top)
        self.named_tasks[f"{name}_task"] = new_task
        self.load_program(new_task, start_addr=start_addr)
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
                if self.cpu.clock_speed > 0: await asyncio.sleep(1.0 / self.cpu.clock_speed)
            except SyscallInterrupt:
                self.handle_syscall()
                if not self.cpu.running:
                    break
            except CPUFault as e:
                self.log("KERNEL", f"Task {task.name} crashed {e}. Terminating task.")
                task.kill()
                self.cpu.running = False
                break
        
        task.save_context(self.cpu)
        if task.state != Task.DEAD:
            if not self.cpu.running:
                task.kill()
            else:
                task.state = Task.READY
    async def schedule(self, quantum_size=5):
        while True:
            ready_tasks = [t for t in self.tasks[1:] if t.state == Task.READY]
            if not ready_tasks:
                self.log("KERNEL", "No tasks.")
                break
        
            for task in ready_tasks:
                await self.run_quantum(task, quantum_size=quantum_size)

# --- Example Usage ---
async def main():
    kernel = Kernel(ram_size=1024, clock_speed=20)

    math_bytecode = [
        0x01, 0x04, 0x00, 0x00, 0x01, 0x03, 0x00, 0x01,
        0x01, 0x02, 0x00, 0x09, 0x02, 0x04, 0x01, 0x03,
        0x0B, 0x04, 0x80, 0x01, 0x00, 0x00, 0x01, 0x01,
        0x01, 0x01, 0x04, 0x09, 0x01, 0x00, 0x01, 0x04,
        0x01, 0x04, 0x01, 0x03, 0x01, 0x03, 0x01, 0x00,
        0x03, 0x02, 0x00, 0x01, 0x08, 0x1C, 0x00
    ]

    math_task = kernel.create_task("math", math_bytecode, start_addr=0x10)
    math_taskagain = kernel.create_task("mathagain", math_bytecode, start_addr=0x10)

    await kernel.schedule(quantum_size=5)


if __name__ == "__main__":
    asyncio.ensure_future(main())