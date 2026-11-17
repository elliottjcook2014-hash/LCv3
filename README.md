# LCv3
## A virtual computer I made in python
---
### Hello!
I am a 7th grader programmer. I've had a fascination with low-level architecture, and I've decided to make my own computer. However, this is not the first computer I have made.
I called the first one I made La Computadora, as a little computer thing. It ran on formulas and it was on google sheets. It wasn't very much of a computer, as you could only just type numbers in little cells and see the answer, no programming it was only a basic calculator.
The second generation, which I made it as a revision of the original, I called LCv2. It used an apps script to update a clock that would turn a clock cell into a random number, and when it changed, it updated the entire sheet so the formulas would calculate again. Every other logic was created in formulas, which was my challenge for myself.
It used an instruction pointer to get the opcode and parameter of the thing, put it into the processing area, then the next cycle it would go down the line, until it reached HLT (halt command)
Since it ran at about 1hz, I decided in class that I would try to make one in the pyodide ide (linux on the chromebooks is blocked, but it kinda helped because it can run fully in the browser using wasm, so thats something other projects don't really have) and it was very fun to code. The instructions are in the documentation.

## Okay enough of that massive wall of text. What are the features?
---
* It can run in a browser using pyodide (python fork to wasm)
* It is turing-complete
* It also has a virtual CPU and a kernel, a lot of the stuff is inspired by Linux.
---
# The documentation is in [docs/index.md](docs/index.md)
