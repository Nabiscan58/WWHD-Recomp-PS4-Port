// PS4: a trace of the kernel calls the Vulkan driver makes while the device is created (--wrap of the calls below,
// toolchain/ps4-app.cmake), into boot-trace.log.
//
// 0.1.0 to 0.1.2 stopped inside vkCreateDevice: RADV's log ends at its first buffer ("bo 1"), and the watchdog of
// 0.1.2 found the game's main thread not answering signals (stuck inside a system call) while the rest ran. Each call
// below is logged before and after ("..." then "= result"), so the call that never returns is the last line. RADV
// also reaches the GPU driver (libSceGnmDriver) through sceKernelDlsym: those functions are handed out through
// trampolines that log their calls the same way.
//
// With WWHD_KTRACE=1 in env.txt: on from port/ps4_vk_wsi.cpp's CreateDevice (ps4_ktrace_on) for the first kMaxLines
// lines.
//
// These wrappers also run in the very first moments of the process: the heap (port/ps4_runtime.cpp) reserves its
// range through sceKernelReserveVirtualRange when the C library's own start-up first calls malloc. Until
// ps4_ktrace_on is set they only pass the call on: 0.1.3's first build read the environment (getenv) there, inside
// the C library's start-up, and the app froze before writing anything.
#include <array>
#include <atomic>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

#include <utility>

extern "C" void ps4_boot_trace(const char* line);  // port/ps4_crashlog.cpp

extern "C" {
volatile int ps4_ktrace_on = 0;
int ps4_ktrace_wanted(void);
}

namespace {

constexpr int kMaxLines = 1500;
std::atomic<int> g_lines{0};

bool wanted() {  // only once the app runs (RADV's start, port/ps4_vk_wsi.cpp): never from the C library's start-up
    const char* e = getenv("WWHD_KTRACE");  // off since 0.1.6 (the game starts): WWHD_KTRACE=1 in env.txt
    return e && !strcmp(e, "1");
}

bool tracing() {
    if (!ps4_ktrace_on) return false;  // a plain load: safe at any time
    return g_lines.fetch_add(2, std::memory_order_relaxed) < kMaxLines;  // the call and its result
}

__attribute__((format(printf, 1, 2))) void line(const char* fmt, ...) {
    char b[320];
    va_list a;
    va_start(a, fmt);
    vsnprintf(b, sizeof b, fmt, a);
    va_end(a);
    ps4_boot_trace(b);
}

}  // namespace

extern "C" int ps4_ktrace_wanted(void) { return wanted(); }

