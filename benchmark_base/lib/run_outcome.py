#!/usr/bin/env python3
"""Stable classification of algorithm-runner process outcomes."""
from __future__ import annotations


def classify_runner_status(returncode: int) -> str:
    """Map reserved runner exit codes to benchmark run-status semantics."""
    code = int(returncode)
    if code == 0:
        return "PASS"
    if code == 65:
        return "BLOCKED_ENVIRONMENT"
    return "FAIL_ALGORITHM"
