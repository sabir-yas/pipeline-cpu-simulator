// Test 4: Forwarding corner cases
// EXPECT X1=2 X2=2 X3=64 X4=7 X5=7 X6=1
// Targets paths tests 1-3 don't reach (used by harness.py fault injection)
//
// Expected results:
//   X1 = 2  (written twice back to back)
//   X2 = 2  (newest value: EX/MEM must beat MEM/WB)
//   X3 = 64, X4 = 7, X5 = 7, X6 = 1
//   X7 = 0  (XZR stays zero)
//   mem[64] = 7

ADDI XZR, XZR, #5      // write to XZR must be discarded
ADDI X1, XZR, #1
ADDI X1, XZR, #2       // X1 written twice back to back
ADD  X2, X1, XZR       // X2 = 2: EX/MEM (newest) has priority over MEM/WB
ADDI X3, XZR, #64      // base address
ADDI X4, XZR, #7
STR  X4, [X3, #0]      // store data X4 forwarded from EX/MEM
LDR  X5, [X3, #0]      // X5 = 7
CBZ  X5, SKIP          // condition is a just-loaded reg: load-use stall + MEM/WB fwd (not taken)
ADDI X6, XZR, #1       // X6 = 1
SKIP:
ADD  X7, XZR, XZR      // X7 = 0
HALT
