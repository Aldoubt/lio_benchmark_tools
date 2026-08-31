from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

from freeze_experiment import register_generated_artifact


DEFAULT_CJK_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf"),
    Path("/usr/share/fonts/truetype/arphic-gkai00mp/gkai00mp.ttf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def resolve_cjk_font(candidates: Iterable[Path] | None = None) -> Path | None:
    if candidates is None:
        values: list[Path] = []
        configured = os.environ.get("LIO_BENCHMARK_CJK_FONT")
        if configured:
            values.append(Path(configured).expanduser())
        values.extend(DEFAULT_CJK_FONT_CANDIDATES)
    else:
        values = [Path(item).expanduser() for item in candidates]
    for path in values:
        if path.is_file():
            return path.resolve()
    return None


def _safe_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\u2013", "-").replace("\u2014", "-")


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, bool):
        return "yes" if value else "no"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _safe_text(value)
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _safe_bundle_file(frozen: Path, bundle_path: str) -> Path:
    relative = Path(str(bundle_path))
    if relative.is_absolute() or ".." in relative.parts or str(relative) in {"", "."}:
        raise ValueError(f"invalid frozen evidence path: {bundle_path}")
    target = (frozen / relative).resolve()
    try:
        target.relative_to(frozen)
    except ValueError as exc:
        raise ValueError(f"evidence path escapes frozen bundle: {bundle_path}") from exc
    if not target.is_file():
        raise FileNotFoundError(bundle_path)
    return target


def _font_setup(
    language: str, cjk_font_candidates: Iterable[Path] | None
) -> tuple[str, str | None]:
    if language == "en":
        return "Helvetica", None
    if language != "zh-CN":
        raise ValueError(f"unsupported report language: {language}")

    font_path = resolve_cjk_font(cjk_font_candidates)
    if font_path is None:
        raise RuntimeError(
            "A locally installed CJK font is required for zh-CN PDF reports. "
            "Install a CJK TTF or set LIO_BENCHMARK_CJK_FONT."
        )
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        digest = hashlib.sha256(str(font_path).encode("utf-8")).hexdigest()[:10]
        font_name = f"LIO-CJK-{digest}"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    except Exception as exc:
        raise RuntimeError(f"CJK font could not be loaded: {font_path}") from exc
    return font_name, str(font_path)


def _paragraph(text: Any, style: Any) -> Any:
    from reportlab.platypus import Paragraph

    return Paragraph(escape(_safe_text(text)), style)


def _algorithm_rows(
    report_data: dict[str, Any], paragraph_style: Any
) -> list[list[Any]]:
    health = report_data.get("runtime_health") or {}
    trajectories = report_data.get("trajectory_summary") or {}
    relative = report_data.get("baseline_relative_diagnostics") or {}
    resources = report_data.get("resource_summary") or {}
    diagnostics = report_data.get("trajectory_diagnostics") or {}
    rows: list[list[Any]] = []
    for algorithm in health if isinstance(health, dict) else []:
        h = dict(health.get(algorithm) or {})
        t = (
            dict(trajectories.get(algorithm) or {})
            if isinstance(trajectories, dict)
            else {}
        )
        rel = (
            dict(relative.get(algorithm) or {})
            if isinstance(relative, dict)
            else {}
        )
        res = (
            dict(resources.get(algorithm) or {})
            if isinstance(resources, dict)
            else {}
        )
        diag = (
            dict(diagnostics.get(algorithm) or {})
            if isinstance(diagnostics, dict)
            else {}
        )
        flags = ",".join(str(item) for item in (h.get("health_flags") or [])) or "none"
        rows.append(
            [
                _paragraph(algorithm, paragraph_style),
                _paragraph(h.get("status") or "N/A", paragraph_style),
                _paragraph(
                    "yes"
                    if h.get("trajectory_health_pass")
                    else f"no ({flags})",
                    paragraph_style,
                ),
                _paragraph(
                    "yes" if h.get("recommendation_eligible") else "no",
                    paragraph_style,
                ),
                _paragraph(_fmt(t.get("path_length_m")), paragraph_style),
                _paragraph(_fmt(t.get("z_range_m")), paragraph_style),
                _paragraph(_fmt(res.get("mean_cpu_percent")), paragraph_style),
                _paragraph(_fmt(res.get("peak_rss_mib")), paragraph_style),
                _paragraph(_fmt(rel.get("rmse_m")), paragraph_style),
                _paragraph(_fmt(rel.get("p95_m")), paragraph_style),
                _paragraph(
                    f"{diag.get('position_jump_count', 0)}/{diag.get('yaw_jump_count', 0)}",
                    paragraph_style,
                ),
            ]
        )
    return rows


