# Application setup for PS4 homebrew, included by the project after toolchain/ps4.cmake (from love-ps4 / DolphinPS4 /
# SMW's ps4-love-style.cmake, github.com/iHaiDeeZ/SMW, MIT, which run on retail consoles):
#
#   PS4_PORT_SOURCES        the PS4 runtime in port/ (heap, crash log, thread fixes, lazy memory, VideoOut WSI, ...)
#   ps4_link_mesa(<target>) Mesa's RADV Vulkan driver for the PS4 GPU (SMW's sdk-1), linked whole
#   ps4_add_eboot(<target>) <target>.elf -> <binary dir>/<target>_eboot/eboot.bin (fake SELF), checked
#
# and the link changes every PS4 application needs: a crt1.o whose malloc-replacement table sends every malloc of the
# process (system modules included) to our heap, a link script that keeps prioritized constructors and per-symbol
# data sections, and the linker --wraps of port/ps4_runtime.cpp.

get_filename_component(PS4_PORT_DIR "${CMAKE_CURRENT_LIST_DIR}/../port" ABSOLUTE)
set(PS4_PORT_SOURCES
    ${PS4_PORT_DIR}/ps4_runtime.cpp
    ${PS4_PORT_DIR}/ps4_dlmalloc.c
    ${PS4_PORT_DIR}/ps4_crashlog.cpp
    ${PS4_PORT_DIR}/ps4_sampler.cpp
    ${PS4_PORT_DIR}/ps4_string.c
    ${PS4_PORT_DIR}/ps4_random.c
    ${PS4_PORT_DIR}/ps4_memory.cpp
    ${PS4_PORT_DIR}/ps4_vk_wsi.cpp
    ${PS4_PORT_DIR}/ps4_platform.cpp
    ${PS4_PORT_DIR}/ps4_https.cpp
    ${PS4_PORT_DIR}/ps4_libc_extras.c
    ${PS4_PORT_DIR}/ps4_ktrace.cpp)

# crt1.o with the malloc-replacement table (port/ps4_crt1.S): the libc heap can't initialize on retail consoles
set(PS4_CRT1 ${CMAKE_BINARY_DIR}/ps4-crt1-malloc-replace.o)
execute_process(
  COMMAND ${CMAKE_C_COMPILER} -target x86_64-pc-freebsd12-elf -c ${PS4_PORT_DIR}/ps4_crt1.S -o ${PS4_CRT1}
  RESULT_VARIABLE _ps4_crt1_result)
if(NOT _ps4_crt1_result EQUAL 0)
  message(FATAL_ERROR "assembling port/ps4_crt1.S failed: ${_ps4_crt1_result}")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${PS4_PORT_DIR}/ps4_crt1.S)

# The OpenOrbis link script only collects plain .init_array, so prioritized constructors (.init_array.NNN: libc++'s
# iostreams, port/ps4_crashlog.cpp) end up in an orphan section the loader never runs; and plain .data/.tdata/.tbss,
# so per-symbol sections (C++ template statics, inline variables, all of Mesa) became orphans past the end of the data
# segment's file image (zeros on the console).
set(PS4_LINK_SCRIPT ${CMAKE_BINARY_DIR}/ps4-link.x)
file(READ ${OPENORBIS}/link.x _ps4_ld)
string(FIND "${_ps4_ld}" "*(.init_array);" _ps4_pos)
if(_ps4_pos EQUAL -1)
  message(FATAL_ERROR "Unexpected ${OPENORBIS}/link.x: no '*(.init_array);' rule to patch")
endif()
string(REPLACE "*(.init_array);" "KEEP(*(SORT_BY_INIT_PRIORITY(.init_array.*))); KEEP(*(.init_array));"
       _ps4_ld "${_ps4_ld}")
foreach(rule ".data" ".tdata" ".tbss")
  string(FIND "${_ps4_ld}" "*(${rule})" _ps4_pos)
  if(_ps4_pos EQUAL -1)
    message(FATAL_ERROR "Unexpected ${OPENORBIS}/link.x: no '*(${rule})' rule to patch")
  endif()
  string(REPLACE "*(${rule})" "*(${rule} ${rule}.*)" _ps4_ld "${_ps4_ld}")
endforeach()
file(WRITE ${PS4_LINK_SCRIPT} "${_ps4_ld}")

