// Benchmark: nested loop with a load-use stall, a store, and a taken branch per iteration
// ~8 cycles per inner iteration x 250 x 500 = ~1M cycles
// Not in programs/ so the directed harness run stays fast; used by: python harness.py --bench

ADDI X1, XZR, #500     // outer count
OUTER:
ADDI X2, XZR, #250     // inner count
INNER:
LDR  X3, [X10, #0]
ADD  X3, X3, X2        // load-use stall
STR  X3, [X10, #0]
SUBI X2, X2, #1
CBNZ X2, INNER         // taken: 2-cycle flush
SUBI X1, X1, #1
CBNZ X1, OUTER
HALT
