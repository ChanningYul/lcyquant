#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
沪深A股全量历史数据下载脚本
支持命令行参数指定日期范围，默认下载近70个交易日数据
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import time
import json
import argparse
import logging
from typing import List, Tuple, Optional
from tqdm import tqdm
import warnings

# 忽略一些不重要的警告
warnings.filterwarnings('ignore')

# 添加xtquant路径
xtquant_path = Path(__file__).parent / "xtquant"
if xtquant_path.exists():
    sys.path.insert(0, str(xtquant_path))

from xtquant import xtdata

# 配置日志
def setup_logging(log_file: str = "log/download_all_stocks.log"):
    """配置日志（输出到stderr，避免干扰进度条）"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stderr)  # 输出到stderr
        ]
    )
    return logging.getLogger(__name__)

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='下载沪深A股全量历史数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python download_all_stocks.py                          # 下载近70个交易日数据（启用智能增量）
  python download_all_stocks.py --start 20240101 --end 20241231  # 指定日期范围
  python download_all_stocks.py --days 30               # 下载近30个交易日数据
  python download_all_stocks.py --resume                # 断点续传（从上次中断的地方继续）
  python download_all_stocks.py --no-smart-increment    # 禁用智能增量，每次完整下载

智能增量更新说明：
  - 默认启用智能增量更新，会自动检测本地数据，只下载缺失的部分
  - 第一次运行时下载完整历史数据
  - 后续运行只下载新产生的数据，大大节省时间
        """
    )

    parser.add_argument('--start', type=str, help='开始日期，格式：YYYYMMDD（例如：20240101）')
    parser.add_argument('--end', type=str, help='结束日期，格式：YYYYMMDD（例如：20241231）')
    parser.add_argument('--days', type=int, help='近N个交易日数据（默认70）')
    parser.add_argument('--period', type=str, default='1d', help='数据周期：1m, 5m, 15m, 30m, 1h, 1d（默认：1d）')
    parser.add_argument('--resume', action='store_true', help='断点续传模式')
    parser.add_argument('--retry', type=int, default=3, help='下载失败重试次数（默认3次）')
    parser.add_argument('--delay', type=float, default=0.1, help='下载间隔秒数（默认0.1秒）')
    parser.add_argument('--batch-size', type=int, default=50, help='每批次下载股票数量（默认50）')
    parser.add_argument('--log-file', type=str, default='download_all_stocks.log', help='日志文件名')
    parser.add_argument('--smart-increment', action='store_true', default=True,
                        help='启用智能增量更新（自动检测本地数据，仅下载缺失部分，默认启用）')
    parser.add_argument('--no-smart-increment', action='store_false', dest='smart_increment',
                        help='禁用智能增量更新，每次都完整下载')

    return parser.parse_args()

def connect_qmt(logger) -> bool:
    """连接QMT"""
    logger.info("正在连接QMT...")

    # 常见的QMT端口和IP
    ports_to_try = [None, 6166, 9999, 7777]
    ips_to_try = ['', '127.0.0.1', 'localhost']

    for ip in ips_to_try:
        for port in ports_to_try:
            try:
                logger.info(f"尝试连接: ip={ip if ip else '默认'}, port={port if port else '默认'}")
                xtdata.connect(ip, port)
                logger.info("✓ 连接成功！")
                return True
            except Exception as e:
                logger.debug(f"连接失败: {str(e)[:80]}")
                continue

    logger.error("连接QMT失败！请检查：")
    logger.error("1. QMT客户端是否完全启动并登录？")
    logger.error("2. QMT版本是否为专业版或极简版？")
    logger.error("3. 是否以管理员权限运行QMT？")
    return False