foreach(_lang C CXX)
  set(CMAKE_${_lang}_LINK_EXECUTABLE
      "<CMAKE_LINKER> ${PS4_LDFLAGS} --script ${PS4_LINK_SCRIPT} <LINK_FLAGS> ${PS4_CRT1} <OBJECTS> -o <TARGET> <LINK_LIBRARIES>")
endforeach()

# port/ps4_runtime.cpp: the malloc family on our heap, the kernel's pthread_once that writes 16 bytes into a 4-byte
# pthread_once_t, large anonymous mmaps from the system flexible pool, CLOCK_MONOTONIC from the TSC, new threads on
# all of the app's cores with a signal stack each
set(PS4_WRAPS)
foreach(fn malloc free calloc realloc memalign __memalign pthread_once mmap clock_gettime pthread_create
           sceKernelMapDirectMemory sceKernelAllocateDirectMemory sceKernelReleaseDirectMemory sceKernelVirtualQuery
           sceKernelReserveVirtualRange sceKernelMunmap sceKernelDlsym)
  list(APPEND PS4_WRAPS --wrap=${fn})
endforeach()

# Program authority ID and auth info of the eboot: RetroArch for PS4's, as love-ps4, DolphinPS4 and SMW use
set(PS4_PAID "0x3100000000000002" CACHE STRING "Program authority ID of eboot.bin")
set(PS4_AUTH_INFO "000000000000000000000000001C004000FF000000000080000000000000000000000000000000000000008000400040000000000000008000000000000000080040FFFF000000F000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    CACHE STRING "Auth info of eboot.bin")

# Mesa's RADV for the PS4 GPU (Crema's GNM winsys), as SMW's sdk-1 ships it: whole archives, as Mesa's own shared
# library link does (the dispatch tables refer to entry points through weak symbols, which pull no archive members)
set(PS4_MESA_BUILD "" CACHE PATH "RADV for the PS4: the build/mesa folder of SMW's sdk-1")
set(PS4_MESA_LIBS
    src/amd/vulkan/libvulkan_radeon.a src/amd/common/libamd_common.a src/amd/compiler/libaco.a
    src/amd/addrlib/libaddrlib.a src/vulkan/util/libvulkan_util.a src/compiler/spirv/libvtn.a
    src/compiler/nir/libnir.a src/compiler/libcompiler.a src/util/libxmlconfig.a src/util/libmesa_util.a
    src/util/libmesa_util_simd.a src/util/libmesa_util_clflush.a src/util/libmesa_util_clflushopt.a
    src/util/libparson.a src/util/blake3/libblake3.a src/c11/impl/libmesa_util_c11.a)
function(ps4_link_mesa target)
  if(NOT PS4_MESA_BUILD)
    message(FATAL_ERROR "set PS4_MESA_BUILD to the build/mesa folder of SMW's sdk-1")
  endif()
  set(libs ${PS4_MESA_LIBS})
  list(TRANSFORM libs PREPEND "${PS4_MESA_BUILD}/")
  target_link_libraries(${target} PRIVATE --whole-archive ${libs} --no-whole-archive)
endfunction()

function(ps4_add_eboot target)
  target_link_options(${target} PRIVATE ${PS4_WRAPS})
  set(out_dir ${CMAKE_CURRENT_BINARY_DIR}/${target}_eboot)
  if(CMAKE_HOST_WIN32)
    set(_fself "${OPENORBIS}/bin/windows/create-fself.exe")
  else()
    set(_fself "${OPENORBIS}/bin/linux/create-fself")
  endif()
  add_custom_command(
    OUTPUT ${out_dir}/eboot.bin
    COMMAND ${CMAKE_COMMAND} -E make_directory ${out_dir}
    COMMAND ${CMAKE_COMMAND} -E env OO_PS4_TOOLCHAIN=${OPENORBIS}
        ${_fself} -in=$<TARGET_FILE:${target}> -out=${out_dir}/${target}.oelf --eboot ${out_dir}/eboot.bin
        --paid ${PS4_PAID} --authinfo ${PS4_AUTH_INFO}
    COMMAND ${CMAKE_COMMAND} -DOELF=${out_dir}/${target}.oelf -DREADELF=${PS4_LLVM}/llvm-readelf${CMAKE_HOST_EXECUTABLE_SUFFIX}
        -P ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/check-oelf.cmake
    DEPENDS ${target}
    VERBATIM)
  add_custom_target(${target}_eboot ALL DEPENDS ${out_dir}/eboot.bin)
endfunction()
