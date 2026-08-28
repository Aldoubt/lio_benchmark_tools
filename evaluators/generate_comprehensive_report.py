#!/usr/bin/env python3
"""Deprecated compatibility entrypoint for comprehensive benchmark reports.

The historical implementation embedded run-specific prose and numeric
constants.  Keep the old filename for callers that still invoke it directly,
but delegate all active behavior to the current-run-only report generator.
"""
from current_run_report import main


if __name__ == "__main__":
    raise SystemExit(main())
