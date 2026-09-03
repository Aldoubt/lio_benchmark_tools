from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from freeze_experiment import register_generated_artifact


LABELS = {
    "zh-CN": {
        "title": "LIO 冻结实验报告",
        "overview": "实验概览",
        "algorithms": "算法对比",
        "evidence": "静态证据",
        "anomalies": "代表异常案例",
        "repro": "可复现性检查",
        "limitations": "限制与解释边界",
        "run": "Run",
        "state": "源 Run 状态",
        "baseline": "Baseline",
        "created": "冻结时间",
        "commit": "Benchmark commit",
        "duration": "数据时长 (s)",
        "playback": "回放倍率",
        "algorithm": "Algorithm",
        "status": "Status",
        "health": "Traj health",
        "eligible": "Eligible",
        "path": "Path (m)",
        "zrange": "Z range (m)",
        "cpu": "Mean CPU (%)",
        "rss": "Peak RSS (MiB)",
        "rmse": "Rel. RMSE (m)",
        "p95": "Rel. P95 (m)",
        "jumps": "Pos/Yaw jumps",
        "yes": "yes",
        "no": "no",
        "none": "N/A",
        "scope": "结论作用域",
        "healthy": "健康候选",
        "excluded": "本轮不推荐",
        "pointcloud": "点云案例证据",
    },
    "en": {
        "title": "Frozen LIO Experiment Report",
        "overview": "Experiment Overview",
        "algorithms": "Algorithm Comparison",
        "evidence": "Static Evidence",
        "anomalies": "Representative Anomaly Cases",
        "repro": "Reproducibility Checklist",
        "limitations": "Limitations and Interpretation Boundary",
        "run": "Run",
        "state": "Source run state",
        "baseline": "Baseline",
        "created": "Freeze time",
        "commit": "Benchmark commit",
        "duration": "Dataset duration (s)",
        "playback": "Playback rate",
        "algorithm": "Algorithm",
        "status": "Status",
        "health": "Traj health",
        "eligible": "Eligible",
        "path": "Path (m)",
        "zrange": "Z range (m)",
        "cpu": "Mean CPU (%)",
        "rss": "Peak RSS (MiB)",
        "rmse": "Rel. RMSE (m)",
        "p95": "Rel. P95 (m)",
        "jumps": "Pos/Yaw jumps",
        "yes": "yes",
        "no": "no",
        "none": "N/A",
        "scope": "Conclusion scope",
        "healthy": "Health-valid candidates",
        "excluded": "Not recommended this run",
        "pointcloud": "Point-cloud case evidence",
    },
}


