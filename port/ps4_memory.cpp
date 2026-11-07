// PS4: lazily mapped guest memory and host stacks (ps4_memory.h). From SMW's platform_ps4.cpp "lazy" namespace
// (github.com/iHaiDeeZ/SMW, MIT), for the Wind Waker HD port's single 4 GiB window.
#include "ps4_memory.h"

#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>

#include <atomic>
#include <cstdlib>
#include <mutex>

// libkernel, declared by hand: several OpenOrbis prototypes are wrong or take no parameters.
extern "C" {
int32_t ps4mem_k_reserve(void** addr, size_t len, int32_t flags, size_t align) __asm__("sceKernelReserveVirtualRange");
int32_t ps4mem_k_map_direct(void** addr, size_t len, int32_t prot, int32_t flags, off_t phys, size_t align) __asm__(
    "sceKernelMapDirectMemory");
int32_t ps4mem_k_allocate_direct(off_t start, off_t end, size_t len, size_t align, int32_t type, off_t* phys) __asm__(
    "sceKernelAllocateDirectMemory");
size_t ps4mem_k_direct_size() __asm__("sceKernelGetDirectMemorySize");
int32_t ps4mem_k_munmap(void* addr, size_t len) __asm__("sceKernelMunmap");
void ps4_boot_trace(const char* line);  // port/ps4_crashlog.cpp
}

