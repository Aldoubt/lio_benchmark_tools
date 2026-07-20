#!/usr/bin/env bash
_lio_sam_deps="${LIO_BENCHMARK_ALGORITHM_WORKSPACE:?runner must set algorithm workspace}/deps/opt/ros/humble"
export CMAKE_PREFIX_PATH="$_lio_sam_deps:${CMAKE_PREFIX_PATH:-}"
export LD_LIBRARY_PATH="$_lio_sam_deps/lib/x86_64-linux-gnu:$_lio_sam_deps/lib:${LD_LIBRARY_PATH:-}"
unset _lio_sam_deps
