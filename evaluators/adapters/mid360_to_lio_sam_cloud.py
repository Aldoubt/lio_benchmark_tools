#!/usr/bin/env python3
"""LIO-SAM-specific entry point for the validated MID360 cloud contract.

The implementation reuses the common converter. `ring` is the recorded Livox
line ID, not an inferred spinning-LiDAR ring. Points are sorted by their actual
offset time so LIO-SAM's `points.back().time` scan-end assumption is valid.
"""
from custommsg_to_pointcloud2 import main


if __name__ == "__main__":
    main()
