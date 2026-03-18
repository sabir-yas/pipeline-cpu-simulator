// Test 3: Branch Hazards + Loop
// Demonstrates 2-cycle branch penalty (flush) on taken branches
// Loop computes sum = 5+4+3+2+1 = 15
//
// CBZ: branch taken when register == 0  (2-cycle flush penalty)
// B:   unconditional branch            (always 2-cycle flush penalty)
//
// Expected results:
//   X1 = 0  (counter decremented to 0)
//   X2 = 15 (accumulated sum)
//   X4 = 15 (copy of X2)

ADDI X1, XZR, #5       // X1 = 5  (loop counter)
ADDI X2, XZR, #0       // X2 = 0  (accumulator)
ADDI X3, XZR, #1       // X3 = 1  (constant)
LOOP:
ADD  X2, X2, X1        // X2 += X1
SUBI X1, X1, #1        // X1 -= 1
CBZ  X1, DONE          // if X1==0, exit loop  [flush on last iteration]
B    LOOP              // else loop back       [flush every iteration]
DONE:
ADD  X4, X2, XZR       // X4 = final sum = 15
HALT
