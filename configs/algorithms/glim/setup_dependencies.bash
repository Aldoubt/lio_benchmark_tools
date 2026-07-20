#!/usr/bin/env bash
_glim_deps="${LIO_BENCHMARK_ALGORITHM_WORKSPACE:?runner must set algorithm workspace}/deps_install"
_glim_gtsam="${LIO_BENCHMARK_GTSAM_PREFIX:?manifest must set GTSAM dependency prefix}"
export CMAKE_PREFIX_PATH="$_glim_deps:$_glim_gtsam:${CMAKE_PREFIX_PATH:-}"
export LD_LIBRARY_PATH="$_glim_deps/lib:$_glim_gtsam/lib/x86_64-linux-gnu:$_glim_gtsam/lib:${LD_LIBRARY_PATH:-}"
unset _glim_deps _glim_gtsam
