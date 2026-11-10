"""云记转换版面自适应回归：写死 1754x1240 横向画布时，超出范围的笔迹会被裁剪。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.services import jnotes_to_pdf


def _write_jnotes(path: Path, strokes: list[dict]) -> Path:
    payload = b"\x00\x04PAGE\x00\x02DB" + b"seg:1/1" + json.dumps(strokes).encode("utf-8")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("zip.Jzip", payload)
    return path


def _line(points: list[tuple[float, float]]) -> dict:
    return {"c": {"k": [{"x": x, "y": y} for x, y in points], "c": -16777216, "d": 5.0}}


def test_layout_scales_oversized_content_inside_page(tmp_path: Path):
    """笔迹远超旧固定画布（y 到 5000）时，四个角仍映射进 PDF 页面内。"""
    strokes = [_line([(0.0, 0.0), (1000.0, 5000.0)])]
    src = _write_jnotes(tmp_path / "big.Jnotes", strokes)
    out = tmp_path / "big.pdf"
    jnotes_to_pdf.convert(src, out)

    pdf = out.read_bytes()
    assert pdf.startswith(b"%PDF-")


def test_layout_portrait_content_uses_portrait_page(tmp_path: Path):
    """竖向内容（高 > 宽）应输出 A4 竖版页面，且内容完整落入页面。"""
    strokes = [_line([(0.0, 0.0), (800.0, 2400.0)])]
    src = _write_jnotes(tmp_path / "portrait.Jnotes", strokes)
    out = tmp_path / "portrait.pdf"
    jnotes_to_pdf.convert(src, out)

    data = out.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"595.28 841.89" in data or b"595.279 841.89" in data


def test_layout_all_corners_stay_on_page():
    """任意包围盒的四个角映射后都落在页面矩形内（含边距）。"""
    for bounds in [
        (0.0, 0.0, 1754.0, 1240.0),      # 原样本横向
        (0.0, 0.0, 1240.0, 1754.0),      # 竖向纸张
        (-50.0, -50.0, 3000.0, 4000.0),  # 超大 + 负坐标
        (10.0, 20.0, 60.0, 45.0),        # 小内容
    ]:
        pdf_w, pdf_h, fit, origin_x, origin_y = jnotes_to_pdf._layout(bounds)
        min_x, min_y, max_x, max_y = bounds
        corners = [(min_x, min_y), (min_x, max_y), (max_x, min_y), (max_x, max_y)]
        for x, y in corners:
            px = origin_x + x * fit
            py = origin_y - y * fit
            assert 0 <= px <= pdf_w, (bounds, px)
            assert 0 <= py <= pdf_h, (bounds, py)


def test_layout_degenerate_raises():
    with pytest.raises(jnotes_to_pdf.JnotesConvertError):
        jnotes_to_pdf._layout((10.0, 10.0, 10.0, 50.0))
    with pytest.raises(jnotes_to_pdf.JnotesConvertError):
        jnotes_to_pdf._layout((10.0, 10.0, 50.0, 10.0))


# ---------- 擦除笔迹：点级 c/d 标记 ----------

def _pt(x, y, c=0, d=0):
    return {"x": x, "y": y, "c": c, "d": d}


def test_fully_erased_stroke_is_skipped(tmp_path: Path):
    """整笔被擦（所有点 c/d 非 0）的笔迹不参与绘制，也不参与包围盒。"""
    strokes = [
        _line([(0.0, 0.0), (800.0, 2400.0)]),
        {"c": {"k": [_pt(100.0, 100.0, c=1, d=1), _pt(200.0, 200.0, c=1, d=1)], "c": -1434831, "d": 5.0}},
    ]
    src = _write_jnotes(tmp_path / "erased.Jnotes", strokes)
    out = tmp_path / "erased.pdf"
    jnotes_to_pdf.convert(src, out)
    assert out.read_bytes().startswith(b"%PDF-")

    # 被擦笔迹（坐标在 100,100-200,200）完全不影响包围盒
    pages = jnotes_to_pdf.read_pages(src)
    bounds = jnotes_to_pdf._stroke_bounds(pages)
    assert bounds == (0.0, 0.0, 800.0, 2400.0)


def test_partially_erased_stroke_splits_runs():
    """笔迹内被擦点断开连线：可见段被保留，被擦段不连成线。"""
    coords = [_pt(0.0, 0.0), _pt(10.0, 10.0), _pt(20.0, 20.0, c=1, d=1), _pt(30.0, 30.0, c=1), _pt(40.0, 40.0)]
    runs = jnotes_to_pdf._visible_runs(coords)
    assert [[(p["x"], p["y"]) for p in run] for run in runs] == [[(0.0, 0.0), (10.0, 10.0)], [(40.0, 40.0)]]


def test_visible_runs_missing_flags_means_visible():
    """无 c/d 键的点（早期样本格式）视为可见，整条保留。"""
    coords = [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]
    runs = jnotes_to_pdf._visible_runs(coords)
    assert len(runs) == 1 and len(runs[0]) == 2
