# CMake toolchain for PS4 homebrew (jailbroken console, GoldHEN), self-contained:
#
#   - LLVM 21 (clang, ld.lld, llvm-ar) from llvm.org, on Linux or Windows hosts
#   - the OpenOrbis PS4 toolchain v0.5.2 (headers, system library stubs, crt1.o, link.x, create-fself, PkgTool)
#   - the libc++ 21 sysroot with the libc overlay (FreeBSD values for the musl headers' signals, mmap flags,
#     clocks) and open-source libraries built for the PS4: SMW's sdk-1 (github.com/iHaiDeeZ/SMW, sysroot/)
#
# Same compile and link model as love-ps4 / DolphinPS4 / SMW (PacBrew's ps4.cmake with clang 21 + libc++ 21):
# ld.lld is called directly, there is no compiler driver link step.
#
#   cmake -DCMAKE_TOOLCHAIN_FILE=<this> -DOPENORBIS=<dir> -DPS4_SYSROOT=<dir> -DPS4_LLVM=<dir> ...
# or the environment variables of the same names.

set(CMAKE_SYSTEM_NAME FreeBSD)
set(CMAKE_SYSTEM_VERSION 12)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(PS4 TRUE)
set(ORBIS TRUE)

foreach(_v OPENORBIS PS4_SYSROOT PS4_LLVM)
  if(NOT ${_v} AND DEFINED ENV{${_v}})
    set(${_v} "$ENV{${_v}}")
  endif()
  if(NOT ${_v})
    message(FATAL_ERROR "ps4.cmake: set ${_v} (cmake -D${_v}=... or the environment)")
  endif()
  file(TO_CMAKE_PATH "${${_v}}" ${_v})
  set(${_v} "${${_v}}" CACHE PATH "PS4 toolchain path (ps4.cmake)" FORCE)
endforeach()
set(CMAKE_TRY_COMPILE_PLATFORM_VARIABLES OPENORBIS PS4_SYSROOT PS4_LLVM)

if(CMAKE_HOST_WIN32)
  set(_exe ".exe")
else()
  set(_exe "")