_TEMPLATE = r"""<!doctype html>
<html lang="{{ lang }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ tr.title }} · {{ experiment.run_id }}</title>
<style>
:root{font-family:Inter,"Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;color:#1f2937;background:#f7f8fa;line-height:1.5}
body{margin:0}.wrap{max-width:1180px;margin:0 auto;padding:32px 22px 64px}.hero{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:24px 26px;margin-bottom:18px}.hero h1{margin:0 0 8px;font-size:28px}.muted{color:#667085}.notice{border-left:4px solid #6b7280;background:#f3f4f6;padding:12px 14px;margin:18px 0;border-radius:6px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px}.card b{display:block;font-size:12px;color:#667085;margin-bottom:5px}.section{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:22px 24px;margin-top:18px}.section h2{margin-top:0}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px 8px;border-bottom:1px solid #eaecf0;text-align:left;white-space:nowrap}th{background:#f9fafb}.ok{font-weight:600}.bad{font-weight:600}.figure-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}.figure{border:1px solid #e5e7eb;border-radius:10px;padding:10px;margin:0}.figure img{width:100%;height:auto;display:block}.figure figcaption{font-size:12px;color:#667085;margin-top:6px;word-break:break-all}.case{padding:12px 0;border-bottom:1px solid #eaecf0}.case:last-child{border-bottom:0}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}.check{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px}.check div{padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px}ul{padding-left:22px}
</style>
</head>
<body><main class="wrap">
<section class="hero">
<h1>{{ tr.title }}</h1>
<div class="muted">{{ experiment.run_id }} · {{ metric_class }}</div>
<div class="notice">{{ ground_truth_disclaimer }}</div>
<div class="grid">
<div class="card"><b>{{ tr.run }}</b>{{ experiment.run_id }}</div>
<div class="card"><b>{{ tr.state }}</b>{{ experiment.source_run_state or tr.none }}</div>
<div class="card"><b>{{ tr.baseline }}</b>{{ experiment.baseline }}</div>
<div class="card"><b>{{ tr.created }}</b>{{ experiment.freeze_created_at_utc }}</div>
<div class="card"><b>{{ tr.commit }}</b><span class="mono">{{ experiment.benchmark.commit or tr.none }}</span></div>
<div class="card"><b>{{ tr.duration }}</b>{{ fmt(dataset.duration_s) }}</div>
<div class="card"><b>{{ tr.playback }}</b>{{ fmt(dataset_timing.playback_rate) }}</div>
</div>
</section>
<section class="section"><h2>{{ tr.algorithms }}</h2><div class="scroll"><table>
<thead><tr><th>{{ tr.algorithm }}</th><th>{{ tr.status }}</th><th>{{ tr.health }}</th><th>{{ tr.eligible }}</th><th>{{ tr.path }}</th><th>{{ tr.zrange }}</th><th>{{ tr.cpu }}</th><th>{{ tr.rss }}</th><th>{{ tr.rmse }}</th><th>{{ tr.p95 }}</th><th>{{ tr.jumps }}</th></tr></thead>
<tbody>{% for row in rows %}<tr>
<td class="mono">{{ row.algorithm }}</td><td>{{ row.status or tr.none }}</td><td class="{{ 'ok' if row.health else 'bad' }}">{{ tr.yes if row.health else tr.no }}</td><td>{{ tr.yes if row.eligible else tr.no }}</td><td>{{ fmt(row.path_length_m) }}</td><td>{{ fmt(row.z_range_m) }}</td><td>{{ fmt(row.mean_cpu_percent) }}</td><td>{{ fmt(row.peak_rss_mib) }}</td><td>{{ fmt(row.rmse_m) }}</td><td>{{ fmt(row.p95_m) }}</td><td>{{ row.position_jump_count }}/{{ row.yaw_jump_count }}</td>
</tr>{% endfor %}</tbody></table></div>
<div class="grid" style="margin-top:14px"><div class="card"><b>{{ tr.scope }}</b>{{ conclusions.scope }}</div><div class="card"><b>{{ tr.healthy }}</b>{{ conclusions.health_valid_algorithms|join(', ') if conclusions.health_valid_algorithms else tr.none }}</div><div class="card"><b>{{ tr.excluded }}</b>{{ conclusions.not_recommended_this_run|join(', ') if conclusions.not_recommended_this_run else tr.none }}</div></div>
</section>
<section class="section"><h2>{{ tr.evidence }}</h2>
{% if figures %}<div class="figure-grid">{% for figure in figures %}<figure class="figure"><img src="{{ figure.href }}" alt="{{ figure.label }}"><figcaption>{{ figure.label }}</figcaption></figure>{% endfor %}</div>{% else %}<p class="muted">{{ tr.none }}</p>{% endif %}
<p><b>{{ tr.pointcloud }}:</b> {{ pointcloud.reason or (tr.yes if pointcloud.available else tr.no) }}</p>
</section>
<section class="section"><h2>{{ tr.anomalies }}</h2>
{% if cases %}{% for case in cases %}<div class="case"><b class="mono">{{ case.window_id }}</b> · {{ case.algorithm }} · {{ case.types|join(', ') }} · severity={{ fmt(case.severity) }}{% if case.view_start_bag_time_s is not none %} · {{ fmt(case.view_start_bag_time_s) }}–{{ fmt(case.view_end_bag_time_s) }} s{% endif %}</div>{% endfor %}{% else %}<p class="muted">{{ tr.none }}</p>{% endif %}
</section>
<section class="section"><h2>{{ tr.repro }}</h2><div class="check">{% for key,value in reproducibility.items() %}<div>{{ '✓' if value else '✗' }} <span class="mono">{{ key }}</span></div>{% endfor %}</div></section>
<section class="section"><h2>{{ tr.limitations }}</h2><ul>{% for item in limitations %}<li>{{ item }}</li>{% endfor %}</ul></section>
</main></body></html>
"""


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, bool):
        return "yes" if value else "no"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _safe_bundle_file(frozen: Path, bundle_path: str) -> tuple[Path, Path]:
    relative = Path(str(bundle_path))
    if relative.is_absolute() or ".." in relative.parts or str(relative) in {"", "."}:
        raise ValueError(f"invalid bundle evidence path: {bundle_path}")
    target = (frozen / relative).resolve()
    try:
        target.relative_to(frozen)
    except ValueError as exc:
        raise ValueError(f"evidence path escapes frozen bundle: {bundle_path}") from exc
    if not target.is_file():
        raise FileNotFoundError(bundle_path)
    return relative, target


