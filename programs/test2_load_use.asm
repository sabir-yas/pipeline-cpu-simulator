// Test 2: Load-Use Hazard + Memory Operations
// Demonstrates the unavoidable load-use stall (1 cycle even with forwarding)
// Also shows STR->LDR memory round-trip
//
// Memory layout: address 0 = 100, address 8 = 200
// Expected results:
//   X1 = 4 (base addr)
//   X2 = 100 (loaded from mem[0] after init)
//   X3 = 200 (X2 + X2 after load-use stall)
//   X5 = 99 (stored then reloaded)

ADDI X9, XZR, #100     // X9 = 100
ADDI X10, XZR, #200    // X10 = 200
ADDI X1, XZR, #0       // X1 = base address 0
STR  X9,  [X1, #0]     // mem[0] = 100
STR  X10, [X1, #8]     // mem[8] = 200
LDR  X2, [X1, #0]      // X2 = mem[0] = 100  [load-use stall on next]
ADD  X3, X2, X2        // X3 = 200            [stall 1 cycle: load-use on X2]
LDR  X4, [X1, #8]      // X4 = mem[8] = 200
ADDI X5, XZR, #99
STR  X5, [X1, #0]      // mem[0] = 99
LDR  X6, [X1, #0]      // X6 = 99
ADD  X7, X6, XZR       // X7 = 99             [stall 1 cycle: load-use on X6]
HALT
