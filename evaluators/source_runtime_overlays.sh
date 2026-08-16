#!/usr/bin/env bash
# Source the frozen per-algorithm runtime overlays emitted by emit_runtime_env.py.
# This file is intended to be sourced from an estimator runner.

count=${BENCHMARK_RUNTIME_OVERLAY_COUNT:-0}
if [[ ! "$count" =~ ^[0-9]+$ ]]; then
  echo "invalid BENCHMARK_RUNTIME_OVERLAY_COUNT: $count" >&2
  return 65 2>/dev/null || exit 65
fi

for ((i = 0; i < count; i++)); do
  var="BENCHMARK_RUNTIME_OVERLAY_${i}"
  overlay=${!var-}
  if [[ -z "$overlay" || ! -f "$overlay" ]]; then
    echo "runtime overlay is missing or not a regular file: ${overlay:-<unset>}" >&2
    return 65 2>/dev/null || exit 65
  fi
  if ! source "$overlay"; then
    echo "failed to source runtime overlay: $overlay" >&2
    return 65 2>/dev/null || exit 65
  fi
done
