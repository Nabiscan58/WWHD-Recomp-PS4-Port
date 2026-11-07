// PS4: lazily mapped memory for the guest's 4 GiB window and the guest threads' host stacks.
//
// The PS4 has no demand-zero memory to speak of: flexible memory is small and committed when mapped, direct memory is
// physical. The Wii U game's address space is 4 GiB, of which it uses a fraction, so the window is an address space
// reservation and 64 KiB chunks of direct memory are mapped where it is first touched (zeroed), by a SIGSEGV/SIGBUS
// handler (the approach of SMW's platform_ps4.cpp, github.com/iHaiDeeZ/SMW, MIT).
#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Reserves [base, base + size) (fixed address, nothing mapped). False when the range is not free.
int ps4mem_reserve(uint64_t base, uint64_t size);
// Marks a reserved range usable: its chunks are mapped on first access. A range never committed stays a fault
// (the guest's null page).
void ps4mem_commit(uint64_t addr, uint64_t size);
// Maps every committed chunk of the range now: before a kernel call writes there (read(), which cannot fault on our
// behalf: it fails with EFAULT) and before pages are write-protected.
void ps4mem_prefault(const void* p, size_t size);
// The fault handler's part (async-signal-safe): true when addr was committed and is mapped now.
int ps4mem_fault(uint64_t addr);
// Installs the SIGSEGV/SIGBUS handler that maps chunks, chaining to the handlers installed before it.
void ps4mem_install_handler(void);
// A host stack of `size` bytes for a guest thread from the lazy stack range, its top 1 MiB mapped. 0: none left.
void* ps4mem_stack(size_t size);
// Direct memory mapped for the lazy ranges so far, and the chunk maps that failed (out of direct memory).
uint64_t ps4mem_mapped_bytes(void);
uint64_t ps4mem_failed(void);
// The PS4's page size (musl's sysconf answers 4 KiB).
#define PS4MEM_PAGE 0x4000u

#ifdef __cplusplus
}
#endif
