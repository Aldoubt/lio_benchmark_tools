# README demo assets

The public README demo is generated from a real standardized benchmark run; it is not hand-edited or recorded from different camera angles.

Target tracked artifact:

```text
assets/demo/same_bag_map_comparison.gif
```

Generate it with the V2 demo command after the CLI integration is installed, or directly with:

```bash
python3 reporting/generate_demo.py \
  --run /path/to/frozen/run \
  --output assets/demo/same_bag_map_comparison.gif
```

The generator enforces the same run/bag, common ROI, common map reconstruction contract, common bounds, and identical camera motion for every selected algorithm. Intermediate PNG frames remain run artifacts and should not be committed.

Do not add a placeholder GIF that pretends to be a benchmark result. Until a curated real run has been generated locally, the repository homepage should describe the demo command without embedding a nonexistent file.