def get_trading_days_count(days: int, logger) -> Tuple[str, str]:
    """计算近N个交易日的日期范围"""
    logger.info(f"计算近{days}个交易日的日期范围...")

    # 获取交易日历（使用指数代替）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days * 2)  # 多取一些天数，后面会过滤

    end_str = end_date.strftime("%Y%m%d")
    start_str = start_date.strftime("%Y%m%d")

    logger.info(f"初始日期范围：{start_str} 到 {end_str}")

    # 尝试获取交易日数据来验证
    try:
        # 使用上证指数来获取交易日信息
        test_symbol = "000001.SH"
        data = xtdata.get_market_data([test_symbol], ["1d"], start_time=start_str, end_time=end_str)

        if test_symbol in data and len(data[test_symbol]) > 0:
            df = data[test_symbol]
            if len(df) >= days:
                # 取最后days条数据
                actual_start = df.index[-days]
                start_str = actual_start.strftime("%Y%m%d")
                logger.info(f"基于实际交易日计算：{start_str} 到 {end_str}（共{len(df)}个交易日）")
    except Exception as e:
        logger.warning(f"无法验证交易日历，使用估算日期：{e}")

    return start_str, end_str

def get_all_a_stocks(logger) -> List[Tuple[str, str]]:
    """获取沪深A股所有股票列表"""
    logger.info("正在获取沪深A股股票列表...")

    try:
        # 获取股票列表
        stock_list = xtdata.get_stock_list_in_sector('沪深A股')

        if not stock_list:
            logger.error("未获取到股票列表！")
            return []

        logger.info(f"✓ 获取到 {len(stock_list)} 只股票")

        # 转换为 (代码, 名称) 格式
        stocks = [(code, code) for code in stock_list]

        return stocks

    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return []

def load_downloaded_stocks(resume_file: str, logger) -> set:
    """加载已下载的股票列表（断点续传）"""
    if not Path(resume_file).exists():
        return set()

    try:
        with open(resume_file, 'r', encoding='utf-8') as f:
            downloaded = json.load(f)
            logger.info(f"加载断点续传文件：已下载 {len(downloaded)} 只股票")
            return set(downloaded)
    except Exception as e:
        logger.warning(f"加载断点续传文件失败: {e}")
        return set()