namespace {

constexpr int32_t kMapFixed = 0x10;  // SCE_KERNEL_MAP_FIXED
constexpr int32_t kProtCpuRw = 0x3;
constexpr int32_t kWbOnion = 0;      // SCE_KERNEL_WB_ONION

// The lazy space: the guest window (ppc.h PPC_MEM_BASE on the PS4, 4 GiB) and the host stacks after it, all below
// 256 GiB (0x40_0000_0000), where RADV's PS4 winsys puts its GPU address windows (port/mesa: PS4_VA_HINT). In 0.1.0
// the guest window sat there, RADV's windows moved up 4 GiB, and the console hung at RADV's first GPU mapping.
constexpr uint64_t kBase = 0x3000000000ull;
constexpr uint64_t kStacks = 0x3400000000ull;
constexpr uint64_t kEnd = 0x3C00000000ull;
constexpr uint64_t kChunk = 0x10000;  // 64 KiB, four PS4 pages
constexpr uint64_t kSlice = 1ull << 30;
constexpr uint64_t kChunksPerSlice = kSlice / kChunk;
constexpr uint64_t kSlices = (kEnd - kBase) / kSlice;
constexpr uint64_t kBlock = 32ull << 20;  // direct memory is allocated in blocks of this, mapped by chunk

enum : uint8_t { kUnused = 0, kCommitted = 1, kMapped = 2 };

struct Slice {
    std::atomic<uint8_t> state[kChunksPerSlice];
};

std::atomic<Slice*> g_slices[kSlices];
std::mutex g_slice_alloc;
std::atomic_flag g_lock = ATOMIC_FLAG_INIT;  // the fault handler takes it: no mutex
uint64_t g_block = 0, g_block_size = 0, g_block_used = 0;
std::atomic<uint64_t> g_mapped{0}, g_failed{0};
std::atomic<uint64_t> g_next_stack{kStacks};

struct Lock {
    Lock() {
        while (g_lock.test_and_set(std::memory_order_acquire)) sched_yield();
    }
    ~Lock() { g_lock.clear(std::memory_order_release); }
};

bool ours(uint64_t a) { return a >= kBase && a < kEnd; }
Slice* slice_of(uint64_t a) { return g_slices[(a - kBase) / kSlice].load(std::memory_order_acquire); }
uint64_t index_of(uint64_t a) { return (a - kBase) % kSlice / kChunk; }

Slice* make_slice(uint64_t a) {
    auto& slot = g_slices[(a - kBase) / kSlice];
    if (Slice* s = slot.load(std::memory_order_acquire)) return s;
    std::lock_guard<std::mutex> lk(g_slice_alloc);
    if (Slice* s = slot.load(std::memory_order_acquire)) return s;
    auto* s = static_cast<Slice*>(std::calloc(1, sizeof(Slice)));
    if (!s) {
        ps4_boot_trace("ps4mem: no host memory for the chunk table");
        std::abort();
    }
    slot.store(s, std::memory_order_release);
    return s;
}

// A free chunk of direct memory (its offset), or UINT64_MAX. With g_lock held.
uint64_t take_phys() {
    if (g_block_used == g_block_size) {
        // 32 MiB at a time; when direct memory is fragmented (the GPU's allocations in between), smaller pieces
        off_t phys = 0;
        uint64_t size = kBlock;
        while (ps4mem_k_allocate_direct(0, off_t(ps4mem_k_direct_size()), size, kChunk, kWbOnion, &phys) != 0)
            if ((size /= 2) < kChunk) return UINT64_MAX;
        g_block = uint64_t(phys);
        g_block_size = size;
        g_block_used = 0;
    }
    uint64_t at = g_block + g_block_used;
    g_block_used += kChunk;
    return at;
}

// Zeroes direct memory chunk `phys` in a window of its own (a temporary address the kernel picks), before it shows at
// its guest address. Cleared in place after mapping, the chunk was already every thread's while the memset ran, and a
// write another thread made there meanwhile was lost: random guest corruption (found by SSBU v00.16; TOTK and BOTW had
// the same code, fixed in TOTK 640b099). False when no window could be mapped (the caller then clears in place).
bool zero_phys(uint64_t phys) {
    void* at = nullptr;
    if (ps4mem_k_map_direct(&at, kChunk, kProtCpuRw, 0, off_t(phys), kChunk) != 0 || !at) return false;
    memset(at, 0, kChunk);  // direct memory comes with whatever was there before
    ps4mem_k_munmap(at, kChunk);
    return true;
}

// Maps the committed chunk at `chunk` with zeroes. With g_lock held.
bool map_chunk(Slice* s, uint64_t chunk) {
    uint64_t phys = take_phys();
    if (phys == UINT64_MAX) return false;
    const bool zeroed = zero_phys(phys);
    void* at = reinterpret_cast<void*>(chunk);
    ps4mem_k_munmap(at, kChunk);  // our reservation there: mapping over it fails
    int32_t r = ps4mem_k_map_direct(&at, kChunk, kProtCpuRw, kMapFixed, off_t(phys), kChunk);
    if (r != 0 || at != reinterpret_cast<void*>(chunk)) {
        void* back = reinterpret_cast<void*>(chunk);
        ps4mem_k_reserve(&back, kChunk, kMapFixed, 0);
        return false;
    }
    if (!zeroed) memset(at, 0, kChunk);  // no window: in place, as before (the race above remains possible)
    s->state[index_of(chunk)].store(kMapped, std::memory_order_release);
    g_mapped.fetch_add(kChunk, std::memory_order_relaxed);
    return true;
}

thread_local uint64_t t_last_fault = 0;
thread_local uint32_t t_repeats = 0;

struct sigaction g_old_segv, g_old_bus;

void chain(int sig, siginfo_t* info, void* uc) {
    struct sigaction& old = sig == SIGBUS ? g_old_bus : g_old_segv;
    if (old.sa_flags & SA_SIGINFO) {
        old.sa_sigaction(sig, info, uc);
        return;
    }
    if (old.sa_handler == SIG_IGN) return;
    if (old.sa_handler != SIG_DFL) {
        old.sa_handler(sig);
        return;
    }
    signal(sig, SIG_DFL);
    raise(sig);
}

void handler(int sig, siginfo_t* info, void* uc) {
    if (ps4mem_fault(uint64_t(uintptr_t(info->si_addr)))) return;  // first touch: retried, now mapped
    chain(sig, info, uc);  // the game's crash handler, then port/ps4_crashlog.cpp
}

}  // namespace

