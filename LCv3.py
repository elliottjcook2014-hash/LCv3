from time import sleep

print("init")
# Error codes:
# 000 = KERNEL PANIC
# uh idk what else
print("loading kernel and virtual CPU")


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

    def __init__(self, name, bytecode, entry_point=0x0, stack_top=1023):
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

    def mov(self):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        val = self.fetch()
        self.regs[reg_idx] = val

    def _alu_process(self, op_fn):
        reg_idx = self.fetch()
        self._check_reg(reg_idx)
        val = self.fetch()
        self.regs[reg_idx] = op_fn(self.regs[reg_idx], val)
        self.zero_flag = (self.regs[reg_idx] == 0)

    def _safe_div(self, a, b):
        if b == 0:
            raise DivideByZero(self.ip - 3)
        return a // b

    def step(self):
        opcode = self.fetch()
        if opcode in self.opcodes:
            self.opcodes[opcode]()
        else:
            raise InvalidOpcode(opcode, self.ip - 1)

    def run(self):
        self.running = True
        delay = 1.0 / self.clock_speed if self.clock_speed > 0 else 0
        while self.running:
            self.step()
            if delay > 0:
                sleep(delay)


class Kernel:
    def __init__(self, ram_size=1024, clock_speed=1024):
        self.ram = RAM(ram_size)
        self.tasks = []
        self.cpu = vCPU(self.ram, clock_speed)

        if self.cpu is None:
            self.panic("unloaded cpu")

        # Load the default idle task at 0x00
        idle_task = Task("idle", [0x00], stack_top=ram_size - 1)
        self.load_program(idle_task, start_addr=0x00)
        self.current_task = idle_task
        print("[KERNEL] Loaded successfully!")

    def load_program(self, task, start_addr=0x10):
        task.ip = start_addr
        for offset, byte in enumerate(task.bytecode):
            self.ram.write(start_addr + offset, byte)
        self.tasks.append(task)

    def boot(self, task=None):
        if task is not None:
            self.current_task = task

        self.current_task.state = Task.RUNNING
        self.current_task.restore_context(self.cpu)

        try:
            self.cpu.run()
            self.current_task.save_context(self.cpu)
            self.current_task.state = Task.READY
        except CPUFault as e:
            print(f"[KERNEL] Task '{self.current_task.name}' crashed -> CPU Fault {hex(e.code)}: {e}")
            self.current_task.kill()
            self.cpu.halt()
            self.current_task = self.tasks[0]
            self.current_task.restore_context(self.cpu)
        except Exception as e:
            self.panic(f"Unrecoverable kernel error: {e}")

    def panic(self, err):
        print("[KERNEL] CRITICAL ERROR: KILLING ALL PROCESSES. ERROR:", err)
        for t in self.tasks:
            try:
                t.kill()
            except Exception:
                pass
        raise KernelPanic("[KERNEL] KERNEL PANIC: CRITICAL SYSTEM ERROR. CODE 000")


# Valid Program
k = Kernel()
math_task = Task("math_worker", [0x01, 0x00, 0x03, 0x04, 0x00, 0x04, 0x00], stack_top=959)
k.load_program(math_task, start_addr=0x10)
k.boot(math_task)
print(f"{math_task.name} R0:", hex(math_task.regs[0]), "| State:", hex(math_task.state))

# Invalid Program
crash_task = Task("div_tester", [0x01, 0x00, 0x40, 0x05, 0x00, 0x00, 0x00], stack_top=895)
k.load_program(crash_task, start_addr=0x20)
k.boot(crash_task)
print(f"{crash_task.name} State:", hex(crash_task.state), "| Active task:", k.current_task.name)