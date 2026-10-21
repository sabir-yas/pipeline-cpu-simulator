// Test 5: Stall and flush in the same cycle (forwarding OFF)
// EXPECT X1=1
// With forwarding off, ADD X2 stalls on X1 while B is taken in EX.
// The flush must win: ADD X2 is on the wrong path and must never execute.
//
// Expected results:
//   X1 = 1
//   X2 = 0  (skipped)

ADDI X1, XZR, #1
B    DONE
ADD  X2, X1, X1        // wrong path: squashed by the branch flush
DONE:
HALT
