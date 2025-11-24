import csv
import os
import sys
import argparse
from PIL import Image
from tqdm import tqdm
import time
import multiprocessing

# ================= 配置区域 =================
# 在这里修改过滤参数

# 允许的图片格式 (Pillow format names)
ALLOWED_FORMATS = {'JPEG', 'PNG'}

# 长宽比限制 (宽/高)
MIN_ASPECT_RATIO = 1.0 / 2.5
MAX_ASPECT_RATIO = 2.5 / 1.0

# 尺寸限制 (像素)
MAX_SHORT_EDGE = 2400
MAX_LONG_EDGE = 3600

# 默认并发进程数
DEFAULT_NUM_PROCESSES = 20

# 输入CSV文件的路径 (默认值)
DEFAULT_INPUT_CSV = 'data.csv'

# ===========================================

def get_image_info(image_path):
    """
    获取图片信息。
    返回: (is_valid, reason)
    """
    if not os.path.exists(image_path):
        return False, "文件不存在"
    
    try:
        # Image.open 是懒加载的，只读取文件头获取 meta 信息
        with Image.open(image_path) as img:
            # 1. 检查格式
            if img.format not in ALLOWED_FORMATS:
                return False, f"格式不支持({img.format})"
            
            width, height = img.size
            
            # 2. 检查尺寸
            short_edge = min(width, height)
            long_edge = max(width, height)
            
            if short_edge > MAX_SHORT_EDGE:
                return False, f"短边超限({short_edge}>{MAX_SHORT_EDGE})"
            
            if long_edge > MAX_LONG_EDGE:
                return False, f"长边超限({long_edge}>{MAX_LONG_EDGE})"
            
            # 3. 检查长宽比
            aspect_ratio = width / height
            if not (MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO):
                return False, f"长宽比超限({aspect_ratio:.2f})"
            
            return True, None
            
    except (IOError, SyntaxError) as e:
        return False, f"文件损坏或无法读取: {str(e)}"
    except Exception as e:
        return False, f"未知错误: {str(e)}"

def check_row(row):
    """
    Worker 进程执行的函数。
    接收一行数据，返回 (row, is_kept, reason)
    """
    target_path = row['target_image_path']
    source_path = row['source_image_path']
    
    # 检查 target image
    t_valid, t_reason = get_image_info(target_path)
    if not t_valid:
        return row, False, f"Target: {t_reason}"
        
    # 检查 source image
    s_valid, s_reason = get_image_info(source_path)
    if not s_valid:
        return row, False, f"Source: {s_reason}"
    
    return row, True, None

def process_csv(input_file, num_processes):
    if not os.path.exists(input_file):
        print(f"错误: 输入文件 '{input_file}' 不存在。")
        return

    file_dir = os.path.dirname(os.path.abspath(input_file))
    file_name = os.path.basename(input_file)
    name_part, ext_part = os.path.splitext(file_name)
    
    output_csv_path = os.path.join(file_dir, f"{name_part}_filtered{ext_part}")
    report_path = os.path.join(file_dir, f"{name_part}_report.txt")

    print(f"正在处理文件: {input_file}")
    print(f"并发进程数: {num_processes}")
    print(f"输出文件将在: {output_csv_path}")
    print("-" * 50)

    stats = {
        'total': 0,
        'kept': 0,
        'filtered': 0,
        'reasons': {}
    }

    start_time = time.time()

    # 计算总行数
    print("正在预扫描计算行数...")
    total_lines = 0
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            total_lines = sum(1 for _ in f) - 1
    except Exception as e:
        print(f"无法读取文件行数: {e}")
        return
    
    print(f"总行数: {total_lines}")

    # 增加字段大小限制
    csv.field_size_limit(sys.maxsize)

    with open(input_file, 'r', encoding='utf-8', newline='') as f_in, \
         open(output_csv_path, 'w', encoding='utf-8', newline='') as f_out:
        
        reader = csv.DictReader(f_in)
        
        required_cols = ['target_image_path', 'source_image_path']
        if not all(col in reader.fieldnames for col in required_cols):
            print(f"错误: CSV缺少必要的列: {required_cols}")
            return

        writer = csv.DictWriter(f_out, fieldnames=reader.fieldnames)
        writer.writeheader()

        # 使用 multiprocessing.Pool 进行并发处理
        # chunksize 设为 100 或更大可以减少进程间通信开销
        with multiprocessing.Pool(processes=num_processes) as pool:
            # imap 保持顺序，并且是惰性求值的，内存友好
            result_iter = pool.imap(check_row, reader, chunksize=100)
            
            for row, is_kept, reason in tqdm(result_iter, total=total_lines, unit="pair", desc="多进程处理中"):
                stats['total'] += 1
                
                if is_kept:
                    stats['kept'] += 1
                    writer.writerow(row)
                else:
                    stats['filtered'] += 1
                    stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1

    end_time = time.time()
    duration = end_time - start_time

    # 生成报告
    report_lines = []
    report_lines.append("=" * 30)
    report_lines.append(f"处理报告: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("=" * 30)
    report_lines.append(f"输入文件: {input_file}")
    report_lines.append(f"并发数: {num_processes}")
    report_lines.append(f"耗时: {duration:.2f} 秒")
    if duration > 0:
        report_lines.append(f"处理速度: {stats['total']/duration:.1f} pairs/sec")
    report_lines.append("-" * 30)
    report_lines.append(f"总数据量: {stats['total']}")
    if stats['total'] > 0:
        report_lines.append(f"保留数据: {stats['kept']} ({stats['kept']/stats['total']*100:.2f}%)")
    else:
        report_lines.append("保留数据: 0")
    report_lines.append(f"过滤数据: {stats['filtered']}")
    report_lines.append("-" * 30)
    report_lines.append("过滤原因统计:")
    
    sorted_reasons = sorted(stats['reasons'].items(), key=lambda item: item[1], reverse=True)
    for reason, count in sorted_reasons:
        report_lines.append(f"  - {reason}: {count}")
    
    report_content = "\n".join(report_lines)
    
    print("\n" + report_content)
    
    with open(report_path, 'w', encoding='utf-8') as f_rep:
        f_rep.write(report_content)
    
    print(f"\n报告已保存至: {report_path}")

if __name__ == "__main__":
    # 必须加上这行，防止多进程在某些系统下递归启动
    multiprocessing.freeze_support()
    
    parser = argparse.ArgumentParser(description='多进程过滤图片对CSV脚本')
    parser.add_argument('csv_file', nargs='?', default=DEFAULT_INPUT_CSV, 
                        help=f'CSV文件路径 (默认: {DEFAULT_INPUT_CSV})')
    parser.add_argument('--workers', type=int, default=DEFAULT_NUM_PROCESSES,
                        help=f'并发进程数 (默认: {DEFAULT_NUM_PROCESSES})')
    
    args = parser.parse_args()
    process_csv(args.csv_file, args.workers)