def render_report_pdf(
    frozen: Path,
    *,
    cjk_font_candidates: Iterable[Path] | None = None,
) -> dict[str, Any]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Image,
            KeepTogether,
            LongTable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError(
            "ReportLab is required for PDF reports. Install the report dependency set."
        ) from exc

    frozen = Path(frozen).resolve()
    freeze_manifest = _load_json(frozen / "freeze_manifest.json")
    if freeze_manifest.get("freeze_state") == "COMPLETE":
        raise ValueError("frozen bundle is already COMPLETE")
    report_data = _load_json(frozen / "report_data.json")
    evidence = _load_json(frozen / "evidence/evidence_manifest.json")

    experiment = dict(report_data.get("experiment") or {})
    language = str(experiment.get("language") or "zh-CN")
    font_name, font_path = _font_setup(language, cjk_font_candidates)

    labels = (
        {
            "title": "LIO 冻结实验报告",
            "overview": "实验与来源",
            "comparison": "算法对比",
            "evidence": "静态证据",
            "anomaly": "代表异常案例",
            "repro": "可复现性检查",
            "limits": "限制与解释边界",
            "calib": "标定披露",
        }
        if language == "zh-CN"
        else {
            "title": "Frozen LIO Experiment Report",
            "overview": "Experiment and Provenance",
            "comparison": "Algorithm Comparison",
            "evidence": "Static Evidence",
            "anomaly": "Representative Anomaly Cases",
            "repro": "Reproducibility Checklist",
            "limits": "Limitations and Interpretation Boundary",
            "calib": "Calibration Disclosure",
        }
    )

    output = frozen / "report/report.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=page_size,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        title=f"{labels['title']} - {experiment.get('run_id', '')}",
        author="lio_benchmark_tools",
    )

    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "lio-title",
        parent=base["Title"],
        fontName=font_name,
        fontSize=20,
        leading=25,
        alignment=TA_LEFT,
        spaceAfter=8,
        wordWrap="CJK" if language == "zh-CN" else None,
    )
    heading_style = ParagraphStyle(
        "lio-heading",
        parent=base["Heading2"],
        fontName=font_name,
        fontSize=13,
        leading=17,
        spaceBefore=8,
        spaceAfter=7,
        wordWrap="CJK" if language == "zh-CN" else None,
    )
    body_style = ParagraphStyle(
        "lio-body",
        parent=base["BodyText"],
        fontName=font_name,
        fontSize=8.7,
        leading=12,
        wordWrap="CJK" if language == "zh-CN" else None,
    )
    small_style = ParagraphStyle(
        "lio-small", parent=body_style, fontSize=7.2, leading=9.2
    )
    notice_style = ParagraphStyle(
        "lio-notice",
        parent=body_style,
        borderWidth=0.5,
        borderColor=colors.HexColor("#A7A7A7"),
        borderPadding=7,
        backColor=colors.HexColor("#F4F4F4"),
        spaceAfter=9,
    )

    story: list[Any] = [
        Paragraph(escape(labels["title"]), title_style),
        _paragraph(
            f"{experiment.get('run_id', 'N/A')} | {report_data.get('metric_class', 'N/A')}",
            body_style,
        ),
        Spacer(1, 4 * mm),
        _paragraph(report_data.get("ground_truth_disclaimer") or "", notice_style),
        Paragraph(escape(labels["overview"]), heading_style),
    ]

    dataset_timing = dict(report_data.get("dataset_timing") or {})
    dataset = dict(dataset_timing.get("dataset") or {})
    benchmark = dict(experiment.get("benchmark") or {})
    provenance_rows = [
        ["run_id", experiment.get("run_id")],
        ["source_run_state", experiment.get("source_run_state")],
        ["baseline", experiment.get("baseline")],
        ["freeze_created_at_utc", experiment.get("freeze_created_at_utc")],
        ["benchmark.branch", benchmark.get("branch")],
        ["benchmark.commit", benchmark.get("commit")],
        ["dataset.duration_s", dataset.get("duration_s")],
        ["playback_rate", dataset_timing.get("playback_rate")],
        ["dataset.sha256", (dataset_timing.get("dataset_source") or {}).get("sha256")],
    ]
    provenance_table = Table(
        [
            [
                _paragraph(key, small_style),
                _paragraph(value if value is not None else "N/A", small_style),
            ]
            for key, value in provenance_rows
        ],
        colWidths=[48 * mm, 190 * mm],
        hAlign="LEFT",
    )
    provenance_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9D9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F5F5")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([provenance_table, Spacer(1, 4 * mm)])

    story.append(Paragraph(escape(labels["calib"]), heading_style))
    calibration = dict(report_data.get("calibration") or {})
    story.append(
        _paragraph(
            f"source={calibration.get('source', 'N/A')} | confidence={calibration.get('confidence', 'N/A')}",
            body_style,
        )
    )

    story.append(Paragraph(escape(labels["comparison"]), heading_style))
    headers = [
        "Algorithm",
        "Status",
        "Health",
        "Eligible",
        "Path(m)",
        "Z range(m)",
        "CPU%",
        "RSS MiB",
        "Rel RMSE",
        "Rel P95",
        "P/Y jumps",
    ]
    table_data = [
        [_paragraph(item, small_style) for item in headers]
    ] + _algorithm_rows(report_data, small_style)
    comparison_table = LongTable(
        table_data,
        repeatRows=1,
        colWidths=[
            31 * mm,
            22 * mm,
            37 * mm,
            18 * mm,
            18 * mm,
            20 * mm,
            18 * mm,
            20 * mm,
            21 * mm,
            19 * mm,
            20 * mm,
        ],
    )
    comparison_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9D9")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.extend([comparison_table, Spacer(1, 3 * mm)])

    conclusions = dict(report_data.get("evidence_based_conclusions") or {})
    story.append(
        _paragraph(
            f"scope={conclusions.get('scope', 'N/A')} | health_valid={','.join(conclusions.get('health_valid_algorithms') or []) or 'N/A'} | not_recommended={','.join(conclusions.get('not_recommended_this_run') or []) or 'none'}",
            body_style,
        )
    )

    static_figures = [
        item
        for item in (evidence.get("static_figures") or [])
        if isinstance(item, dict)
    ]
    if static_figures:
        story.extend(
            [PageBreak(), Paragraph(escape(labels["evidence"]), heading_style)]
        )
        for item in static_figures:
            bundle_path = str(item.get("bundle_path") or "")
            path = _safe_bundle_file(frozen, bundle_path)
            try:
                image = Image(str(path))
                max_w, max_h = 245 * mm, 135 * mm
                scale = min(
                    max_w / image.imageWidth,
                    max_h / image.imageHeight,
                    1.0,
                )
                image.drawWidth = image.imageWidth * scale
                image.drawHeight = image.imageHeight * scale
                story.append(
                    KeepTogether(
                        [
                            _paragraph(bundle_path, small_style),
                            Spacer(1, 2 * mm),
                            image,
                            Spacer(1, 5 * mm),
                        ]
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    f"failed to embed PDF evidence image: {bundle_path}"
                ) from exc

    story.append(Paragraph(escape(labels["anomaly"]), heading_style))
    cases = list(
        (report_data.get("anomaly_summary") or {}).get("representative_cases")
        or []
    )
    if not cases:
        story.append(_paragraph("N/A", body_style))
    for case in cases:
        if not isinstance(case, dict):
            continue
        story.append(
            _paragraph(
                f"{case.get('window_id')} | {case.get('algorithm')} | {','.join(case.get('types') or [])} | severity={_fmt(case.get('severity'))} | view={_fmt(case.get('view_start_bag_time_s'))}-{_fmt(case.get('view_end_bag_time_s'))}s",
                body_style,
            )
        )

    story.append(Paragraph(escape(labels["repro"]), heading_style))
    reproducibility = dict(report_data.get("reproducibility_checklist") or {})
    repro_data = [
        [
            _paragraph(key, small_style),
            _paragraph("PASS" if value else "FAIL", small_style),
        ]
        for key, value in reproducibility.items()
    ]
    if repro_data:
        repro_table = Table(
            repro_data, colWidths=[120 * mm, 30 * mm], hAlign="LEFT"
        )
        repro_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9D9")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(repro_table)

    story.append(Paragraph(escape(labels["limits"]), heading_style))
    for limitation in report_data.get("limitations") or []:
        story.append(_paragraph(f"- {limitation}", body_style))

    run_id = _safe_text(experiment.get("run_id") or "")

    def draw_footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 7)
        canvas.drawString(14 * mm, 8 * mm, f"{run_id} | frozen report")
        canvas.drawRightString(
            page_size[0] - 14 * mm, 8 * mm, f"page {document.page}"
        )
        canvas.restoreState()

    try:
        doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    except Exception:
        if output.exists():
            output.unlink()
        raise

    artifact = register_generated_artifact(
        frozen, "report/report.pdf", "offline_pdf_report"
    )
    return {"path": output, "artifact": artifact, "font_path": font_path}
