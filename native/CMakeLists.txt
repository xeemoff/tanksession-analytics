cmake_minimum_required(VERSION 3.24)
project(TankSessionNative LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
foreach(config Debug Release RelWithDebInfo MinSizeRel)
  string(TOUPPER "${config}" config_upper)
  set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_${config_upper} "${CMAKE_BINARY_DIR}/bin")
endforeach()
# The Windows companion is a standalone executable, without a VC runtime install.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

option(TSA_ENABLE_SANITIZERS "Enable address/undefined-behaviour checks on GCC/Clang" OFF)
option(TSA_BUILD_BENCHMARK "Build the deterministic core benchmark" ON)

add_library(ts_native_core STATIC src/analytics.cpp src/protocol.cpp)
target_include_directories(ts_native_core PUBLIC include)
target_compile_features(ts_native_core PUBLIC cxx_std_23)
if(MSVC)
  target_compile_options(ts_native_core PRIVATE /W4 /permissive- /fp:precise)
else()
  target_compile_options(ts_native_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion)
endif()
if(TSA_ENABLE_SANITIZERS)
  if(MSVC)
    message(FATAL_ERROR "This sanitizer configuration requires GCC or Clang")
  endif()
  target_compile_options(ts_native_core PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(ts_native_core PUBLIC -fsanitize=address,undefined)
endif()

add_executable(tanksession-native src/main.cpp)
target_link_libraries(tanksession-native PRIVATE ts_native_core)
install(TARGETS tanksession-native RUNTIME DESTINATION bin)

if(TSA_BUILD_BENCHMARK)
  add_executable(ts_native_benchmark benchmarks/benchmark.cpp)
  target_link_libraries(ts_native_benchmark PRIVATE ts_native_core)
endif()

include(CTest)
if(BUILD_TESTING)
  include(FetchContent)
  # GoogleTest 1.17.0, pinned to an immutable upstream commit. Build-time only.
  FetchContent_Declare(googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG 52eb8108c5bdec04579160ae17225d66034bd723
    GIT_PROGRESS FALSE)
  set(gtest_force_shared_crt OFF CACHE BOOL "" FORCE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
  add_executable(ts_native_tests tests/analytics_test.cpp tests/protocol_test.cpp)
  target_link_libraries(ts_native_tests PRIVATE ts_native_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(ts_native_tests DISCOVERY_TIMEOUT 30)
endif()