def save_downloaded_stocks(downloaded_stocks: set, resume_file: str):
    """保存已下载的股票列表"""
    try:
        with open(resume_file, 'w', encoding='utf-8') as f:
            json.dump(list(downloaded_stocks), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存断点续传文件失败: {e}")

def get_latest_data_date(symbol: str, period: str, logger) -> Optional[str]:
    """获取本地数据的最新日期"""
    try:
        # 获取最近的数据（获取close字段，因为time字段可能不是所有周期都有）
        # 对于1d周期，close字段一定有数据
        fields = ['close'] if period == '1d' else ['time', 'close']
        data = xtdata.get_market_data(
            field_list=fields,
            stock_list=[symbol],
            period=period,
            count=1  # 只获取最新1条记录
        )

        # xtdata.get_market_data 返回格式是 {field: DataFrame}
        # DataFrame 的 index 是 stock_list，columns 是 time_list
        if 'close' in data:
            df = data['close']
            if symbol in df.index and len(df.columns) > 0:
                # 获取该股票的数据
                stock_data = df.loc[symbol]
                # 获取最新的时间列
                latest_timestamp = stock_data.index[-1]  # 最新的时间戳
                # 转换为日期字符串格式 (YYYYMMDD)
                latest_date = datetime.fromtimestamp(latest_timestamp / 1000).strftime('%Y%m%d')
                logger.debug(f"{symbol} 本地最新数据日期: {latest_date}")
                return latest_date
        return None
    except Exception as e:
        logger.debug(f"获取 {symbol} 本地数据日期失败: {str(e)[:80]}")
        return None

def download_stock_data_no_increment(symbol: str, start_date: str, end_date: str, period: str, retry: int, logger) -> bool:
    """下载单只股票数据（传统方式，不使用增量下载）"""
    for attempt in range(retry):
        try:
            xtdata.download_history_data(symbol, period, start_time=start_date, end_time=end_date)
            return True
        except Exception as e:
            if attempt < retry - 1:
                time.sleep(1)  # 等待1秒后重试
                logger.debug(f"{symbol} 下载失败，重试 {attempt + 1}/{retry}: {str(e)[:80]}")
            else:
                logger.warning(f"{symbol} 下载最终失败: {str(e)[:80]}")
    return False

def download_stock_data(symbol: str, start_date: str, end_date: str, period: str, retry: int, logger) -> str:
    """
    下载单只股票数据（智能增量更新）
    返回值：
      - 'skipped': 数据已是最新，跳过下载
      - True: 下载成功
      - False: 下载失败
    """
    for attempt in range(retry):
        try:
            # 检查本地是否已有数据
            latest_date = get_latest_data_date(symbol, period, logger)

            if latest_date:
                # 本地已有数据，计算需要增量下载的起始日期
                latest_date_obj = datetime.strptime(latest_date, '%Y%m%d')
                next_day = latest_date_obj + timedelta(days=1)
                start_time = next_day.strftime('%Y%m%d')

                # 检查是否需要下载（如果最新日期已经晚于等于目标日期，则跳过）
                target_date_obj = datetime.strptime(end_date, '%Y%m%d')

                if start_time > end_date:
                    # 数据已是最新，跳过下载
                    return 'skipped'
                else:
                    # 增量下载
                    xtdata.download_history_data(symbol, period, start_time=start_time, end_time=end_date)
            else:
                # 本地无数据，完整下载
                xtdata.download_history_data(symbol, period, start_time=start_date, end_time=end_date)

            return True
        except Exception as e:
            if attempt < retry - 1:
                time.sleep(1)  # 等待1秒后重试
                logger.debug(f"{symbol} 下载失败，重试 {attempt + 1}/{retry}: {str(e)[:80]}")
            else:
                logger.warning(f"{symbol} 下载最终失败: {str(e)[:80]}")
    return False

def check_connection(logger) -> bool:
    """检查QMT连接状态"""
    try:
        # 尝试获取一个简单的数据来验证连接
        xtdata.get_stock_list_in_sector('沪深A股')
        return True
    except Exception as e:
        logger.warning(f"QMT连接断开: {e}")
        return False

def reconnect_qmt(logger) -> bool:
    """重新连接QMT"""
    # 直接使用print输出到stderr，避免使用logger干扰进度条
    print("尝试重新连接QMT...", file=sys.stderr, flush=True)
    try:
        xtdata.disconnect()
    except:
        pass

    time.sleep(2)
    return connect_qmt(logger)

def download_all_stocks_process(stocks: List[Tuple[str, str]], start_date: str, end_date: str,
                               period: str, retry: int, delay: float,
                               downloaded_stocks: set, resume_file: str, smart_increment: bool, logger):
    """下载所有股票数据（无批次处理）"""

    # 创建进度条（输出到stderr，确保在同一行刷新）
    pbar = tqdm(total=len(stocks), desc="下载进度", unit="只股票",
                file=sys.stderr, ncols=100, dynamic_ncols=True)

    success_count = 0
    fail_count = 0
    skip_count = 0
    already_count = 0  # 新增：已有数据且无需更新的数量

    for symbol, name in stocks:
        # 跳过已下载的股票（断点续传）
        if symbol in downloaded_stocks:
            already_count += 1
            pbar.set_postfix({
                '成功': success_count,
                '失败': fail_count,
                '跳过': skip_count,
                '已有': already_count
            })
            pbar.update(1)
            continue

        # 检查连接状态（静默处理，不输出到stdout）
        if not check_connection(logger):
            # 输出到stderr
            print("QMT连接断开，尝试重连...", file=sys.stderr, flush=True)
            if reconnect_qmt(logger):
                print("重连成功", file=sys.stderr, flush=True)
            else:
                print("重连失败，保存进度并退出", file=sys.stderr, flush=True)
                save_downloaded_stocks(downloaded_stocks, resume_file)
                return

        # 下载数据
        if smart_increment:
            # 使用智能增量下载
            result = download_stock_data(symbol, start_date, end_date, period, retry, logger)
            if result == 'skipped':
                # 数据已是最新，跳过下载
                skip_count += 1
                # 将其添加到 downloaded_stocks，避免重复检测
                downloaded_stocks.add(symbol)
            elif result:
                downloaded_stocks.add(symbol)
                success_count += 1
            else:
                fail_count += 1
        else:
            # 使用传统方式（完整下载）
            if download_stock_data_no_increment(symbol, start_date, end_date, period, retry, logger):
                downloaded_stocks.add(symbol)
                success_count += 1
            else:
                fail_count += 1

        # 更新进度条并显示当前状态
        pbar.set_postfix({
            '成功': success_count,
            '失败': fail_count,
            '跳过': skip_count,
            '已有': already_count
        })
        pbar.update(1)

        # 延迟
        time.sleep(delay)

        # 每处理一定数量后保存进度
        if (success_count + fail_count + skip_count) % 100 == 0:
            save_downloaded_stocks(downloaded_stocks, resume_file)

    pbar.close()

    # 显示最终结果（输出到stderr）
    print("\n" + "="*80, file=sys.stderr)
    print("下载完成！", file=sys.stderr)
    print(f"总股票数: {len(stocks)}", file=sys.stderr)
    print(f"成功下载: {success_count}", file=sys.stderr)
    print(f"下载失败: {fail_count}", file=sys.stderr)
    print(f"跳过下载: {skip_count}", file=sys.stderr)
    print(f"已有数据: {already_count}", file=sys.stderr)
    print("="*80, file=sys.stderr)

def main():
    """主函数"""
    # 解析命令行参数
    args = parse_arguments()

    # 设置日志
    logger = setup_logging(args.log_file)

    logger.info("="*60)
    logger.info("沪深A股全量历史数据下载工具")
    logger.info("="*60)
    logger.info(f"日志文件: {args.log_file}")

    # 连接QMT
    if not connect_qmt(logger):
        return

    try:
        # 计算日期范围
        if args.start and args.end:
            start_date = args.start
            end_date = args.end
            logger.info(f"使用指定日期范围: {start_date} 到 {end_date}")
        elif args.days:
            start_date, end_date = get_trading_days_count(args.days, logger)
        else:
            start_date, end_date = get_trading_days_count(70, logger)

        logger.info(f"日期范围: {start_date} 到 {end_date}")
        logger.info(f"数据周期: {args.period}")
        logger.info(f"重试次数: {args.retry}")
        logger.info(f"下载间隔: {args.delay}秒")
        logger.info(f"智能增量更新: {'启用' if args.smart_increment else '禁用'}")

        # 加载已下载股票列表（总是加载，支持智能增量）
        resume_file = "downloaded_stocks.json"
        downloaded_stocks = load_downloaded_stocks(resume_file, logger)
        logger.info(f"已加载已下载股票列表: {len(downloaded_stocks)} 只")

        # 获取股票列表
        stocks = get_all_a_stocks(logger)
        if not stocks:
            logger.error("未能获取股票列表，退出")
            return

        logger.info(f"总股票数量: {len(stocks)}")

        if len(stocks) == 0:
            logger.info("没有股票需要处理！")
            return

        # 开始下载（不再分批次）
        download_all_stocks_process(
            stocks, start_date, end_date, args.period,
            args.retry, args.delay,
            downloaded_stocks, resume_file, args.smart_increment, logger
        )

    except KeyboardInterrupt:
        logger.info("\n\n下载被用户中断")
        logger.info("已下载的进度已保存，下次可使用 --resume 参数继续")
    except Exception as e:
        logger.error(f"\n下载过程中出现错误: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # 断开连接
        try:
            xtdata.disconnect()
            logger.info("已断开QMT连接")
        except:
            pass

if __name__ == "__main__":
    main()
