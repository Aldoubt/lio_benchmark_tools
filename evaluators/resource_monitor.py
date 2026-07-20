#!/usr/bin/env python3
"""Sample CPU, RSS, thread and IO counters for a process tree."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
import psutil

def main()->int:
 p=argparse.ArgumentParser(); p.add_argument("pid",type=int); p.add_argument("--output",type=Path,required=True); p.add_argument("--interval",type=float,default=0.5); a=p.parse_args()
 root=psutil.Process(a.pid); samples=[]; started=time.monotonic()
 while root.is_running():
  try:
   procs=[root,*root.children(recursive=True)]; rss=sum(x.memory_info().rss for x in procs); cpu=sum(x.cpu_percent(None) for x in procs); threads=sum(x.num_threads() for x in procs); io=sum(getattr(x.io_counters(),'write_bytes',0) for x in procs)
   samples.append({"elapsed_s":time.monotonic()-started,"cpu_percent":cpu,"rss_bytes":rss,"threads":threads,"write_bytes":io})
  except (psutil.NoSuchProcess,psutil.AccessDenied): break
  time.sleep(a.interval)
 result={"wall_time_s":time.monotonic()-started,"samples":len(samples),"mean_cpu_percent":sum(x['cpu_percent'] for x in samples)/len(samples) if samples else None,"peak_cpu_percent":max((x['cpu_percent'] for x in samples),default=None),"mean_rss_bytes":sum(x['rss_bytes'] for x in samples)/len(samples) if samples else None,"peak_rss_bytes":max((x['rss_bytes'] for x in samples),default=None),"peak_threads":max((x['threads'] for x in samples),default=None),"disk_write_bytes":max((x['write_bytes'] for x in samples),default=None)}
 a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,indent=2)+'\n'); return 0
if __name__=='__main__': raise SystemExit(main())
