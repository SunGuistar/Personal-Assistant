"""把云记 .Jnotes 中的手写笔迹转换为可阅读的 PDF（阅读管理笔记上传用）。

基于一个真实 JNotes 样本的非官方格式逆向；不保证兼容所有云记版本。
依赖：reportlab（见 requirements.txt）。

独立调试：
  python -m app.services.jnotes_to_pdf "笔记.Jnotes"
  python -m app.services.jnotes_to_pdf "笔记.Jnotes" -o "输出.pdf"
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import tempfile
import zipfile
from pathlib import Path

from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

SEGMENT_RE = re.compile(rb"seg:(\d+)/(\d+)")
PAGE_RE = re.compile(rb"\x00\x04PAGE\x00\x02DB")


class JnotesConvertError(ValueError):
    """云记文件无法解析或转换（损坏、版本不兼容等）。"""


def read_pages(path: Path) -> list[list[dict]]:
    """从 zip.Jzip 中提取每页 STROKE JSON。"""
    with zipfile.ZipFile(path) as archive:
        if "zip.Jzip" not in archive.namelist():
            raise JnotesConvertError("未找到 zip.Jzip，可能不是兼容版本的云记文件")
        data = archive.read("zip.Jzip")

    page_headers = [m.start() for m in PAGE_RE.finditer(data)]
    if not page_headers:
        raise JnotesConvertError("未识别到 PAGE 记录")

    pages = []
    for index, start in enumerate(page_headers):
        end = page_headers[index + 1] if index + 1 < len(page_headers) else len(data)
        section = data[start:end]
        chunks = []
        for segment in SEGMENT_RE.finditer(section):
            # JSON 数组后面可能紧跟其他非 UTF-8 二进制数据，
            # 用 '[' 到匹配的 ']' 对应的字节区间，而不是 decode 整个文件。
            raw = section[segment.end():]
            # 当前样本中的 JSON 只使用 ASCII 结构字符，忽略后续二进制无碍。
            text = raw.decode("utf-8", errors="ignore")
            try:
                strokes, _ = json.JSONDecoder().raw_decode(text)
            except json.JSONDecodeError as exc:
                raise JnotesConvertError(f"第 {index + 1} 页笔迹 JSON 无法解析") from exc
            if not isinstance(strokes, list):
                raise JnotesConvertError(f"第 {index + 1} 页不是笔迹列表")
            chunks.append((int(segment.group(1)), strokes))
        if not chunks:
            raise JnotesConvertError(f"第 {index + 1} 页未找到笔迹分段；空白页暂不支持")
        chunks.sort(key=lambda entry: entry[0])
        pages.append([stroke for _, chunk in chunks for stroke in chunk])
    return pages


def rgb_from_signed_argb(value: int) -> Color:
    rgb = int(value) & 0xFFFFFF
    return Color(((rgb >> 16) & 255) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255)


def _point_erased(p: dict) -> bool:
    """点级擦除标志：云记橡皮擦不改写历史，而是把被擦点打上 c/d 非 0 的标记。

    实测样本（构建Agent实用指南.Jnotes）：整笔擦除 = 笔迹所有点被标记；
    部分擦除 = 笔迹内连续点被标记。缺省（无 c/d 键，如早期样本）视为可见。
    """
    return bool(p.get("c") or p.get("d"))


def _visible_runs(coords: list[dict]) -> list[list[dict]]:
    """按擦除标志把笔迹点列切成可见段；完全被擦除的笔迹返回空列表。"""
    runs: list[list[dict]] = []
    current: list[dict] = []
    for p in coords:
        if _point_erased(p):
            if current:
                runs.append(current)
                current = []
        else:
            current.append(p)
    if current:
        runs.append(current)
    return runs


def _stroke_bounds(pages: list[list[dict]]) -> tuple[float, float, float, float] | None:
    """全部页**可见**笔迹点的包围盒 (min_x, min_y, max_x, max_y)；无有效点时返回 None。"""
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for strokes in pages:
        for stroke in strokes:
            for run in _visible_runs(stroke.get("c", {}).get("k", [])):
                for p in run:
                    if "x" in p and "y" in p:
                        x, y = float(p["x"]), float(p["y"])
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x)
                        max_y = max(max_y, y)
    if min_x == float("inf"):
        return None
    return min_x, min_y, max_x, max_y


def _layout(bounds: tuple[float, float, float, float], pad: float = 24.0) -> tuple[float, float, float, float, float]:
    """按笔迹包围盒计算版面：页面方向、缩放与原点（PDF 坐标，y 向上）。

    返回 (pdf_width, pdf_height, fit, origin_x, origin_y)，
    映射关系：x_pdf = origin_x + x * fit；y_pdf = origin_y - y * fit。
    """
    min_x, min_y, max_x, max_y = bounds
    content_width = max_x - min_x
    content_height = max_y - min_y
    if content_width <= 0 or content_height <= 0:
        raise JnotesConvertError("笔迹坐标退化，无法确定页面范围")

    if content_height > content_width:
        pdf_width, pdf_height = 595.28, 841.89  # A4 竖版
    else:
        pdf_width, pdf_height = 841.89, 595.28  # A4 横版

    fit = min((pdf_width - 2 * pad) / content_width, (pdf_height - 2 * pad) / content_height)
    origin_x = (pdf_width - content_width * fit) / 2 - min_x * fit
    origin_y = (pdf_height + content_height * fit) / 2 + min_y * fit
    return pdf_width, pdf_height, fit, origin_x, origin_y


def convert(input_path: Path, output_path: Path, background: bool = True) -> None:
    pages = read_pages(input_path)

    # 画布不能写死样本的横向 1754 x 1240：云记页面方向/尺寸因笔记而异，
    # 超出固定画布的笔迹会被裁剪。改为按全部笔迹的包围盒自适应：
    # 内容高 > 宽用 A4 竖版，否则 A4 横版；统一缩放居中，保证完整显示。
    bounds = _stroke_bounds(pages)
    if bounds is None:
        raise JnotesConvertError("未找到任何有效笔迹坐标")
    pdf_width, pdf_height, fit, origin_x, origin_y = _layout(bounds)
    min_x, min_y, max_x, max_y = bounds

    pdf = canvas.Canvas(str(output_path), pagesize=(pdf_width, pdf_height), pageCompression=1)
    pdf.setTitle(input_path.stem)

    # 横线纸背景：按内容范围等距布线（原样本为 40 单位间距），而非写死样本画布
    bg_top = origin_y - min_y * fit
    bg_bottom = origin_y - max_y * fit
    bg_left = origin_x + min_x * fit
    bg_right = origin_x + max_x * fit

    for page_no, strokes in enumerate(pages, start=1):
        if background:
            pdf.setFillColorRGB(0.986, 0.978, 0.954)
            pdf.rect(0, 0, pdf_width, pdf_height, fill=1, stroke=0)
            pdf.setStrokeColorRGB(0.81, 0.81, 0.79)
            pdf.setLineWidth(0.35)
            y = bg_top - 24.0
            while y > bg_bottom:
                pdf.line(bg_left, y, bg_right, y)
                y -= 40 * fit

        for stroke in strokes:
            info = stroke.get("c", {})
            coords = info.get("k", [])
            if not coords:
                continue
            color = rgb_from_signed_argb(info.get("c", -16777216))
            pdf.setStrokeColor(color)
            pdf.setFillColor(color)
            pdf.setLineCap(1)
            pdf.setLineJoin(1)
            width = max(0.35, float(info.get("d", 5.0)) * fit * 0.65)
            pdf.setLineWidth(width)
            # 被擦除的点不打断成连线：按可见段分别绘制，整笔被擦则自然消失
            for run in _visible_runs(coords):
                pts = [(origin_x + float(p["x"]) * fit, origin_y - float(p["y"]) * fit)
                       for p in run if "x" in p and "y" in p]
                if not pts:
                    continue
                if len(pts) == 1:
                    x, y = pts[0]
                    pdf.circle(x, y, width / 2, stroke=0, fill=1)
                    continue
                path = pdf.beginPath()
                path.moveTo(*pts[0])
                for x, y in pts[1:]:
                    path.lineTo(x, y)
                pdf.drawPath(path, stroke=1, fill=0)
        pdf.showPage()
        logger.info("Jnotes 转换进度：第 %s/%s 页，%s 条笔迹", page_no, len(pages), len(strokes))
    pdf.save()
    logger.info("Jnotes 转换完成：%s", output_path)


def convert_bytes(filename: str, data: bytes) -> tuple[str, bytes]:
    """在临时目录中把 .Jnotes 字节转换为 PDF，返回 (pdf 文件名, pdf 字节)。

    任何解析/转换失败都抛 JnotesConvertError；临时文件随目录自动清理。
    """

    stem = Path(filename).stem or "笔记"
    with tempfile.TemporaryDirectory(prefix="jnotes_") as tmp:
        src = Path(tmp) / f"{stem}.jnotes"
        dst = Path(tmp) / f"{stem}.pdf"
        src.write_bytes(data)
        try:
            convert(src, dst)
        except (JnotesConvertError, zipfile.BadZipFile, OSError) as exc:
            raise JnotesConvertError(f"云记文件转换失败：{exc}") from exc
        return f"{stem}.pdf", dst.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser(description="云记 JNotes 手写笔迹转 PDF（实验性）")
    parser.add_argument("input", type=Path, help=".Jnotes 输入路径")
    parser.add_argument("-o", "--output", type=Path, help="输出 PDF，默认为同名 .pdf")
    parser.add_argument("--no-background", action="store_true", help="不要模拟横线纸背景")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    output = args.output or args.input.with_suffix(".pdf")
    convert(args.input, output, background=not args.no_background)


if __name__ == "__main__":
    main()
