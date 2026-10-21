// LEGv8 5-stage pipeline: C++ port of the Python reference model (simulator.py + cpu/).
// Mirrors it stage for stage so per-cycle traces can be diffed by harness.py.
//
// Usage: legv8 <decoded.txt> <fwd 0|1> [fault] [max_cycles] [-q]
// -q: no per-cycle trace; END line adds the simulation loop's wall time (benchmarking)
// decoded.txt: one instruction per line, "OP rd rn rm rt imm offset pc" (-1 = unused register)
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <unordered_map>
#include <vector>

using u64 = uint64_t;
using i64 = int64_t;
using ull = unsigned long long;

enum Op { ADD, ADDI, SUB, SUBI, AND, ORR, LDR, STR, CBZ, CBNZ, B, HALT, NOP, NUM_OPS };
static const char* OP_NAMES[] = {"ADD", "ADDI", "SUB", "SUBI", "AND", "ORR", "LDR",
                                 "STR", "CBZ", "CBNZ", "B", "HALT", "NOP"};
enum AluOp { A_NONE, A_ADD, A_SUB, A_AND, A_ORR, A_PASS };

// Mirrors OPCODE_META in cpu/isa.py
struct Meta { AluOp alu; bool reg_write, mem_read, mem_write, mem_to_reg, alu_src, branch; };
static const Meta META[] = {
    {A_ADD,  1, 0, 0, 0, 0, 0},  // ADD
    {A_ADD,  1, 0, 0, 0, 1, 0},  // ADDI
    {A_SUB,  1, 0, 0, 0, 0, 0},  // SUB
    {A_SUB,  1, 0, 0, 0, 1, 0},  // SUBI
    {A_AND,  1, 0, 0, 0, 0, 0},  // AND
    {A_ORR,  1, 0, 0, 0, 0, 0},  // ORR
    {A_ADD,  1, 1, 0, 1, 1, 0},  // LDR
    {A_ADD,  0, 0, 1, 0, 1, 0},  // STR
    {A_PASS, 0, 0, 0, 0, 0, 1},  // CBZ
    {A_PASS, 0, 0, 0, 0, 0, 1},  // CBNZ
    {A_NONE, 0, 0, 0, 0, 0, 1},  // B
    {A_NONE, 0, 0, 0, 0, 0, 0},  // HALT
    {A_NONE, 0, 0, 0, 0, 0, 0},  // NOP
};

// ── Injectable faults (harness.py checks each one is caught) ──────────────────
enum Fault {
    NO_FAULT,
    NO_FWD_EXMEM,       // EX/MEM forwarding path missing
    NO_FWD_MEMWB,       // MEM/WB forwarding path missing
    FWD_PRIORITY,       // MEM/WB wins over EX/MEM when both match
    NO_LOAD_USE_STALL,  // load-use hazard not detected
    NO_FLUSH,           // taken branch redirects PC but squashes nothing
    SHORT_FLUSH,        // 1-cycle branch penalty: same final state, wrong timing
    STR_NO_DATA_FWD,    // store data (Rt) not tracked by forwarding unit
    CBZ_READS_RN,       // CBZ/CBNZ condition read from Rn instead of Rt
    XZR_WRITABLE,       // writes to XZR stick
    NUM_FAULTS
};
static const char* FAULT_NAMES[] = {"none", "no_fwd_exmem", "no_fwd_memwb", "fwd_priority",
                                    "no_load_use_stall", "no_flush", "short_flush",
                                    "str_no_data_fwd", "cbz_reads_rn", "xzr_writable"};
static Fault fault = NO_FAULT;

struct Instr {
    Op op = NOP;
    int rd = -1, rn = -1, rm = -1, rt = -1;  // -1 = unused (Python None)
    i64 imm = 0, offset = 0, pc = 0;

    const Meta& m() const { return META[op]; }
    int dest_reg() const { return op == LDR ? rt : m().reg_write ? rd : -1; }
    // Instruction.source_regs membership
    bool reads(int r) const {
        return r == rn || r == rm || ((op == STR || op == CBZ || op == CBNZ) && r == rt);
    }
};

