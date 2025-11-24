import csv
import os
import sys
import argparse
from PIL import Image
from tqdm import tqdm
import time

# ================= 配置区域 =================
# 在这里修改过滤参数

# 允许的图片格式 (Pillow format names)
# 常见格式: 'JPEG' (对应 .jpg, .jpeg), 'PNG' (对应 .png)
ALLOWED_FORMATS = {'JPEG', 'PNG'}

# 长宽比限制 (宽/高)
# 限制在 1:2.5 (0.4) 到 2.5:1 (2.5) 之间
MIN_ASPECT_RATIO = 1.0 / 2.5
MAX_ASPECT_RATIO = 2.5 / 1.0

# 尺寸限制 (像素)
# 短边最大值
MAX_SHORT_EDGE = 2400
# 长边最大值
MAX_LONG_EDGE = 3600

# 输入CSV文件的路径 (如果在命令行未提供，将使用此默认值)
DEFAULT_INPUT_CSV = 'data.csv'

# ===========================================

def get_image_info(image_path):
    """
    获取图片信息。
    返回: (is_valid, reason, width, height)
    """
    if not os.path.exists(image_path):
        return False, "文件不存在", 0, 0
    
    try:
        with Image.open(image_path) as img:
            # 1. 检查格式
            if img.format not in ALLOWED_FORMATS:
                return False, f"格式不支持({img.format})", 0, 0
            
            width, height = img.size
            
            # 2. 检查尺寸
            short_edge = min(width, height)
            long_edge = max(width, height)
            
            if short_edge > MAX_SHORT_EDGE:
                return False, f"短边超限({short_edge}>{MAX_SHORT_EDGE})", width, height
            
            if long_edge > MAX_LONG_EDGE:
                return False, f"长边超限({long_edge}>{MAX_LONG_EDGE})", width, height
            
            # 3. 检查长宽比
            aspect_ratio = width / height
            if not (MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO):
                return False, f"长宽比超限({aspect_ratio:.2f})", width, height
            
            return True, None, width, height
            
    except (IOError, SyntaxError) as e:
        return False, f"文件损坏或无法读取: {str(e)}", 0, 0
    except Exception as e:
        return False, f"未知错误: {str(e)}", 0, 0

def process_csv(input_file):
    if not os.path.exists(input_file):
        print(f"错误: 输入文件 '{input_file}' 不存在。")
        return

    file_dir = os.path.dirname(os.path.abspath(input_file))
    file_name = os.path.basename(input_file)
    name_part, ext_part = os.path.splitext(file_name)
    
    output_csv_path = os.path.join(file_dir, f"{name_part}_filtered{ext_part}")
    report_path = os.path.join(file_dir, f"{name_part}_report.txt")

    print(f"正在处理文件: {input_file}")
    print(f"输出文件将在: {output_csv_path}")
    print("-" * 50)

    stats = {
        'total': 0,
        'kept': 0,
        'filtered': 0,
        'reasons': {}
    }

    start_time = time.time()

    # 先计算总行数用于进度条
    total_lines = 0
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            # 减去header
            total_lines = sum(1 for _ in f) - 1
    except Exception as e:
        print(f"无法读取文件行数: {e}")
        return

    # 增加字段大小限制，防止CSV字段过大报错
    csv.field_size_limit(sys.maxsize)

    with open(input_file, 'r', encoding='utf-8', newline='') as f_in, \
         open(output_csv_path, 'w', encoding='utf-8', newline='') as f_out:
        
        reader = csv.DictReader(f_in)
        
        # 检查必要的列
        required_cols = ['target_image_path', 'source_image_path']
        if not all(col in reader.fieldnames for col in required_cols):
            print(f"错误: CSV缺少必要的列: {required_cols}")
            return

        writer = csv.DictWriter(f_out, fieldnames=reader.fieldnames)
        writer.writeheader()

        # 使用 tqdm 显示进度
        for row in tqdm(reader, total=total_lines, unit="pair", desc="处理进度"):
            stats['total'] += 1
            
            target_path = row['target_image_path']
            source_path = row['source_image_path']
            
            # 检查 target image
            t_valid, t_reason, _, _ = get_image_info(target_path)
            if not t_valid:
                stats['filtered'] += 1
                reason = f"Target: {t_reason}"
                stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1
                continue
                
            # 检查 source image
            s_valid, s_reason, _, _ = get_image_info(source_path)
            if not s_valid:
                stats['filtered'] += 1
                reason = f"Source: {s_reason}"
                stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1
                continue
            
            # 通过检查
            stats['kept'] += 1
            writer.writerow(row)

    end_time = time.time()
    duration = end_time - start_time

    # 生成报告
    report_lines = []
    report_lines.append("=" * 30)
    report_lines.append(f"处理报告: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("=" * 30)
    report_lines.append(f"输入文件: {input_file}")
    report_lines.append(f"耗时: {duration:.2f} 秒")
    report_lines.append(f"处理速度: {stats['total']/duration:.1f} pairs/sec")
    report_lines.append("-" * 30)
    report_lines.append(f"总数据量: {stats['total']}")
    report_lines.append(f"保留数据: {stats['kept']} ({stats['kept']/stats['total']*100:.2f}%)" if stats['total'] > 0 else "保留数据: 0")
    report_lines.append(f"过滤数据: {stats['filtered']}")
    report_lines.append("-" * 30)
    report_lines.append("过滤原因统计:")
    
    # 按数量降序排列原因
    sorted_reasons = sorted(stats['reasons'].items(), key=lambda item: item[1], reverse=True)
    for reason, count in sorted_reasons:
        report_lines.append(f"  - {reason}: {count}")
    
    report_content = "\n".join(report_lines)
    
    # 输出到终端
    print("\n" + report_content)
    
    # 输出到文件
    with open(report_path, 'w', encoding='utf-8') as f_rep:
        f_rep.write(report_content)
    
    print(f"\n报告已保存至: {report_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='过滤图片对CSV脚本')
    parser.add_argument('csv_file', nargs='?', default=DEFAULT_INPUT_CSV, 
                        help=f'CSV文件路径 (默认: {DEFAULT_INPUT_CSV})')
    
    args = parser.parse_args()
    process_csv(args.csv_file)