def _safe_bundle_asset(frozen: Path, bundle_path: str) -> dict[str, str]:
    relative, target = _safe_bundle_file(frozen, bundle_path)
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
    }.get(target.suffix.lower())
    if mime is None:
        raise ValueError(f"unsupported HTML evidence image type: {bundle_path}")
    encoded = base64.b64encode(target.read_bytes()).decode("ascii")
    return {
        "label": relative.as_posix(),
        "href": f"data:{mime};base64,{encoded}",
    }


def _algorithm_rows(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    health = report_data.get("runtime_health") or {}
    trajectory = report_data.get("trajectory_summary") or {}
    relative = report_data.get("baseline_relative_diagnostics") or {}
    resources = report_data.get("resource_summary") or {}
    diagnostics = report_data.get("trajectory_diagnostics") or {}
    order = list(health) if isinstance(health, dict) else []
    rows: list[dict[str, Any]] = []
    for algorithm in order:
        h = dict(health.get(algorithm) or {})
        t = dict(trajectory.get(algorithm) or {}) if isinstance(trajectory, dict) else {}
        rel = dict(relative.get(algorithm) or {}) if isinstance(relative, dict) else {}
        res = dict(resources.get(algorithm) or {}) if isinstance(resources, dict) else {}
        diag = dict(diagnostics.get(algorithm) or {}) if isinstance(diagnostics, dict) else {}
        rows.append(
            {
                "algorithm": algorithm,
                "status": h.get("status"),
                "health": bool(h.get("trajectory_health_pass")),
                "eligible": bool(h.get("recommendation_eligible")),
                "path_length_m": t.get("path_length_m"),
                "z_range_m": t.get("z_range_m"),
                "mean_cpu_percent": res.get("mean_cpu_percent"),
                "peak_rss_mib": res.get("peak_rss_mib"),
                "rmse_m": rel.get("rmse_m"),
                "p95_m": rel.get("p95_m"),
                "position_jump_count": diag.get("position_jump_count", 0),
                "yaw_jump_count": diag.get("yaw_jump_count", 0),
            }
        )
    return rows


def render_report_html(frozen: Path) -> dict[str, Any]:
    try:
        from jinja2 import Environment, StrictUndefined, select_autoescape
    except ImportError as exc:
        raise RuntimeError(
            "Jinja2 is required for offline HTML reports. Install the report dependency set."
        ) from exc

    frozen = Path(frozen).resolve()
    freeze_manifest = _load_json(frozen / "freeze_manifest.json")
    if freeze_manifest.get("freeze_state") == "COMPLETE":
        raise ValueError("frozen bundle is already COMPLETE")
    report_data = _load_json(frozen / "report_data.json")
    evidence = _load_json(frozen / "evidence/evidence_manifest.json")

    language = str((report_data.get("experiment") or {}).get("language") or "zh-CN")
    if language not in LABELS:
        raise ValueError(f"unsupported report language: {language}")

    figures = [
        _safe_bundle_asset(frozen, str(item.get("bundle_path") or ""))
        for item in (evidence.get("static_figures") or [])
        if isinstance(item, dict)
    ]
    for item in evidence.get("anomaly_cases") or []:
        if isinstance(item, dict) and item.get("bundle_path"):
            _safe_bundle_file(frozen, str(item["bundle_path"]))

    dataset_timing = dict(report_data.get("dataset_timing") or {})
    dataset = dict(dataset_timing.get("dataset") or {})
    environment = Environment(
        autoescape=select_autoescape(default_for_string=True, default=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = environment.from_string(_TEMPLATE).render(
        lang=language,
        tr=LABELS[language],
        experiment=dict(report_data.get("experiment") or {}),
        metric_class=report_data.get("metric_class"),
        ground_truth_disclaimer=report_data.get("ground_truth_disclaimer"),
        dataset_timing=dataset_timing,
        dataset=dataset,
        rows=_algorithm_rows(report_data),
        conclusions=dict(report_data.get("evidence_based_conclusions") or {}),
        figures=figures,
        cases=list((report_data.get("anomaly_summary") or {}).get("representative_cases") or []),
        reproducibility=dict(report_data.get("reproducibility_checklist") or {}),
        pointcloud=dict(evidence.get("pointcloud_case_evidence") or {}),
        limitations=list(report_data.get("limitations") or []),
        fmt=_fmt,
    )

    output = frozen / "report/index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    artifact = register_generated_artifact(
        frozen, "report/index.html", "offline_html_report"
    )
    return {"path": output, "artifact": artifact}
