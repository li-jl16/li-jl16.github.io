#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片对过滤脚本
根据元数据快速过滤不符合要求的图片对
"""

import csv
import os
import struct
import imghdr
from pathlib import Path
from typing import Tuple, Optional, Dict
from datetime import datetime
from tqdm import tqdm

# ==================== 可配置参数 ====================
# 长宽比限制（最小比例和最大比例）
MIN_ASPECT_RATIO = 1 / 2.5  # 1:2.5
MAX_ASPECT_RATIO = 2.5       # 2.5:1

# 图片尺寸限制
MAX_SHORT_SIDE = 2400  # 短边最大值
MAX_LONG_SIDE = 3600   # 长边最大值

# 允许的图片格式（小写）
ALLOWED_FORMATS = {'jpg', 'jpeg', 'png'}
# ====================================================


def get_image_size_fast(filepath: str) -> Optional[Tuple[int, int, str]]:
    """
    快速获取图片尺寸和格式，不加载整个图片到内存
    返回: (width, height, format) 或 None
    """
    try:
        with open(filepath, 'rb') as f:
            # 读取文件头部识别格式
            head = f.read(32)
            if len(head) < 24:
                return None
            
            # 检测图片格式
            fmt = imghdr.what(filepath)
            if fmt is None:
                return None
            
            # PNG格式
            if head[:8] == b'\x89PNG\r\n\x1a\n':
                # PNG的IHDR块包含宽高信息
                f.seek(16)
                width, height = struct.unpack('>II', f.read(8))
                return width, height, 'png'
            
            # JPEG格式
            elif head[:2] == b'\xff\xd8':
                f.seek(0)
                size = 2
                ftype = 0
                while not 0xc0 <= ftype <= 0xcf or ftype in (0xc4, 0xc8, 0xcc):
                    f.seek(size, 1)
                    byte = f.read(1)
                    while ord(byte) == 0xff:
                        byte = f.read(1)
                    ftype = ord(byte)
                    size = struct.unpack('>H', f.read(2))[0] - 2
                
                f.seek(1, 1)
                height, width = struct.unpack('>HH', f.read(4))
                return width, height, 'jpeg'
            
            # GIF格式（需要过滤）
            elif head[:6] in (b'GIF87a', b'GIF89a'):
                width, height = struct.unpack('<HH', head[6:10])
                return width, height, 'gif'
            
            # WebP格式
            elif head[:4] == b'RIFF' and head[8:12] == b'WEBP':
                return None, None, 'webp'
            
            # 其他格式尝试用imghdr
            else:
                # 尝试使用PIL作为后备
                try:
                    from PIL import Image
                    with Image.open(filepath) as img:
                        return img.width, img.height, img.format.lower() if img.format else fmt
                except:
                    return None
                    
    except Exception as e:
        return None


def check_image_valid(filepath: str) -> Tuple[bool, str]:
    """
    检查图片是否符合要求
    返回: (是否有效, 失败原因)
    """
    # 检查文件是否存在
    if not os.path.exists(filepath):
        return False, "文件不存在"
    
    # 获取图片信息
    img_info = get_image_size_fast(filepath)
    if img_info is None:
        return False, "格式损坏或无法识别"
    
    width, height, fmt = img_info
    
    # 检查格式
    if fmt not in ALLOWED_FORMATS:
        return False, f"不支持的格式({fmt})"
    
    # 检查尺寸是否有效
    if width is None or height is None or width <= 0 or height <= 0:
        return False, "无效的尺寸"
    
    # 检查长宽比
    aspect_ratio = width / height
    if aspect_ratio < MIN_ASPECT_RATIO or aspect_ratio > MAX_ASPECT_RATIO:
        return False, f"长宽比不符({aspect_ratio:.2f})"
    
    # 检查尺寸限制
    short_side = min(width, height)
    long_side = max(width, height)
    
    if short_side > MAX_SHORT_SIDE:
        return False, f"短边过大({short_side}>{MAX_SHORT_SIDE})"
    
    if long_side > MAX_LONG_SIDE:
        return False, f"长边过大({long_side}>{MAX_LONG_SIDE})"
    
    return True, ""


def process_csv(input_csv: str, output_csv: str = None):
    """
    处理CSV文件，过滤不符合要求的图片对
    """
    if output_csv is None:
        # 生成输出文件名：原文件名_filtered.csv
        input_path = Path(input_csv)
        output_csv = str(input_path.parent / f"{input_path.stem}_filtered{input_path.suffix}")
    
    # 统计信息
    stats = {
        'total': 0,
        'valid': 0,
        'filtered': 0,
        'reasons': {}
    }
    
    # 读取CSV并处理
    print(f"\n开始处理CSV文件: {input_csv}")
    print(f"输出文件: {output_csv}")
    print("=" * 80)
    
    valid_rows = []
    
    try:
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            stats['total'] = len(rows)
            
            print(f"总共 {stats['total']} 条数据，开始过滤...\n")
            
            # 使用tqdm显示进度
            for row in tqdm(rows, desc="处理进度", unit="对"):
                target_path = row['target_image_path']
                source_path = row['source_image_path']
                
                # 检查target图片
                target_valid, target_reason = check_image_valid(target_path)
                if not target_valid:
                    stats['filtered'] += 1
                    reason = f"目标图片{target_reason}"
                    stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1
                    continue
                
                # 检查source图片
                source_valid, source_reason = check_image_valid(source_path)
                if not source_valid:
                    stats['filtered'] += 1
                    reason = f"源图片{source_reason}"
                    stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1
                    continue
                
                # 两张图片都有效，保留
                valid_rows.append(row)
                stats['valid'] += 1
        
        # 写入过滤后的CSV
        if valid_rows:
            with open(output_csv, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
                writer.writeheader()
                writer.writerows(valid_rows)
            print(f"\n✓ 已写入 {len(valid_rows)} 条有效数据到 {output_csv}")
        else:
            print("\n⚠ 警告: 没有有效数据！")
    
    except FileNotFoundError:
        print(f"\n✗ 错误: 找不到输入文件 {input_csv}")
        return
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        return
    
    # 生成报告
    generate_report(stats, input_csv, output_csv)


def generate_report(stats: Dict, input_csv: str, output_csv: str):
    """
    生成并显示过滤报告
    """
    report_lines = []
    report_lines.append("\n" + "=" * 80)
    report_lines.append("图片对过滤报告")
    report_lines.append("=" * 80)
    report_lines.append(f"处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"输入文件: {input_csv}")
    report_lines.append(f"输出文件: {output_csv}")
    report_lines.append("-" * 80)
    report_lines.append(f"总数据量:     {stats['total']:>10,} 对")
    report_lines.append(f"保留数据:     {stats['valid']:>10,} 对 ({stats['valid']/stats['total']*100:.2f}%)" if stats['total'] > 0 else "保留数据:     0 对")
    report_lines.append(f"过滤数据:     {stats['filtered']:>10,} 对 ({stats['filtered']/stats['total']*100:.2f}%)" if stats['total'] > 0 else "过滤数据:     0 对")
    report_lines.append("-" * 80)
    report_lines.append("过滤原因统计:")
    
    # 按过滤数量排序
    sorted_reasons = sorted(stats['reasons'].items(), key=lambda x: x[1], reverse=True)
    for reason, count in sorted_reasons:
        percentage = count / stats['total'] * 100 if stats['total'] > 0 else 0
        report_lines.append(f"  - {reason:<30} {count:>8,} 对 ({percentage:.2f}%)")
    
    report_lines.append("=" * 80)
    
    # 显示到终端
    report_text = "\n".join(report_lines)
    print(report_text)
    
    # 保存到文件
    report_file = str(Path(output_csv).parent / f"{Path(output_csv).stem}_report.txt")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n报告已保存到: {report_file}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python filter_image_pairs.py <input_csv> [output_csv]")
        print("\n示例:")
        print("  python filter_image_pairs.py data.csv")
        print("  python filter_image_pairs.py data.csv filtered_data.csv")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else None
    
    process_csv(input_csv, output_csv)