endif()
set(CMAKE_C_COMPILER "${PS4_LLVM}/clang${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_CXX_COMPILER "${PS4_LLVM}/clang++${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_ASM_COMPILER "${PS4_LLVM}/clang${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_LINKER "${PS4_LLVM}/ld.lld${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_AR "${PS4_LLVM}/llvm-ar${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_RANLIB "${PS4_LLVM}/llvm-ranlib${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_NM "${PS4_LLVM}/llvm-nm${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_OBJCOPY "${PS4_LLVM}/llvm-objcopy${_exe}" CACHE FILEPATH "" FORCE)
set(CMAKE_STRIP "" CACHE FILEPATH "" FORCE)
foreach(_lang C CXX ASM)
  set(CMAKE_${_lang}_COMPILER_TARGET x86_64-pc-freebsd12-elf)
endforeach()

# --sysroot (not -isysroot): with -isysroot clang still searches the build machine's /usr/include, and headers the
# PS4 doesn't have (execinfo.h, ...) would silently come from the host.
# The PS4's CPU is an AMD Jaguar (btver2): SSE4.2, AVX, BMI1, F16C, MOVBE, no AVX2 and no FMA.
set(_ps4_c_flags
  "-march=btver2 -D__PS4__ -D__ORBIS__ -D__OPENORBIS__ -DPS4 -D_GNU_SOURCE -D__BSD_VISIBLE -D_BSD_SOURCE \
-fPIC -funwind-tables --sysroot=${OPENORBIS} -isystem ${PS4_SYSROOT}/libc-overlay -isystem ${OPENORBIS}/include \
-I${PS4_SYSROOT}/include")
set(CMAKE_C_FLAGS_INIT "${_ps4_c_flags}")
set(CMAKE_ASM_FLAGS_INIT "${_ps4_c_flags}")
# libc++ 21 (the sysroot's) instead of the OpenOrbis libc++ 12 headers, ahead of the C headers
set(CMAKE_CXX_FLAGS_INIT "-nostdinc++ -isystem ${PS4_SYSROOT}/include/c++/v1 ${_ps4_c_flags}")

# ld.lld directly, as the OpenOrbis samples do. ps4-app.cmake replaces crt1.o and link.x for applications.
set(PS4_CRT1 "${OPENORBIS}/lib/crt1.o")
set(PS4_LINK_SCRIPT "${OPENORBIS}/link.x")
# -z nodynamic-undefined-weak: undefined weak symbols (C++ thread_local init functions, _ZTH*) resolve to 0 in the
# eboot instead of becoming imports, which create-fself refuses ("missing module for symbol")
# --lto-O3: the runtime's ThinLTO bitcode (PS4_LTO, the WWHD CMakeLists) when the build links it itself
set(PS4_LDFLAGS "-m elf_x86_64 -pie --eh-frame-hdr -z nodynamic-undefined-weak --lto-O3 -L${OPENORBIS}/lib -L${PS4_SYSROOT}/lib")
foreach(_lang C CXX)
  set(CMAKE_${_lang}_LINK_EXECUTABLE
      "<CMAKE_LINKER> ${PS4_LDFLAGS} --script <PS4_LINK_SCRIPT> <LINK_FLAGS> <PS4_CRT1> <OBJECTS> -o <TARGET> <LINK_LIBRARIES>")
  string(REPLACE "<PS4_LINK_SCRIPT>" "${PS4_LINK_SCRIPT}" CMAKE_${_lang}_LINK_EXECUTABLE "${CMAKE_${_lang}_LINK_EXECUTABLE}")
  string(REPLACE "<PS4_CRT1>" "${PS4_CRT1}" CMAKE_${_lang}_LINK_EXECUTABLE "${CMAKE_${_lang}_LINK_EXECUTABLE}")
  set(CMAKE_${_lang}_LINK_OPTIONS_PIE "")
  set(CMAKE_${_lang}_COMPILE_OPTIONS_PIE "-fPIC")
  set(CMAKE_${_lang}_LINK_WHAT_YOU_USE_FLAG "")
endforeach()
set(CMAKE_EXE_LINKER_FLAGS_INIT "")
set(CMAKE_C_STANDARD_LIBRARIES "-lc -lkernel ${OPENORBIS}/lib/libclang_rt.builtins-x86_64.a")
set(CMAKE_CXX_STANDARD_LIBRARIES
    "${PS4_SYSROOT}/lib/libc++.a ${PS4_SYSROOT}/lib/libc++abi.a ${OPENORBIS}/lib/libunwind.a ${CMAKE_C_STANDARD_LIBRARIES}")
# ld.lld takes no -l<lib> for "Threads": pthread is in the OpenOrbis libc / libkernel
set(CMAKE_THREAD_LIBS_INIT "")
set(CMAKE_HAVE_THREADS_LIBRARY 1)
set(CMAKE_USE_PTHREADS_INIT 1)
set(THREADS_PREFER_PTHREAD_FLAG OFF)
set(Threads_FOUND TRUE)

# PS4_PREFIX: where this project's own PS4 libraries are installed (SDL3, glslang, LZ4), searched first
if(NOT PS4_PREFIX AND DEFINED ENV{PS4_PREFIX})
  set(PS4_PREFIX "$ENV{PS4_PREFIX}")
endif()
if(PS4_PREFIX)
  file(TO_CMAKE_PATH "${PS4_PREFIX}" PS4_PREFIX)
  set(PS4_PREFIX "${PS4_PREFIX}" CACHE PATH "this project's PS4 libraries" FORCE)
  list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES PS4_PREFIX)
endif()
set(CMAKE_FIND_ROOT_PATH ${PS4_PREFIX} "${PS4_SYSROOT}" "${OPENORBIS}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(CMAKE_EXECUTABLE_SUFFIX ".elf")
set(CMAKE_C_COMPILER_WORKS TRUE)
set(CMAKE_CXX_COMPILER_WORKS TRUE)
