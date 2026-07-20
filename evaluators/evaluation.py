"""Ground-truth and diagnostic trajectory evaluation primitives."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

DIAGNOSTIC_METRICS = {"z_range_m", "z_end_delta_m", "loop_endpoint_delta_m", "estimated_path_length_m", "roll_range_deg", "pitch_range_deg", "map_consistency_proxy"}


def common_time_window(trajectories: dict[str, np.ndarray]) -> tuple[float, float]:
    if not trajectories: raise ValueError("no trajectories")
    start = max(float(values[0]) for values in trajectories.values())
    end = min(float(values[-1]) for values in trajectories.values())
    if end <= start: raise ValueError("trajectories have no common time window")
    return start, end


def crop_common(values: np.ndarray, start: float, end: float) -> tuple[np.ndarray, dict]:
    mask = (values[:, 0] >= start) & (values[:, 0] <= end)
    result = values[mask]
    return result, {"original_samples": len(values), "retained_samples": len(result), "discarded_samples": len(values)-len(result), "retained_ratio": len(result)/len(values) if len(values) else 0.0, "discarded_duration_s": (start-values[0,0]) + (values[-1,0]-end) if len(values) else 0.0}


def align_positions(estimated: np.ndarray, truth: np.ndarray, method: str) -> tuple[np.ndarray, dict]:
    if estimated.shape != truth.shape or estimated.ndim != 2 or estimated.shape[1] != 3: raise ValueError("position arrays must both be N×3")
    if method == "known_transform": return estimated.copy(), {"scale": 1.0, "rotation": np.eye(3).tolist(), "translation": [0,0,0]}
    if method == "translation_only":
        t = truth.mean(axis=0)-estimated.mean(axis=0); return estimated+t, {"scale":1.0,"rotation":np.eye(3).tolist(),"translation":t.tolist()}
    if method == "yaw_translation":
        a, b = estimated[:,:2]-estimated[:,:2].mean(0), truth[:,:2]-truth[:,:2].mean(0)
        h=a.T@b; u,_,vt=np.linalg.svd(h); r2=vt.T@u.T
        if np.linalg.det(r2)<0: vt[-1]*=-1; r2=vt.T@u.T
        r=np.eye(3); r[:2,:2]=r2; t=truth.mean(0)-r@estimated.mean(0); return (r@estimated.T).T+t,{"scale":1.0,"rotation":r.tolist(),"translation":t.tolist()}
    if method not in ("SE3", "Sim3"): raise ValueError(f"unknown alignment method: {method}")
    x, y = estimated-estimated.mean(0), truth-truth.mean(0); u,s,vt=np.linalg.svd(x.T@y); r=vt.T@u.T
    if np.linalg.det(r)<0: vt[-1]*=-1; r=vt.T@u.T
    scale=float(s.sum()/np.square(x).sum()) if method=="Sim3" else 1.0
    t=truth.mean(0)-scale*r@estimated.mean(0); return scale*(r@estimated.T).T+t,{"scale":scale,"rotation":r.tolist(),"translation":t.tolist()}


def ate_metrics(aligned: np.ndarray, truth: np.ndarray) -> dict:
    errors=np.linalg.norm(aligned-truth,axis=1)
    return {"ate_rmse_m":float(np.sqrt(np.mean(errors**2))),"ate_mean_m":float(np.mean(errors)),"ate_median_m":float(np.median(errors)),"ate_max_m":float(np.max(errors)),"ate_p95_m":float(np.percentile(errors,95))}


def diagnostic_metrics(positions: np.ndarray, roll: np.ndarray, pitch: np.ndarray) -> dict:
    if len(positions)<2: raise ValueError("at least two positions required")
    lengths=np.linalg.norm(np.diff(positions,axis=0),axis=1)
    return {"metric_class":"diagnostic/conditional/non-ground-truth","z_range_m":float(np.ptp(positions[:,2])),"z_end_delta_m":float(positions[-1,2]-positions[0,2]),"loop_endpoint_delta_m":float(np.linalg.norm(positions[-1]-positions[0])),"estimated_path_length_m":float(lengths.sum()),"roll_range_deg":float(np.degrees(np.ptp(roll))),"pitch_range_deg":float(np.degrees(np.ptp(pitch)))}


def validate_metric_names(metrics: dict, ground_truth_available: bool) -> None:
    forbidden = ("ate", "rpe", "rmse", "absolute_error", "accuracy")
    if not ground_truth_available:
        bad=[key for key in metrics if any(token in key.lower() for token in forbidden)]
        if bad: raise ValueError(f"ground-truth metrics forbidden without ground truth: {bad}")
