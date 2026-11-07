/* PS4: C library functions the OpenOrbis libc lacks and the port's code (or a library it links) refers to.
   Each fails cleanly (ENOSYS / NULL), as on a system without the feature. */
#include <errno.h>
#include <stddef.h>
#include <time.h>

/* musl's internal name, which the OpenOrbis v0.5.2 libc.a refers to (__randname: mkstemp, tmpfile) without defining
   it: clock_gettime is libkernel's there */
int __clock_gettime(clockid_t id, struct timespec* ts) {
    return clock_gettime(id, ts);
}
