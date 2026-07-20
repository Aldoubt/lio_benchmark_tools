#!/usr/bin/env python3
"""Classify an algorithm run from exit status, output counts and log evidence."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path

FAILURES=("BUILD_FAILED","DEPENDENCY_MISSING","INPUT_INCOMPATIBLE","INITIALIZATION_FAILED","TIME_SYNC_FAILED","RUNTIME_CRASH","OUT_OF_MEMORY","NO_ODOMETRY","ODOMETRY_INTERRUPTED","INVALID_TRAJECTORY","MAP_EXPORT_FAILED","GROUND_TRUTH_UNAVAILABLE","SUCCESS")
def classify(exit_code:int,odom_count:int,log:str)->str:
 text=log.lower()
 if "out of memory" in text or "bad_alloc" in text:return "OUT_OF_MEMORY"
 if "time sync" in text or "timestamp" in text and "invalid" in text:return "TIME_SYNC_FAILED"
 if exit_code:return "RUNTIME_CRASH"
 if odom_count==0:return "NO_ODOMETRY"
 return "SUCCESS"
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--exit-code',type=int,required=True);p.add_argument('--odometry-count',type=int,required=True);p.add_argument('--log',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args(); status=classify(a.exit_code,a.odometry_count,a.log.read_text(errors='replace') if a.log.exists() else '');a.output.write_text(json.dumps({'status':status,'exit_code':a.exit_code,'odometry_count':a.odometry_count},indent=2)+'\n');return 0 if status=='SUCCESS' else 2
if __name__=='__main__':raise SystemExit(main())
