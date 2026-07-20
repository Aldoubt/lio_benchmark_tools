#!/usr/bin/env bash
# User-local extraction of the official ROS 2 Humble MOLA Debian packages.
_mola_root="${LIO_BENCHMARK_ALGORITHM_WORKSPACE:?runner must set algorithm workspace}/apt_root"
_mola_prefix="$_mola_root/opt/ros/humble"
export AMENT_PREFIX_PATH="$_mola_prefix:${AMENT_PREFIX_PATH:-}"
export CMAKE_PREFIX_PATH="$_mola_prefix:${CMAKE_PREFIX_PATH:-}"
export PATH="$_mola_prefix/bin:$PATH"
export LD_LIBRARY_PATH="$_mola_prefix/lib/x86_64-linux-gnu:$_mola_prefix/lib:$_mola_root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$_mola_prefix/local/lib/python3.10/dist-packages:$_mola_prefix/lib/python3.10/site-packages:${PYTHONPATH:-}"
unset _mola_root _mola_prefix