// ── Pipeline registers (cpu/pipeline_regs.py) ────────────────────────────────
struct IF_ID { Instr instr; bool valid = false; };
struct ID_EX {
    Instr instr;
    u64 read_data1 = 0, read_data2 = 0;
    i64 sign_ext_imm = 0;
    int rn = 31, rm = 31, rd = 31, rt = 31;
    bool reg_write = false, mem_read = false, mem_write = false, mem_to_reg = false;
    bool alu_src = false, branch = false, valid = false;
    AluOp alu_op = A_NONE;
};
struct EX_MEM {
    Instr instr;
    u64 alu_result = 0, read_data2 = 0;
    int dest_reg = 31;
    bool branch_taken = false;
    i64 branch_target = 0;
    bool reg_write = false, mem_read = false, mem_write = false, mem_to_reg = false, valid = false;
};
struct MEM_WB {
    Instr instr;
    u64 alu_result = 0, mem_data = 0;
    int dest_reg = 31;
    bool reg_write = false, mem_to_reg = false, valid = false;
};

enum Src { SRC_NONE, SRC_EXMEM, SRC_MEMWB };

struct Sim {
    bool fwd_enabled = true;
    u64 regs[32] = {};
    std::unordered_map<u64, u64> dmem;
    std::vector<Instr> imem;
    IF_ID if_id; ID_EX id_ex; EX_MEM ex_mem; MEM_WB mem_wb;
    i64 pc = 0;
    u64 cycles = 0, retired = 0, stalls = 0, flushes = 0;
    bool halted = false;
    // Per-cycle trace info
    bool stalled = false, flushed = false, stored = false;
    u64 store_addr = 0, store_val = 0;

    u64 reg_read(int i) const { return (i == 31 && fault != XZR_WRITABLE) ? 0 : regs[i]; }
    void reg_write(int i, u64 v) { if (i != 31 || fault == XZR_WRITABLE) regs[i] = v; }

    Instr fetch(i64 addr) const {
        i64 idx = addr / 4;
        if (idx < 0 || idx >= (i64)imem.size()) { Instr nop; nop.pc = addr; return nop; }
        return imem[idx];
    }

    // ── Hazard unit (cpu/hazard.py) ──
    bool load_use_stall() const {
        if (!id_ex.mem_read || id_ex.rt == 31) return false;
        return if_id.instr.reads(id_ex.rt);
    }

    bool raw_stall_no_forwarding() const {
        const Instr& s = if_id.instr;
        int d = id_ex.instr.dest_reg();
        if (id_ex.reg_write && d != -1 && d != 31 && s.reads(d)) return true;
        if (ex_mem.reg_write && ex_mem.dest_reg != 31 && s.reads(ex_mem.dest_reg)) return true;
        if (mem_wb.reg_write && mem_wb.dest_reg != 31 && s.reads(mem_wb.dest_reg)) return true;
        return false;
    }

    void forwarding(Src& a, Src& b) const {
        a = b = SRC_NONE;
        if (!fwd_enabled) return;
        bool ex = ex_mem.reg_write && ex_mem.dest_reg != 31 && fault != NO_FWD_EXMEM;
        bool mw = mem_wb.reg_write && mem_wb.dest_reg != 31 && fault != NO_FWD_MEMWB;
        auto check = [&](bool ok, int dest, Src src) {
            if (!ok) return;
            if (dest == id_ex.rn && a == SRC_NONE) a = src;
            if (dest == id_ex.rm && b == SRC_NONE) b = src;
        };
        if (fault == FWD_PRIORITY) {
            check(mw, mem_wb.dest_reg, SRC_MEMWB);
            check(ex, ex_mem.dest_reg, SRC_EXMEM);
        } else {
            check(ex, ex_mem.dest_reg, SRC_EXMEM);  // EX hazard has priority
            check(mw, mem_wb.dest_reg, SRC_MEMWB);
        }
    }