extern "C" {

// ---- kernel memory calls -----------------------------------------------------------------------------------------

int32_t __real_sceKernelMapDirectMemory(void** addr, size_t len, int prot, int flags, off_t phys, size_t align);
int32_t __wrap_sceKernelMapDirectMemory(void** addr, size_t len, int prot, int flags, off_t phys, size_t align) {
    const bool t = tracing();
    if (t)
        line("k: MapDirectMemory(%p, %#zx, prot %#x, flags %#x, phys %#llx, align %#zx)...", addr ? *addr : nullptr,
             len, prot, flags, (long long)phys, align);
    const int32_t r = __real_sceKernelMapDirectMemory(addr, len, prot, flags, phys, align);
    if (t) line("k: MapDirectMemory = %#x at %p", unsigned(r), addr ? *addr : nullptr);
    return r;
}

int32_t __real_sceKernelAllocateDirectMemory(off_t start, off_t end, size_t len, size_t align, int type, off_t* out);
int32_t __wrap_sceKernelAllocateDirectMemory(off_t start, off_t end, size_t len, size_t align, int type, off_t* out) {
    const bool t = tracing();
    if (t)
        line("k: AllocateDirectMemory([%#llx, %#llx), %#zx, align %#zx, type %d)...", (long long)start, (long long)end,
             len, align, type);
    const int32_t r = __real_sceKernelAllocateDirectMemory(start, end, len, align, type, out);
    if (t) line("k: AllocateDirectMemory = %#x, phys %#llx", unsigned(r), out ? (long long)*out : -1ll);
    return r;
}

int32_t __real_sceKernelReleaseDirectMemory(off_t start, size_t len);
int32_t __wrap_sceKernelReleaseDirectMemory(off_t start, size_t len) {
    const bool t = tracing();
    if (t) line("k: ReleaseDirectMemory(%#llx, %#zx)...", (long long)start, len);
    const int32_t r = __real_sceKernelReleaseDirectMemory(start, len);
    if (t) line("k: ReleaseDirectMemory = %#x", unsigned(r));
    return r;
}

int32_t __real_sceKernelVirtualQuery(const void* addr, int flags, void* info, size_t size);
int32_t __wrap_sceKernelVirtualQuery(const void* addr, int flags, void* info, size_t size) {
    const bool t = tracing();
    if (t) line("k: VirtualQuery(%p, %d)...", addr, flags);
    const int32_t r = __real_sceKernelVirtualQuery(addr, flags, info, size);
    if (t) line("k: VirtualQuery = %#x", unsigned(r));
    return r;
}

int32_t __real_sceKernelReserveVirtualRange(void** addr, size_t len, int flags, size_t align);
int32_t __wrap_sceKernelReserveVirtualRange(void** addr, size_t len, int flags, size_t align) {
    const bool t = tracing();
    if (t) line("k: ReserveVirtualRange(%p, %#zx, flags %#x, align %#zx)...", addr ? *addr : nullptr, len, flags, align);
    const int32_t r = __real_sceKernelReserveVirtualRange(addr, len, flags, align);
    if (t) line("k: ReserveVirtualRange = %#x at %p", unsigned(r), addr ? *addr : nullptr);
    return r;
}

int32_t __real_sceKernelMunmap(void* addr, size_t len);
int32_t __wrap_sceKernelMunmap(void* addr, size_t len) {
    const bool t = tracing();
    if (t) line("k: Munmap(%p, %#zx)...", addr, len);
    const int32_t r = __real_sceKernelMunmap(addr, len);
    if (t) line("k: Munmap = %#x", unsigned(r));
    return r;
}

}  // extern "C"

// ---- the GPU driver's functions (libSceGnmDriver, found by RADV with sceKernelDlsym) --------------------------------
// Integer and pointer arguments only (the GNM API has no floating-point parameters): ten are passed on, the six in
// registers and four from the stack, which covers every GNM function RADV uses.

namespace {

using Fn = uint64_t (*)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t,
                        uint64_t);
constexpr int kSlots = 96;
struct Slot {
    Fn real;
    char name[64];
};
Slot g_slots[kSlots];
std::atomic<int> g_used{0};

template <int N>
uint64_t trampoline(uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f, uint64_t g, uint64_t h,
                    uint64_t i, uint64_t j) {
    Slot& s = g_slots[N];
    const bool t = tracing();
    if (t) line("gnm: %s(%#llx, %#llx, %#llx, %#llx, %#llx, %#llx)...", s.name, (unsigned long long)a,
                (unsigned long long)b, (unsigned long long)c, (unsigned long long)d, (unsigned long long)e,
                (unsigned long long)f);
    const uint64_t r = s.real(a, b, c, d, e, f, g, h, i, j);
    if (t) line("gnm: %s = %#llx", s.name, (unsigned long long)r);
    return r;
}

template <int... N>
constexpr auto table(std::integer_sequence<int, N...>) {
    return std::array<Fn, sizeof...(N)>{&trampoline<N>...};
}
const auto g_trampolines = table(std::make_integer_sequence<int, kSlots>{});

}  // namespace

extern "C" {

int32_t __real_sceKernelDlsym(int32_t handle, const char* name, void** addr);
int32_t __wrap_sceKernelDlsym(int32_t handle, const char* name, void** addr) {
    const int32_t r = __real_sceKernelDlsym(handle, name, addr);
    if (r != 0 || !addr || !*addr || !name || strncmp(name, "sceGnm", 6) != 0 || !wanted()) return r;
    const int k = g_used.fetch_add(1);
    if (k >= kSlots) return r;
    g_slots[k].real = reinterpret_cast<Fn>(*addr);
    snprintf(g_slots[k].name, sizeof g_slots[k].name, "%s", name);
    *addr = reinterpret_cast<void*>(g_trampolines[k]);
    return r;
}

}  // extern "C"
