#!/usr/bin/env python3
"""
根据元数据快速过滤图片对CSV。

规则：
1. 仅保留jpg/jpeg/png。
2. 过滤长宽比不在[1/2.5, 2.5]范围内的图片。
3. 过滤短边>2400或长边>3600的图片。
4. 图片缺失、格式损坏视为无效。
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Tuple

# 可快速调整的参数
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_ASPECT_RATIO = 2.5
MIN_ASPECT_RATIO = 1 / MAX_ASPECT_RATIO
MAX_SHORT_EDGE = 2400
MAX_LONG_EDGE = 3600
PROGRESS_INTERVAL = 10_000

REASON_LABELS = {
    "unsupported_format": "格式不在允许列表",
    "missing_or_corrupt": "文件缺失或格式损坏",
    "aspect_ratio": "长宽比超出阈值",
    "oversized": "尺寸超出阈值",
}


class ImageMetaError(Exception):
    """基类：解析图片元数据时出现问题。"""


class UnsupportedFormatError(ImageMetaError):
    """图片格式不支持（或扩展名不在允许列表）。"""


class CorruptImageError(ImageMetaError):
    """图片文件损坏或结构异常。"""


@dataclass
class FilterStats:
    total_pairs: int = 0
    kept_pairs: int = 0
    reason_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_failure(self, reason: str) -> None:
        self.reason_counts[reason] += 1


def read_png_size(path: Path) -> Tuple[int, int]:
    with path.open("rb") as fh:
        signature = fh.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            raise CorruptImageError("PNG签名不匹配")
        chunk_len = int.from_bytes(fh.read(4), "big")
        chunk_type = fh.read(4)
        if chunk_type != b"IHDR" or chunk_len != 13:
            raise CorruptImageError("缺少IHDR块")
        data = fh.read(13)
        width = int.from_bytes(data[0:4], "big")
        height = int.from_bytes(data[4:8], "big")
        if not width or not height:
            raise CorruptImageError("PNG尺寸为零")
        return width, height


def read_jpeg_size(path: Path) -> Tuple[int, int]:
    with path.open("rb") as fh:
        if fh.read(2) != b"\xff\xd8":
            raise CorruptImageError("JPEG缺少SOI标记")
        while True:
            marker_prefix = fh.read(1)
            if not marker_prefix:
                break
            if marker_prefix != b"\xff":
                continue
            marker = fh.read(1)
            while marker == b"\xff":
                marker = fh.read(1)
            if not marker:
                break
            marker_value = marker[0]
            if marker_value in (0xD8, 0xD9):
                continue
            length_bytes = fh.read(2)
            if len(length_bytes) != 2:
                break
            segment_length = int.from_bytes(length_bytes, "big")
            if segment_length < 2:
                raise CorruptImageError("JPEG段长度非法")
            if 0xC0 <= marker_value <= 0xCF and marker_value not in (0xC4, 0xC8, 0xCC):
                fh.read(1)  # 精度
                height = int.from_bytes(fh.read(2), "big")
                width = int.from_bytes(fh.read(2), "big")
                if not width or not height:
                    raise CorruptImageError("JPEG尺寸为零")
                return width, height
            fh.seek(segment_length - 2, 1)
    raise CorruptImageError("未找到SOF段")


def read_image_size(path: Path) -> Tuple[int, int]:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return read_jpeg_size(path)
    if suffix == ".png":
        return read_png_size(path)
    raise UnsupportedFormatError(f"不支持的扩展名: {suffix}")


def validate_image(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return "unsupported_format"
    try:
        width, height = read_image_size(path)
    except FileNotFoundError:
        return "missing_or_corrupt"
    except CorruptImageError:
        return "missing_or_corrupt"
    except UnsupportedFormatError:
        return "unsupported_format"

    aspect_ratio = width / height
    if aspect_ratio < MIN_ASPECT_RATIO or aspect_ratio > MAX_ASPECT_RATIO:
        return "aspect_ratio"

    short_edge = min(width, height)
    long_edge = max(width, height)
    if short_edge > MAX_SHORT_EDGE or long_edge > MAX_LONG_EDGE:
        return "oversized"

    return None


def evaluate_pair(row: Dict[str, str], image_keys: Iterable[str]) -> str | None:
    for key in image_keys:
        path_str = row.get(key, "").strip()
        if not path_str:
            return "missing_or_corrupt"
        reason = validate_image(Path(path_str))
        if reason:
            return reason
    return None


def print_progress(stats: FilterStats) -> None:
    filtered = stats.total_pairs - stats.kept_pairs
    print(
        f"[进度] 已处理 {stats.total_pairs:,} 对，保留 {stats.kept_pairs:,} 对，过滤 {filtered:,} 对",
        flush=True,
    )


def build_report(stats: FilterStats, input_csv: Path, output_csv: Path) -> str:
    filtered_total = stats.total_pairs - stats.kept_pairs
    lines = [
        "过滤报告",
        f"输入文件: {input_csv}",
        f"输出文件: {output_csv}",
        "",
        "参数:",
        f"- 允许格式: {', '.join(sorted(ext.lstrip('.') for ext in ALLOWED_EXTENSIONS))}",
        f"- 长宽比范围: {MIN_ASPECT_RATIO:.3f} - {MAX_ASPECT_RATIO:.3f}",
        f"- 尺寸阈值: 短边≤{MAX_SHORT_EDGE}, 长边≤{MAX_LONG_EDGE}",
        "",
        "结果:",
        f"- 总图片对: {stats.total_pairs:,}",
        f"- 保留: {stats.kept_pairs:,}",
        f"- 过滤: {filtered_total:,}",
    ]

    if filtered_total:
        lines.append("")
        lines.append("按原因统计:")
        for reason, label in REASON_LABELS.items():
            count = stats.reason_counts.get(reason, 0)
            percentage = (count / stats.total_pairs * 100) if stats.total_pairs else 0.0
            lines.append(f"  * {label}: {count:,} ({percentage:.2f}%)")

    return "\n".join(lines)


def process_csv(input_csv: Path, output_csv: Path, report_path: Path) -> None:
    if input_csv == output_csv:
        raise ValueError("输出CSV不能与输入CSV相同")

    stats = FilterStats()
    with input_csv.open("r", newline="", encoding="utf-8") as src, output_csv.open(
        "w", newline="", encoding="utf-8"
    ) as dst:
        reader = csv.DictReader(src)
        if not reader.fieldnames:
            raise ValueError("输入CSV缺少表头")
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        image_keys = ("target_image_path", "source_image_path")

        for row in reader:
            stats.total_pairs += 1
            reason = evaluate_pair(row, image_keys)
            if reason:
                stats.record_failure(reason)
            else:
                writer.writerow(row)
                stats.kept_pairs += 1

            if stats.total_pairs % PROGRESS_INTERVAL == 0:
                print_progress(stats)

    report = build_report(stats, input_csv, output_csv)
    print_progress(stats)
    print("\n" + report)
    report_path.write_text(report + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="过滤不符合要求的图片对CSV")
    parser.add_argument("input_csv", type=Path, help="原始图片对CSV路径")
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="过滤后的CSV路径（默认与输入同目录，命名为 *_filtered.csv）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="报告输出路径（默认与输入同目录，命名为 *_filter_report.txt）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_csv = args.input_csv.resolve()
    if not input_csv.exists():
        raise FileNotFoundError(f"找不到输入文件: {input_csv}")
    default_output = input_csv.with_name(f"{input_csv.stem}_filtered.csv")
    default_report = input_csv.with_name(f"{input_csv.stem}_filter_report.txt")
    output_csv = (args.output_csv or default_output).resolve()
    report_path = (args.report or default_report).resolve()
    process_csv(input_csv, output_csv, report_path)


if __name__ == "__main__":
    main()