    // ── Stages (cpu/stages.py) ──
    ID_EX stage_id() const {
        const Instr& in = if_id.instr;
        ID_EX o;
        int rn = in.rn < 0 ? 31 : in.rn, rm = in.rm < 0 ? 31 : in.rm;
        int rd = in.rd < 0 ? 31 : in.rd, rt = in.rt < 0 ? 31 : in.rt;

        if ((in.op == CBZ || in.op == CBNZ) && fault != CBZ_READS_RN) {
            o.read_data1 = reg_read(rt);  // condition reg in rn slot so forward_a covers it
            o.read_data2 = 0;
            rn = rt;
        } else if (in.op == STR) {
            o.read_data1 = reg_read(rn);  // base address
            o.read_data2 = reg_read(rt);  // store data
            if (fault != STR_NO_DATA_FWD) rm = rt;  // so forward_b covers store data
        } else {
            o.read_data1 = reg_read(rn);
            o.read_data2 = reg_read(rm);
        }

        o.sign_ext_imm = (in.op == ADDI || in.op == SUBI) ? in.imm : in.offset;
        o.instr = in;
        o.rn = rn; o.rm = rm; o.rd = rd; o.rt = rt;
        const Meta& m = in.m();
        o.reg_write = m.reg_write; o.mem_read = m.mem_read; o.mem_write = m.mem_write;
        o.mem_to_reg = m.mem_to_reg; o.alu_src = m.alu_src; o.branch = m.branch;
        o.alu_op = m.alu;
        o.valid = if_id.valid;
        return o;
    }

    EX_MEM stage_ex(Src fa, Src fb) const {
        auto fwd = [&](Src s, u64 own) {
            if (s == SRC_EXMEM) return ex_mem.alu_result;
            if (s == SRC_MEMWB) return mem_wb.mem_to_reg ? mem_wb.mem_data : mem_wb.alu_result;
            return own;
        };
        u64 a = fwd(fa, id_ex.read_data1);
        u64 d2 = fwd(fb, id_ex.read_data2);
        u64 b = id_ex.alu_src ? (u64)id_ex.sign_ext_imm : d2;

        u64 r = 0;
        switch (id_ex.alu_op) {
            case A_ADD:  r = a + b; break;
            case A_SUB:  r = a - b; break;
            case A_AND:  r = a & b; break;
            case A_ORR:  r = a | b; break;
            case A_PASS: r = a; break;
            case A_NONE: break;
        }

        EX_MEM o;
        if (id_ex.branch) {
            Op op = id_ex.instr.op;
            o.branch_target = id_ex.instr.pc + id_ex.sign_ext_imm * 4;
            o.branch_taken = op == B || (op == CBZ && a == 0) || (op == CBNZ && a != 0);
        }
        o.instr = id_ex.instr;
        o.alu_result = r;
        o.read_data2 = d2;
        o.dest_reg = id_ex.mem_read ? id_ex.rt : id_ex.reg_write ? id_ex.rd : 31;
        o.reg_write = id_ex.reg_write; o.mem_read = id_ex.mem_read; o.mem_write = id_ex.mem_write;
        o.mem_to_reg = id_ex.mem_to_reg; o.valid = id_ex.valid;
        return o;
    }

    MEM_WB stage_mem() {
        MEM_WB o;
        u64 addr = ex_mem.alu_result;
        if (ex_mem.mem_read) {
            auto it = dmem.find(addr);
            o.mem_data = it == dmem.end() ? 0 : it->second;
        }
        if (ex_mem.mem_write) {
            dmem[addr] = ex_mem.read_data2;
            stored = true; store_addr = addr; store_val = ex_mem.read_data2;
        }
        o.instr = ex_mem.instr;
        o.alu_result = ex_mem.alu_result;
        o.dest_reg = ex_mem.dest_reg;
        o.reg_write = ex_mem.reg_write; o.mem_to_reg = ex_mem.mem_to_reg; o.valid = ex_mem.valid;
        return o;
    }