extern "C" {

int ps4mem_reserve(uint64_t base, uint64_t size) {
    void* at = reinterpret_cast<void*>(base);
    const int32_t r = ps4mem_k_reserve(&at, size, kMapFixed, 0);
    char line[160];
    snprintf(line, sizeof line, "ps4mem: reserve %#llx + %#llx: %s (%x, %p)", (unsigned long long)base,
             (unsigned long long)size, r == 0 && at == reinterpret_cast<void*>(base) ? "ok" : "FAILED", unsigned(r), at);
    ps4_boot_trace(line);
    return r == 0 && at == reinterpret_cast<void*>(base);
}

void ps4mem_commit(uint64_t addr, uint64_t size) {
    if (!size) return;
    uint64_t a = addr & ~(kChunk - 1), e = (addr + size + kChunk - 1) & ~(kChunk - 1);
    for (uint64_t c = a; c < e; c += kChunk) {
        if (!ours(c)) continue;
        Slice* s = make_slice(c);
        uint8_t expected = kUnused;
        s->state[index_of(c)].compare_exchange_strong(expected, kCommitted, std::memory_order_acq_rel);
    }
}

int ps4mem_fault(uint64_t addr) {
    if (!ours(addr)) return 0;
    Slice* s = slice_of(addr);
    if (!s) return 0;
    uint64_t chunk = addr & ~(kChunk - 1);
    uint8_t st = s->state[index_of(chunk)].load(std::memory_order_acquire);
    if (st == kMapped) {
        // Another thread mapped it between the access and now: retry. The same address faulting again and again on
        // a mapped chunk is a real protection fault (a write-protected page that isn't the write tracker's).
        t_repeats = t_last_fault == addr ? t_repeats + 1 : 0;
        t_last_fault = addr;
        return t_repeats < 4;
    }
    if (st != kCommitted) return 0;
    Lock lk;
    st = s->state[index_of(chunk)].load(std::memory_order_acquire);
    if (st == kMapped) return 1;
    if (st != kCommitted) return 0;
    if (!map_chunk(s, chunk)) {
        g_failed.fetch_add(1, std::memory_order_relaxed);
        return 0;  // out of direct memory: the crash handler reports it
    }
    return 1;
}

void ps4mem_prefault(const void* p, size_t size) {
    if (!size) return;
    uint64_t a = uint64_t(uintptr_t(p)) & ~(kChunk - 1), e = uint64_t(uintptr_t(p)) + size;
    for (uint64_t c = a; c < e; c += kChunk) {
        if (!ours(c)) continue;
        Slice* s = slice_of(c);
        if (!s || s->state[index_of(c)].load(std::memory_order_acquire) != kCommitted) continue;
        Lock lk;
        if (s->state[index_of(c)].load(std::memory_order_acquire) == kCommitted && !map_chunk(s, c))
            g_failed.fetch_add(1, std::memory_order_relaxed);
    }
}

void ps4mem_install_handler(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = handler;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGSEGV, &sa, &g_old_segv);
    sigaction(SIGBUS, &sa, &g_old_bus);
}

void* ps4mem_stack(size_t size) {
    static std::once_flag reserved;
    static bool ok = false;
    std::call_once(reserved, [] { ok = ps4mem_reserve(kStacks, kEnd - kStacks); });
    if (!ok) return nullptr;
    size = (size + kChunk - 1) & ~(kChunk - 1);
    uint64_t at = g_next_stack.fetch_add(size + kChunk);  // one unmapped chunk between stacks: a guard
    if (at + size > kEnd) return nullptr;
    ps4mem_commit(at, size);
    const uint64_t top = size < (1u << 20) ? size : (1u << 20);
    ps4mem_prefault(reinterpret_cast<void*>(at + size - top), top);  // the first frames need no fault
    return reinterpret_cast<void*>(at);
}

uint64_t ps4mem_mapped_bytes(void) { return g_mapped.load(); }
uint64_t ps4mem_failed(void) { return g_failed.load(); }

}  // extern "C"
