cmake_minimum_required(VERSION 3.18)
project(wfs-catalog LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/../cmake")
find_package(cryptopp REQUIRED)

set(wfslib_source "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/wfs-tools/wfslib")
if(NOT EXISTS "${wfslib_source}/CMakeLists.txt")
    message(FATAL_ERROR "wfslib is not checked out. Run scripts/build-catalog.sh")
endif()

set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
# GCC 16 does not include cstdint before wfslib uses uint32_t.
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -include cstdint")
add_subdirectory(
    "${wfslib_source}"
    "${CMAKE_CURRENT_BINARY_DIR}/wfslib"
    EXCLUDE_FROM_ALL
)

add_executable(wfs-catalog main.cpp)
target_compile_features(wfs-catalog PRIVATE cxx_std_23)
target_compile_options(wfs-catalog PRIVATE -Wall -Wextra -Wpedantic -Werror)
# Public headers include private ones by quoted name. Match wfs-extract.
target_include_directories(wfs-catalog PRIVATE
    "${wfslib_source}/src"
    "${wfslib_source}/include/wfslib"
)
target_link_libraries(wfs-catalog PRIVATE wfslib cryptopp::cryptopp)
