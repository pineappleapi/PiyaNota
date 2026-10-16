# Builds LAME 3.100 as libmp3lame.so plus the JNI bridge (PIYA-211).
#
# LAME is vendored, unmodified, from the official 3.100 release tarball
# (lame-3.100.tar.gz on SourceForge) into ./lame/. Only libmp3lame/ and
# include/ are compiled; the frontend, mpglib decoder and SIMD vector/
# code are not needed for encoding and are left out.
cmake_minimum_required(VERSION 3.22.1)
project(piyanota_lame C)

set(LAME_DIR ${CMAKE_CURRENT_SOURCE_DIR}/lame)

if(NOT EXISTS ${LAME_DIR}/libmp3lame/lame.c)
    message(FATAL_ERROR
        "LAME 3.100 sources missing: unpack lame-3.100.tar.gz into ${LAME_DIR}")
endif()

# Top level of libmp3lame/ only: vector/ (SSE) and i386/ (nasm) are
# x86-only optional paths.
file(GLOB LAME_SOURCES ${LAME_DIR}/libmp3lame/*.c)

add_library(mp3lame SHARED ${LAME_SOURCES})
target_include_directories(mp3lame PRIVATE
    ${LAME_DIR}/include
    ${LAME_DIR}/libmp3lame
    ${LAME_DIR})
# No ./configure on Android, so give LAME the facts config.h would hold.
target_compile_definitions(mp3lame PRIVATE
    STDC_HEADERS=1
    HAVE_STDINT_H=1
    HAVE_INTTYPES_H=1
    HAVE_LIMITS_H=1
    HAVE_ERRNO_H=1
    HAVE_FCNTL_H=1
    HAVE_STRCHR=1
    HAVE_MEMCPY=1
    TAKEHIRO_IEEE754_HACK=1
    USE_FAST_LOG=1
    NDEBUG)
target_compile_options(mp3lame PRIVATE -O2 -w)
target_link_libraries(mp3lame m)

add_library(piyanota_lame SHARED lame_jni.c)
target_include_directories(piyanota_lame PRIVATE ${LAME_DIR}/include)
target_link_libraries(piyanota_lame mp3lame)
