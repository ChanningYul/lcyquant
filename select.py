#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
选股脚本 (miniQMT版本)
基于原有的QMT内置脚本逻辑迁移
功能：筛选涨停后符合条件的股票，保存至candidate.json
"""

import sys
import os
import time
import json
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Optional

# 添加xtquant路径
xtquant_path = Path(__file__).parent / "xtquant"
if xtquant_path.exists():
    sys.path.insert(0, str(xtquant_path))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('select.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('StockSelector')

# 配置文件路径
CANDIDATE_FILE = "candidate.json"
SELECT_LOG = "select_detail.log"


def log_selection(msg: str):
    """写选股详细日志"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(SELECT_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception as e:
        logger.error(f"日志写入失败: {e}")


class StockSelector:
    """选股器"""

    def __init__(self):
        self.stock_list = []
        self.use_mock_data = False  # 标记是否使用模拟数据
        self.trading_calendar = []  # 交易日历
        self.params = {
            'limit_ratio_main': 0.10,  # 沪深A股涨停幅度
            'limit_ratio_special': 0.20,  # 创业板涨停幅度
            'limit_ratio_bj': 0.30,  # 北交所涨停幅度
            'max_price': 200.0,  # 最大持仓价格
            'drawdown_limit': 0.20,  # 最大回撤率
            'stop_profit': 0.10,  # 止盈比例
            'stop_loss': -0.02,  # 止损比例
            'seal_circ_ratio': 0.03,  # 封单对流通市值占比
            'seal_turnover_ratio': 2.0,  # 封单占成交额倍数
        }

    def init_data(self):
        """初始化数据：获取股票列表和交易日历"""
        logger.info("开始初始化数据...")
        try:
            # 使用xtQuant接口获取股票列表
            # xtdata.get_stock_list_in_sector() 返回股票代码列表
            from xtquant import xtdata
            self.stock_list = xtdata.get_stock_list_in_sector('沪深A股')

            logger.info(f"获取到 {len(self.stock_list)} 只股票")

            # 获取交易日历
            try:
                # 获取上海和深圳的交易日历
                calendar_sh = xtdata.get_trading_calendar('SH')
                calendar_sz = xtdata.get_trading_calendar('SZ')
                # 合并并去重
                self.trading_calendar = sorted(set(calendar_sh + calendar_sz))
                if self.trading_calendar:
                    logger.info(f"获取到 {len(self.trading_calendar)} 个交易日")
                else:
                    logger.warning("交易日历为空")
            except Exception as e:
                logger.warning(f"获取交易日历失败: {e}")

            return True
        except Exception as e:
            logger.error(f"初始化数据失败: {e}")
            logger.warning("尝试使用模拟数据进行测试...")
            return self.init_data_mock()

    def init_data_mock(self):
        """使用模拟数据初始化（用于测试）"""
        logger.info("使用模拟数据初始化...")
        self.use_mock_data = True  # 标记使用模拟数据
        # 生成模拟股票列表
        self.stock_list = []
        # 模拟主板股票
        for i in range(50):
            code = f"{600000 + i:06d}"
            self.stock_list.append(code)
        # 模拟深市股票
        for i in range(50):
            code = f"{1 + i:06d}"
            self.stock_list.append(code)

        logger.info(f"模拟数据: 生成 {len(self.stock_list)} 只股票")
        return True

    def _get_stock_list_fallback(self) -> List[str]:
        """备用股票列表获取方法"""
        # 这里实现备用逻辑，例如从文件读取或使用其他API
        return []

    def filter_basic_criteria(self) -> List[str]:
        """
        基础过滤：剔除ST、北交所、创业板、科创板、次新股、高价股
        """
        logger.info("开始基础过滤...")
        valid_stocks = []

        for code in self.stock_list:
            try:
                # 1. 剔除板块
                if code.startswith('30') or code.startswith('68'):  # 创业板/科创板
                    continue
                if code.startswith('8') or code.startswith('4'):  # 北交所
                    continue

                # 2. 剔除ST
                stock_name = self.get_stock_name(code)
                if 'ST' in stock_name:
                    continue

                # 3. 剔除高价股（如果需要）
                # current_price = self.get_current_price(code)
                # if current_price > self.params['max_price']:
                #     continue

                valid_stocks.append(code)

            except Exception as e:
                logger.warning(f"过滤股票 {code} 时出错: {e}")
                continue

        logger.info(f"基础过滤完成：从 {len(self.stock_list)} 只股票筛选至 {len(valid_stocks)} 只")
        return valid_stocks

    def get_stock_name(self, code: str) -> str:
        """获取股票名称（模拟数据）"""
        return f"股票{code}"

    def is_before_trading_time(self) -> bool:
        """
        判断当前是否在15:00之前（交易时间前）
        True: 交易前，需要使用前3个交易日数据判断涨停
        False: 交易后或收盘后，使用前2个交易日+当日数据判断涨停
        """
        now = datetime.datetime.now()
        cutoff_time = now.replace(hour=15, minute=0, second=0, microsecond=0)
        return now < cutoff_time

    def get_trading_dates(self, count: int) -> List[str]:
        """
        根据当前时间获取需要的交易日
        交易前：返回前N个完整交易日
        交易后：返回前N-1个完整交易日 + 当日
        """
        if self.use_mock_data:
            # 模拟数据模式下，返回模拟日期
            return []

        # 如果有交易日历，使用交易日历
        if self.trading_calendar:
            recent_dates = sorted(self.trading_calendar, reverse=True)
            if self.is_before_trading_time():
                return recent_dates[:count]
            else:
                return recent_dates[:count]
        else:
            # 无法获取交易日历时，使用get_market_last_trade_date
            try:
                from xtquant import xtdata
                import datetime
                # 获取最后交易日
                last_date_sh = xtdata.get_market_last_trade_date('SH')
                last_date_sz = xtdata.get_market_last_trade_date('SZ')
                # 使用较新的日期作为基准
                last_date_ts = max(last_date_sh, last_date_sz)
                # 转换时间戳为datetime对象
                last_date_dt = datetime.datetime.fromtimestamp(last_date_ts / 1000)
                # 生成连续的交易日期（倒推count天）
                trading_dates = []
                current_date = last_date_dt
                for i in range(count):
                    trading_dates.append(current_date.strftime('%Y%m%d'))
                    # 倒推一天
                    current_date = current_date - datetime.timedelta(days=1)
                return trading_dates
            except Exception as e:
                logger.warning(f"无法获取交易日历和最后交易日: {e}")
                return []

    def get_market_data_ex_with_trading_dates(self, fields: List[str], stock_list: List[str],
                                              period: str, count: int) -> Dict:
        """
        根据交易日历获取市场数据（使用交易日期而非自然日期）
        """
        if self.use_mock_data:
            return self.get_market_data_mock(fields, stock_list, period, count)

        # QMT极简版不支持start_time和end_time参数，使用count参数
        # 周六周日市场关闭，需要更多历史数据才能获取到交易日数据
        # 非交易日需要更大的count值以确保获取到最近交易日的数据
        logger.info("使用count参数获取历史数据（非交易日需增加数据量）")

        # 计算调整后的count值
        # 周一需要5天（上周五+周末3天）
        # 周二-周五需要3天
        # 周六-周日需要4天
        now = datetime.datetime.now()
        weekday = now.weekday()  # 0=Monday, 6=Sunday

        if weekday == 0:  # 周一
            adjusted_count = count * 5  # 需要获取上周五及更早的数据
        elif weekday == 5 or weekday == 6:  # 周六或周日
            adjusted_count = count * 4  # 需要获取周五及更早的数据
        else:  # 周二至周五
            adjusted_count = count * 3  # 工作日正常获取

        logger.info(f"当前星期: {now.strftime('%A')}, 调整count: {count} -> {adjusted_count}")

        result = {}
        try:
            from xtquant import xtdata

            # 尝试使用fill_data=True来填充周末的数据
            logger.info("尝试使用fill_data=True获取数据...")

            for code in stock_list:
                try:
                    # xtdata.get_market_data_ex() 返回字典格式数据
                    data = xtdata.get_market_data_ex(
                        field_list=fields,
                        stock_list=[code],
                        period=period,
                        count=adjusted_count,
                        dividend_type='none',  # 不复权
                        fill_data=True,  # 填充数据
                    )

                    if data and code in data:
                        # 转换为DataFrame
                        result[code] = data[code]

                except Exception as e:
                    logger.warning(f"获取 {code} 历史数据失败: {e}")
                    continue

            logger.info(f"成功获取 {len(result)}/{len(stock_list)} 只股票的历史数据")

            # 检查数据质量
            if len(result) > 0:
                # 检查是否有非空数据
                stocks_with_data = sum(1 for df in result.values() if len(df) > 0)
                logger.info(f"其中有数据的股票: {stocks_with_data}/{len(result)}")

                # 如果所有数据都是空的，提示用户
                if stocks_with_data == 0:
                    now = datetime.datetime.now()
                    if now.weekday() >= 5:  # 周六(5)或周日(6)
                        logger.warning("=" * 60)
                        logger.warning("当前是周末，QMT极简版无法获取历史数据")
                        logger.warning("建议：")
                        logger.warning("1. 在工作日运行脚本（周一至周五 9:30-15:00）")
                        logger.warning("2. 或使用模拟数据模式进行测试")
                        logger.warning("=" * 60)

            return result

        except Exception as e:
            logger.error(f"获取市场数据失败: {e}")
            return {}
    def get_current_price(self, code: str) -> float:
        """获取当前价格"""
        # 返回模拟价格
        import random
        return round(random.uniform(5, 100), 2)

    def is_limit_up_bar(self, code: str, bar: Dict, is_today: bool = False) -> bool:
        """
        判断某根K线是否涨停
        is_today: 是否为当日数据（当日数据可能不完整，需要放宽条件）
        """
        try:
            close = bar.get('close', 0)
            pre_close = bar.get('preClose', 0)
            high = bar.get('high', 0)

            if pre_close <= 0:
                return False

            # 1. 基础检查：收盘价必须等于最高价 (未炸板)
            # 当日数据还未收盘，可能炸板，所以放宽条件
            if not is_today:
                if abs(close - high) > 0.01:
                    return False
            else:
                # 当日数据：只要涨幅达到涨停价即可，不要求收盘=最高
                # 但还是要有一定约束
                pass

            # 2. 确定涨停幅度
            limit_ratio = 0.10  # 默认主板 10%
            if code.startswith('30') or code.startswith('68'):
                limit_ratio = 0.20
            elif code.startswith('8') or code.startswith('4'):
                limit_ratio = 0.30

            # 3. 计算涨幅
            pct = (close - pre_close) / pre_close

            # 4. 容差判断（当日数据容差更大）
            threshold = limit_ratio - 0.02 if is_today else limit_ratio - 0.015
            if pct < threshold:
                return False

            return True

        except Exception as e:
            logger.warning(f"is_limit_up_bar error {code}: {e}")
            return False

    def check_drawdown_from_data(self, code: str, df, drawdown_limit: float) -> bool:
        """
        (纯计算) 涨停前 60 日最大回撤＜15%
        """
        try:
            if df is None or len(df) < 60:
                logger.warning(f"{code} 数据不足，跳过回撤检查")
                return False

            # 取涨停前的数据 (剔除最近1天)
            hist_df = df.iloc[:-1]

            # 计算最大回撤
            highs = hist_df['high'].values
            lows = hist_df['low'].values

            max_drawdown = 0.0
            rolling_max = highs[0]

            for i in range(len(highs)):
                if highs[i] > rolling_max:
                    rolling_max = highs[i]

                dd = (rolling_max - lows[i]) / rolling_max
                if dd > max_drawdown:
                    max_drawdown = dd

            is_pass = max_drawdown >= drawdown_limit
            if is_pass:
                log_selection(f"剔除 {code}: 60日最大回撤 {max_drawdown:.2%}，高于 {drawdown_limit:.2%}")
                logger.info(f"{code} 回撤检查不通过: {max_drawdown:.2%} >= {drawdown_limit:.2%}")

            return not is_pass

        except Exception as e:
            log_selection(f"回撤计算异常 {code}: {e}")
            logger.error(f"{code} 回撤计算异常: {e}")
            return False

    def run_selection(self) -> Optional[List[str]]:
        """
        执行完整的选股流程
        """
        logger.info("=" * 60)
        logger.info("开始执行选股任务")
        start_time = time.time()

        try:
            # 1. 基础过滤
            basic_pool = self.filter_basic_criteria()
            if not basic_pool:
                logger.warning("基础过滤后无股票，结束选股")
                return []

            log_selection(f"=== 开始新一轮选股筛选 (候选 {len(basic_pool)} 只) ===")

            # 2. 批量获取N日数据用于涨停判断（根据当前时间动态调整）
            is_before_trading = self.is_before_trading_time()
            logger.info(f"当前时间: {datetime.datetime.now().strftime('%H:%M:%S')}")
            logger.info(f"交易前模式: {is_before_trading}")

            # 动态调整count值
            if is_before_trading:
                # 交易前：需要前3个完整交易日 + 1个前前交易日作为对比 = 4个交易日
                data_count = 4
                logger.info("交易前模式: 筛选上交易日首板（需要4个交易日数据）")
            else:
                # 交易后：需要前2个完整交易日 + 当日 = 3个交易日
                data_count = 3
                logger.info("交易后模式: 筛选当日首板（需要3个交易日数据）")

            logger.info(f"获取{data_count}日行情数据...")
            data_3d = self.get_market_data_ex_with_trading_dates(
                fields=['close', 'preClose', 'high', 'amount', 'open'],
                stock_list=basic_pool,
                period='1d',
                count=data_count
            )

            # 3. 初筛涨停股
            logger.info("筛选涨停股...")
            limit_up_candidates = []
            total_stocks = 0
            stocks_with_data = 0

            for code in basic_pool:
                total_stocks += 1
                if code not in data_3d:
                    continue

                df = data_3d[code]
                # 交易前需要至少4条数据（-3, -2索引），交易后需要至少3条数据（-2索引）
                min_required = 4 if is_before_trading else 3
                if len(df) < min_required:
                    continue

                stocks_with_data += 1

                if is_before_trading:
                    # 交易前（早于15:00）：筛选上一个交易日（bar_prev）的首板
                    # bar_prev 涨停 AND bar_prev_prev 未涨停
                    bar_target = df.iloc[-2]  # 上一个交易日
                    bar_prev_target = df.iloc[-3]  # 上上一个交易日
                    is_today_bar = False

                    if self.is_limit_up_bar(code, bar_target, is_today_bar) and \
                       not self.is_limit_up_bar(code, bar_prev_target, False):
                        limit_up_candidates.append(code)
                        log_selection(f"[交易前] 上交易日首板: {code}")
                else:
                    # 交易后（晚于15:00）：筛选当日（bar_t）的首板
                    # bar_t 涨停 AND bar_prev 未涨停
                    bar_target = df.iloc[-1]  # 当日
                    bar_prev_target = df.iloc[-2]  # 昨日
                    is_today_bar = True

                    if self.is_limit_up_bar(code, bar_target, is_today_bar) and \
                       not self.is_limit_up_bar(code, bar_prev_target, False):
                        limit_up_candidates.append(code)
                        log_selection(f"[交易后] 当日首板: {code}")

            logger.info(f"统计: 总股票数={total_stocks}, 有数据股票数={stocks_with_data}")

            if is_before_trading:
                logger.info(f"上交易日首板筛选结果: {len(limit_up_candidates)} 只")
            else:
                logger.info(f"当日首板筛选结果: {len(limit_up_candidates)} 只")

            if limit_up_candidates:
                logger.info(f"涨停股列表: {limit_up_candidates[:10]}")
            else:
                logger.info("未发现符合条件的涨停股票")

            if not limit_up_candidates:
                if is_before_trading:
                    logger.info("上交易日无涨停候选股")
                else:
                    logger.info("当日无涨停候选股")
                # 写入空结果
                self._save_result([])
                return []

            # 4. 获取候选股的60日数据用于回撤计算（使用交易日历）
            logger.info("获取60日行情数据...")
            data_60d = self.get_market_data_ex_with_trading_dates(
                fields=['high', 'low'],
                stock_list=limit_up_candidates,
                period='1d',
                count=63
            )

            # 5. 回撤检查
            logger.info("执行回撤检查...")
            final_list = []
            rejected_count = 0

            for code in limit_up_candidates:
                if code not in data_60d:
                    rejected_count += 1
                    continue

                df = data_60d[code]
                if not self.check_drawdown_from_data(code, df, self.params['drawdown_limit']):
                    rejected_count += 1
                    continue

                final_list.append(code)
                log_selection(f"入选: {code}")

            # 6. 可选：高级筛选（L2数据、龙虎榜等）
            # final_list = self._apply_advanced_filters(final_list)

            # 7. 保存结果
            elapsed = time.time() - start_time
            msg = f"筛选完成: 初始 {len(basic_pool)}, 涨停候选 {len(limit_up_candidates)}, 剔除 {rejected_count}, 剩余 {len(final_list)}"
            logger.info(msg)
            log_selection(msg)

            self._save_result(final_list)

            logger.info(f"选股完成，耗时: {elapsed:.2f}秒，共选出 {len(final_list)} 只股票")
            logger.info("=" * 60)

            return final_list

        except Exception as e:
            logger.error(f"选股流程异常: {e}", exc_info=True)
            return None

    def _save_result(self, candidates: List[str]):
        """保存结果到JSON文件"""
        try:
            data = {
                "date": datetime.date.today().strftime("%Y-%m-%d"),
                "candidates": candidates,
                "timestamp": time.time(),
                "count": len(candidates)
            }

            os.makedirs(os.path.dirname(CANDIDATE_FILE) if os.path.dirname(CANDIDATE_FILE) else '.', exist_ok=True)
            with open(CANDIDATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

            logger.info(f"结果已保存至 {CANDIDATE_FILE}")

        except Exception as e:
            logger.error(f"保存结果失败: {e}")

    # 以下是需要根据miniQMT实际API实现的方法
    def get_market_data_ex(self, fields: List[str], stock_list: List[str], period: str, count: int) -> Dict:
        """
        批量获取市场数据
        使用xtdata接口获取历史数据
        """
        # 如果是模拟数据模式，直接使用模拟数据
        if self.use_mock_data:
            logger.info(f"模拟数据模式: 直接生成 {len(stock_list)} 只股票的历史数据")
            return self.get_market_data_mock(fields, stock_list, period, count)

        result = {}
        try:
            from xtquant import xtdata

            # 批量获取历史数据
            for code in stock_list:
                try:
                    # xtdata.get_market_data_ex() 返回字典格式数据
                    data = xtdata.get_market_data_ex(
                        field_list=fields,
                        stock_list=[code],
                        period=period,
                        count=count,
                        dividend_type='none',  # 不复权

                    )

                    if data and code in data:
                        # 转换为DataFrame
                        result[code] = data[code]

                except Exception as e:
                    logger.warning(f"获取 {code} 历史数据失败: {e}")
                    continue

            logger.info(f"成功获取 {len(result)}/{len(stock_list)} 只股票的历史数据")
            return result

        except Exception as e:
            logger.warning(f"获取市场数据失败，使用模拟数据: {e}")
            return self.get_market_data_mock(fields, stock_list, period, count)

    def get_market_data_mock(self, fields: List[str], stock_list: List[str],
                            period: str, count: int) -> Dict:
        """生成模拟历史数据"""
        import pandas as pd
        import random
        from datetime import datetime, timedelta

        result = {}
        for code in stock_list:
            # 生成日期序列
            end_date = datetime.now().date()
            dates = [end_date - timedelta(days=i) for i in range(count)]
            dates.reverse()

            # 生成模拟数据
            base_price = random.uniform(10, 100)
            data = []

            for date in dates:
                # 随机游走生成价格
                change = random.uniform(-0.05, 0.05)
                base_price = base_price * (1 + change)

                open_price = base_price + random.uniform(-2, 2)
                high_price = open_price + random.uniform(0, 3)
                low_price = open_price - random.uniform(0, 3)
                close_price = random.uniform(low_price, high_price)
                pre_close = close_price + random.uniform(-1, 1)

                row = {
                    'date': date,
                    'open': round(open_price, 2),
                    'high': round(high_price, 2),
                    'low': round(low_price, 2),
                    'close': round(close_price, 2),
                    'preClose': round(pre_close, 2),
                    'amount': random.uniform(1000000, 10000000),
                }
                data.append(row)

            df = pd.DataFrame(data)
            result[code] = df

        logger.info(f"生成模拟数据: {len(result)} 只股票 x {count} 条记录")
        return result


def main():
    """主函数"""
    logger.info("选股脚本启动")

    # 创建选股器实例
    selector = StockSelector()

    # 初始化数据
    if not selector.init_data():
        logger.error("初始化失败，退出")
        return 1

    # 执行选股
    result = selector.run_selection()

    if result is None:
        logger.error("选股失败")
        return 1

    logger.info(f"选股完成，最终结果: {len(result)} 只股票")
    return 0


if __name__ == '__main__':
    sys.exit(main())