// Test 1: RAW Data Hazards
// Demonstrates forwarding paths (EX/MEM and MEM/WB forwarding)
// With forwarding ON: minimal stalls
// With forwarding OFF: multiple stall cycles required
//
// Expected results:
//   X1 = 10, X2 = 20, X3 = 30, X4 = 20, X5 = 20, X6 = 26

ADDI X1, XZR, #10      // X1 = 10
ADDI X2, XZR, #20      // X2 = 20
ADD  X3, X1, X2        // X3 = 30  [EX/MEM fwd X1, MEM/WB fwd X2]
SUB  X4, X3, X1        // X4 = 20  [EX/MEM fwd X3]
AND  X5, X3, X4        // X5 = 20  [EX/MEM fwd X4, MEM/WB fwd X3]
ORR  X6, X5, X1        // X6 = 26  [EX/MEM fwd X5]
HALT