    // ── One clock cycle (PipelineSimulator.step) ──
    void step() {
        stored = false;

        // 1. Hazard detection on current pipeline regs
        Src fa, fb;
        forwarding(fa, fb);
        bool stall = fwd_enabled ? (fault != NO_LOAD_USE_STALL && load_use_stall())
                                 : raw_stall_no_forwarding();

        // 2. WB
        if (mem_wb.reg_write && mem_wb.valid)
            reg_write(mem_wb.dest_reg, mem_wb.mem_to_reg ? mem_wb.mem_data : mem_wb.alu_result);

        // 3. MEM, 4. EX
        MEM_WB n_mem_wb = stage_mem();
        EX_MEM n_ex_mem = stage_ex(fa, fb);

        // 5. Branch resolution; flush beats stall
        bool taken = n_ex_mem.branch_taken;
        bool flush = taken && fault != NO_FLUSH;
        if (taken) {
            flushes++;
            pc = n_ex_mem.branch_target;
            stall = false;
        }

        // 6. ID
        ID_EX n_id_ex = (stall || flush) ? ID_EX{} : stage_id();

        // 7. IF
        IF_ID n_if_id;
        if (stall) {
            n_if_id = if_id;
        } else if (flush && fault != SHORT_FLUSH) {
            n_if_id = IF_ID{};
        } else {
            n_if_id.instr = fetch(pc);
            n_if_id.valid = true;
            pc += 4;
        }

        // 8. Retire
        if (mem_wb.valid && mem_wb.instr.op != NOP) {
            if (mem_wb.instr.op == HALT) halted = true;
            else retired++;
        }
        if (stall) stalls++;
        stalled = stall;
        flushed = taken;

        // 9. Advance
        if_id = n_if_id; id_ex = n_id_ex; ex_mem = n_ex_mem; mem_wb = n_mem_wb;
        cycles++;
    }

    void trace() const {
        printf("c=%llu pc=%lld s=%d f=%d", (ull)cycles, (long long)pc, stalled, flushed);
        for (int i = 0; i < 31; i++) printf(" x%d=%llx", i, (ull)regs[i]);
        if (stored) printf(" m=%llx:%llx\n", (ull)store_addr, (ull)store_val);
        else printf(" m=-\n");
    }
};

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <decoded.txt> <fwd 0|1> [fault] [max_cycles] [-q]\n", argv[0]);
        return 2;
    }
    if (argc > 3) {
        int k = 0;
        while (k < NUM_FAULTS && strcmp(argv[3], FAULT_NAMES[k]) != 0) k++;
        if (k == NUM_FAULTS) { fprintf(stderr, "unknown fault: %s\n", argv[3]); return 2; }
        fault = (Fault)k;
    }
    u64 max_cycles = argc > 4 ? strtoull(argv[4], nullptr, 10) : 10000;
    bool quiet = argc > 5 && strcmp(argv[5], "-q") == 0;

    Sim sim;
    sim.fwd_enabled = argv[2][0] == '1';

    std::ifstream f(argv[1]);
    if (!f) { fprintf(stderr, "cannot open %s\n", argv[1]); return 2; }
    std::string name;
    Instr in;
    while (f >> name >> in.rd >> in.rn >> in.rm >> in.rt >> in.imm >> in.offset >> in.pc) {
        int k = 0;
        while (k < NUM_OPS && name != OP_NAMES[k]) k++;
        if (k == NUM_OPS) { fprintf(stderr, "unknown opcode: %s\n", name.c_str()); return 2; }
        in.op = (Op)k;
        sim.imem.push_back(in);
    }

    if (quiet) {  // benchmark: no trace, time the simulation loop only
        auto t0 = std::chrono::steady_clock::now();
        while (!sim.halted && sim.cycles < max_cycles) sim.step();
        double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        printf("END cycles=%llu retired=%llu stalls=%llu flushes=%llu time_s=%.6f\n",
               (ull)sim.cycles, (ull)sim.retired, (ull)sim.stalls, (ull)sim.flushes, secs);
        return 0;
    }
    while (!sim.halted && sim.cycles < max_cycles) {
        sim.step();
        sim.trace();
    }
    printf("END cycles=%llu retired=%llu stalls=%llu flushes=%llu\n", (ull)sim.cycles,
           (ull)sim.retired, (ull)sim.stalls, (ull)sim.flushes);
    return 0;
}
