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
import pandas as pd

# 添加xtquant路径
xtquant_path = Path(__file__).parent / "xtquant"
if xtquant_path.exists():
    sys.path.insert(0, str(xtquant_path))

# 导入工具函数
from util.functools import is_trading_day

# 创建输出目录
log_dir = Path("log")
temp_dir = Path("temp")
log_dir.mkdir(exist_ok=True)
temp_dir.mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'select.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('StockSelector')

# 配置文件路径
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)
CANDIDATE_FILE = data_dir / "candidate.json"
SELECT_LOG = log_dir / "select_detail.log"


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
        self.trading_calendar = []  # 交易日历
        # 从配置文件读取参数
        try:
            from select_config import PARAMS
            self.params = PARAMS.copy()
        except ImportError:
            # 如果配置文件不存在，使用默认值
            logger.warning("select_config.py 不存在，使用默认参数")
            self.params = {
                'limit_ratio_main': 0.10,  # 沪深A股涨停幅度
                'limit_ratio_special': 0.20,  # 创业板涨停幅度
                'limit_ratio_bj': 0.30,  # 北交所涨停幅度
                'max_price': 200.0,  # 最大持仓价格
                'drawdown_limit': 0.15,  # 最大回撤率（默认15%）
                'stop_profit': 0.10,  # 止盈比例
                'stop_loss': -0.02,  # 止损比例
                'seal_circ_ratio': 0.000003,  # 封单对流通市值占比
                'seal_turnover_ratio': 2.0,  # 封单占成交额倍数
                'enable_seal_filter': True,  # 是否启用封单金额筛选
            }

    def init_data(self):
        """初始化数据：获取股票列表和交易日历"""
        logger.info("开始初始化数据...")

        try:
            # 使用xtQuant接口获取股票列表
            from xtquant import xtdata

            # 尝试获取股票列表
            try:
                self.stock_list = xtdata.get_stock_list_in_sector('沪深A股')
                logger.info(f"获取到 {len(self.stock_list)} 只股票")
            except (AssertionError, Exception) as e:
                # BSON错误处理
                error_msg = str(e)[:100]
                logger.error(f"BSON错误，无法获取股票列表: {error_msg}")
                raise

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
            raise

    def filter_basic_criteria(self) -> List[str]:
        """
        基础过滤：剔除ST、北交所、创业板、科创板、次新股、高价股、停牌股票
        """
        logger.info("开始基础过滤...")

        # 批量获取停牌状态
        suspended_stocks = set()
        try:
            from xtquant import xtdata
            # 获取所有股票的最近1条日线数据的suspendFlag
            # suspendFlag: 0-正常, 1-停牌
            data = xtdata.get_market_data(
                field_list=['suspendFlag'],
                stock_list=self.stock_list,
                period='1d',
                count=1
            )
            if 'suspendFlag' in data:
                df = data['suspendFlag']
                if not df.empty:
                    # 获取最后一列（最新日期）
                    last_col = df.iloc[:, -1]
                    # 找出值为1（停牌）的股票
                    suspended_stocks = set(last_col[last_col == 1].index)
                    logger.info(f"识别出 {len(suspended_stocks)} 只停牌股票")
        except Exception as e:
            logger.warning(f"获取停牌状态失败: {e}")

        valid_stocks = []

        for code in self.stock_list:
            try:
                # 0. 剔除停牌
                if code in suspended_stocks:
                    continue

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
        """获取股票名称"""
        try:
            # 尝试通过xtdata获取真实股票名称
            from xtquant import xtdata
            try:
                # 获取股票详细信息
                info = xtdata.get_instrument_detail(code)
                if info and 'InstrumentName' in info:
                    return info['InstrumentName']
                # 如果没有InstrumentName，尝试其他可能的字段
                for key in ['name', 'shortName', 'abbr']:
                    if key in info and info[key]:
                        return info[key]
            except Exception as e:
                logger.debug(f"获取 {code} 股票名称失败: {e}")

            # 如果获取失败，返回默认名称
            return code

        except Exception as e:
            logger.warning(f"获取股票名称异常 {code}: {e}")
            return code

    def is_before_trading_time(self) -> bool:
        """
        判断当前是否在9:30之前（交易时间前）
        True: 交易前（早于9:30），需要使用前3个交易日数据判断涨停
        False: 交易时间或收盘后，使用前2个交易日+当日数据判断涨停
        """
        now = datetime.datetime.now()
        # 交易时间：9:30-15:00
        start_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        end_time = now.replace(hour=15, minute=0, second=0, microsecond=0)

        # 如果在交易时间前（早于9:30），返回True
        # 如果在交易时间或收盘后（9:30-24:00），返回False
        return now < start_time

    def get_trading_dates(self, count: int) -> List[str]:
        """
        根据当前时间获取需要的交易日
        交易前：返回前N个完整交易日
        交易后：返回前N-1个完整交易日 + 当日
        """
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
        # QMT极简版不支持start_time和end_time参数，使用count参数
        # fill_data=False 直接获取实际交易日数据，不填充周末等非交易日
        logger.info(f"使用count参数直接获取{count}条交易日数据")

        result = {}
        try:
            from xtquant import xtdata

            # 直接使用count参数获取实际交易日数据
            logger.info(f"使用fill_data=False获取数据...股票数量: {len(stock_list)}, 需要的count: {count}")

            try:
                # 批量获取所有股票数据
                data = xtdata.get_market_data_ex(
                    field_list=fields,
                    stock_list=stock_list,
                    period=period,
                    count=count,  # 直接使用传入的count值
                    dividend_type='none',  # 不复权
                    fill_data=False,  # 不填充数据，直接获取实际交易日数据
                )

                """
                # 保存数据到CSV文件
                if data:
                    import pandas as pd
                    all_rows = []
                    for code, df in data.items():
                        if df is not None and len(df) > 0:
                            df_copy = df.copy() if hasattr(df, 'copy') else pd.DataFrame(df)
                            df_copy['code'] = code
                            all_rows.append(df_copy)
                    if all_rows:
                        combined_df = pd.concat(all_rows, ignore_index=True)
                        combined_df.to_csv('stock.csv', index=False, encoding='utf-8')
                        logger.info(f"数据已保存至 stock.csv, 共 {len(combined_df)} 条记录")

                # 调试：检查前两只股票的数据
                for i, code in enumerate(stock_list[:2]):
                    logger.info(f"调试 {code}: data类型={type(data)}, data_keys={list(data.keys())[:5] if data else 'None'}")
                    if data and code in data:
                        df = data[code]
                        logger.info(f"调试 {code}: df类型={type(df)}, df长度={len(df) if hasattr(df, '__len__') else 'N/A'}")
                    else:
                        logger.info(f"调试 {code}: data为空或code不在data中")
                """

                # 过滤非空数据
                if data:
                    for code in stock_list:
                        if code in data and len(data[code]) > 0:
                            result[code] = data[code]

            except AssertionError as e:
                logger.warning(f"BSON错误，批量获取数据失败: {str(e)[:100]}")
            except Exception as e:
                logger.warning(f"批量获取历史数据失败: {e}")

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
        try:
            from xtquant import xtdata
            # 获取最新价格
            data = xtdata.get_market_data(
                field_list=['close'],
                stock_list=[code],
                period='1d',
                count=1
            )
            if 'close' in data and len(data['close']) > 0:
                df = data['close']
                if code in df.index and len(df.columns) > 0:
                    return float(df.iloc[0, -1])
            return 0.0
        except Exception as e:
            logger.warning(f"获取 {code} 当前价格失败: {e}")
            return 0.0

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
                log_selection(f"[涨停判断] {code}: preClose<=0, 跳过")
                return False

            # 1. 基础检查：收盘价必须等于最高价 (未炸板)
            # 当日数据还未收盘，可能炸板，所以放宽条件
            if not is_today:
                if abs(close - high) > 0.01:
                    log_selection(f"[涨停判断] {code}: 炸板 close={close:.2f} != high={high:.2f}, 非涨停")
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
                log_selection(f"[涨停判断] {code}: 涨幅不足 pct={pct:.2%} < threshold={threshold:.2%}, 非涨停")
                return False

            # 涨停确认
            log_selection(f"[涨停判断] {code}: 涨停确认 close={close:.2f}, preClose={pre_close:.2f}, pct={pct:.2%}, limit={limit_ratio:.0%}")
            return True

        except Exception as e:
            logger.warning(f"is_limit_up_bar error {code}: {e}")
            log_selection(f"[涨停判断] {code}: 异常 {e}")
            return False

    def check_drawdown_from_data(self, code: str, df, drawdown_limit: float) -> bool:
        """
        检查涨停前60日最大回撤是否小于限制
        回撤 = (峰值 - 谷值) / 峰值
        返回True表示通过检查（回撤小于限制），返回False表示不通过
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

            # 如果最大回撤超过限制，则剔除
            if max_drawdown > drawdown_limit:
                log_selection(f"剔除 {code}: 60日最大回撤 {max_drawdown:.2%}，高于 {drawdown_limit:.2%}")
                logger.info(f"{code} 回撤检查不通过: {max_drawdown:.2%} > {drawdown_limit:.2%}")
                return False

            # 回撤小于等于限制，通过检查
            log_selection(f"通过 {code}: 60日最大回撤 {max_drawdown:.2%}，低于等于 {drawdown_limit:.2%}")
            logger.info(f"{code} 回撤检查通过: {max_drawdown:.2%} <= {drawdown_limit:.2%}")
            return True

        except Exception as e:
            log_selection(f"回撤计算异常 {code}: {e}")
            logger.error(f"{code} 回撤计算异常: {e}")
            return False

    def filter_by_sell_orders(self, candidates: List[str]) -> List[str]:
        """
        通过Tick数据过滤掉有卖单的股票（非封板）
        卖一量 > 0 表示未封死
        """
        logger.info("开始通过Tick数据过滤未封板股票...")
        if not candidates:
            return []

        final_list = []
        try:
            from xtquant import xtdata
            # 获取全推Tick数据
            ticks = xtdata.get_full_tick(candidates)
            
            for code in candidates:
                if code not in ticks:
                    # 如果获取不到Tick数据，暂且保留
                    final_list.append(code)
                    continue
                    
                tick = ticks[code]
                # 检查卖一量
                # askVol 是一个列表或数组，index 0 为卖一
                has_sell_order = False
                if 'askVol' in tick:
                    ask_vols = tick['askVol']
                    # 确保是列表/数组且长度大于0
                    if hasattr(ask_vols, '__len__') and len(ask_vols) > 0:
                         if ask_vols[0] > 0:
                            has_sell_order = True
                
                if has_sell_order:
                    logger.info(f"剔除 {code}: 存在卖单 (卖一量: {tick['askVol'][0]})")
                else:
                    final_list.append(code)

        except Exception as e:
            logger.error(f"Tick数据过滤失败: {e}")
            return candidates # 发生错误时返回原列表
            
        logger.info(f"Tick过滤完成: {len(candidates)} -> {len(final_list)}")
        return final_list

    def filter_by_seal_amount(self, candidates: List[str]) -> List[str]:
        """
        通过封单金额筛选股票
        条件：
        1. 封单金额 = 盘口卖一档价格 * 盘口卖一档数量
        2. 封单金额 >= 0.03 * 流通市值 AND 封单金额 >= 2 * 当日成交额
        """
        logger.info("开始封单金额筛选...")
        if not candidates:
            return []

        if not self.params.get('enable_seal_filter', True):
            logger.info("封单金额筛选已禁用，跳过")
            return candidates

        final_list = []
        try:
            from xtquant import xtdata

            # 批量获取Tick数据（包含盘口数据）
            logger.info(f"获取 {len(candidates)} 只股票的盘口数据...")
            ticks = xtdata.get_full_tick(candidates)

            for code in candidates:
                if code not in ticks:
                    # 如果获取不到数据，暂且保留
                    final_list.append(code)
                    continue

                tick = ticks[code]

                # 1. 获取盘口数据：买一档价格和数量（涨停股看买一）
                bid1_price = None
                bid1_volume = None

                if 'bidPrice' in tick and 'bidVol' in tick:
                    bid_prices = tick['bidPrice']
                    bid_vols = tick['bidVol']

                    # 确保是列表/数组且长度大于0
                    if (hasattr(bid_prices, '__len__') and len(bid_prices) > 0 and
                        hasattr(bid_vols, '__len__') and len(bid_vols) > 0):
                        bid1_price = bid_prices[0]
                        bid1_volume = bid_vols[0]

                if bid1_price is None or bid1_volume is None:
                    logger.warning(f"{code}: 无法获取盘口数据，跳过封单筛选")
                    final_list.append(code)
                    continue

                # 2. 计算封单金额
                seal_amount = bid1_price * bid1_volume * 100

                # 3. 获取流通市值
                circ_market_value = None

                # 尝试从tick数据获取（如果接口支持）
                if 'circulationValue' in tick:
                    circ_market_value = tick.get('circulationValue')

                # 如果无法直接获取，计算：流通量 * 当日收盘价
                if circ_market_value is None or circ_market_value <= 0:
                    try:
                        # 获取最新日线数据
                        data = xtdata.get_market_data_ex(
                            field_list=['close', 'volume'],
                            stock_list=[code],
                            period='1d',
                            count=1
                        )

                        if code in data and len(data[code]) > 0:
                            df = data[code]
                            close_price = df.iloc[-1]['close']
                            # volume 是总成交量，需要获取流通量
                            # 简化处理：使用总成交量作为近似（实际应使用流通股本）
                            volume = df.iloc[-1]['volume']
                            # 这里做一个简化估算：流通量约为总量的0.3-0.8倍
                            # 实际项目中应该从基本面数据获取准确的流通股本
                            circ_volume = volume * 0.5  # 简化估算
                            circ_market_value = circ_volume * close_price
                    except Exception as e:
                        logger.warning(f"{code}: 获取流通市值失败: {e}")
                        final_list.append(code)
                        continue

                # 4. 获取当日成交额
                turnover_amount = None

                # 尝试从tick数据获取
                if 'turnover' in tick:
                    turnover_amount = tick.get('turnover')

                # 如果tick中没有成交额，从日线数据获取
                if turnover_amount is None or turnover_amount <= 0:
                    try:
                        data = xtdata.get_market_data_ex(
                            field_list=['amount'],
                            stock_list=[code],
                            period='1d',
                            count=1
                        )

                        if code in data and len(data[code]) > 0:
                            df = data[code]
                            # amount字段单位是千元，转换为元
                            turnover_amount = df.iloc[-1]['amount'] * 1000
                    except Exception as e:
                        logger.warning(f"{code}: 获取成交额失败: {e}")
                        final_list.append(code)
                        continue

                # 5. 验证数据有效性
                if (seal_amount <= 0 or circ_market_value <= 0 or turnover_amount <= 0):
                    logger.warning(f"{code}: 数据无效 - 封单金额:{seal_amount:.2f}, 流通市值:{circ_market_value:.2f}, 成交额:{turnover_amount:.2f}")
                    final_list.append(code)
                    continue

                # 6. 计算筛选条件
                seal_circ_threshold = self.params['seal_circ_ratio'] * circ_market_value
                seal_turnover_threshold = self.params['seal_turnover_ratio'] * turnover_amount

                # 判断条件：封单金额 >= 0.03 * 流通市值 AND 封单金额 >= 2 * 当日成交额
                condition1 = seal_amount >= seal_circ_threshold
                condition2 = seal_amount >= seal_turnover_threshold

                if condition1 and condition2:
                    log_selection(f"封单筛选通过 {code}: 封单金额={seal_amount:.0f}, 流通市值占比={seal_amount/circ_market_value:.2%}, 成交额倍数={seal_amount/turnover_amount:.2f}")
                    final_list.append(code)
                else:
                    reason1 = f"封单{seal_amount:.0f} < {self.params['seal_circ_ratio']:.2%}的流通市值{seal_circ_threshold:.0f}" if not condition1 else ""
                    reason2 = f"封单{seal_amount:.0f} < {self.params['seal_turnover_ratio']:.2%}的成交额{seal_turnover_threshold:.0f}" if not condition2 else ""
                    reason = " AND ".join([r for r in [reason1, reason2] if r])
                    logger.info(f"剔除 {code}: {reason}")
                    log_selection(f"封单筛选剔除 {code}: {reason}")

        except Exception as e:
            logger.error(f"封单金额筛选失败: {e}")
            # 发生错误时返回原列表
            return candidates

        logger.info(f"封单金额筛选完成: {len(candidates)} -> {len(final_list)}")
        return final_list

    def run_selection(self) -> Optional[List[str]]:
        """
        执行完整的选股流程
        """
        logger.info("=" * 60)
        logger.info("开始执行选股任务")
        start_time = time.time()

        try:
            # 使用工具函数判断今天是否是交易日
            today_is_trading_day = is_trading_day()
            now = datetime.datetime.now()

            # 判断当前时间段：盘前(9:30前)、盘中(9:30-15:00)、盘后(15:00后)
            is_before_trading_time = now.hour < 9 or (now.hour == 9 and now.minute < 30)
            is_during_trading_time = 9 <= now.hour < 15
            is_after_trading_time = now.hour >= 15

            logger.info(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"今天是交易日: {today_is_trading_day}")
            logger.info(f"盘前时间: {is_before_trading_time}, 盘中时间: {is_during_trading_time}, 盘后时间: {is_after_trading_time}")

            # 1. 基础过滤
            basic_pool = self.filter_basic_criteria()
            if not basic_pool:
                logger.warning("基础过滤后无股票，结束选股")
                return []

            log_selection(f"=== 开始新一轮选股筛选 (候选 {len(basic_pool)} 只) ===")

            # 2. 批量获取60日数据用于涨停判断（统一使用60个交易日数据）
            # 使用fill_data=False直接获取实际交易日数据，避免填充周末等非交易日
            logger.info(f"获取前3个交易日行情数据用于涨停判断...")
            data_3d = self.get_market_data_ex_with_trading_dates(
                fields=['close', 'preClose', 'high', 'amount', 'open'],
                stock_list=basic_pool,
                period='1d',
                count=3  # 使用3个交易日数据
            )
            # 保存3日数据到CSV
            if data_3d:
                all_rows = []
                for code, df in data_3d.items():
                    if df is not None and len(df) > 0:
                        df_copy = df.copy() if hasattr(df, 'copy') else pd.DataFrame(df)
                        df_copy['code'] = code
                        all_rows.append(df_copy)
                if all_rows:
                    pd.concat(all_rows, ignore_index=True).to_csv(data_dir / 'data_3d.csv', index=False)
                    logger.info(f"3日数据已保存至 {data_dir / 'data_3d.csv'}")

            # 3. 初筛涨停股
            logger.info("筛选涨停股...")
            limit_up_candidates = []
            total_stocks = 0
            stocks_with_data = 0

            # 根据时间段确定筛选策略
            for code in basic_pool:
                total_stocks += 1
                if code not in data_3d:
                    continue

                df = data_3d[code]
                stocks_with_data += 1

                # 进行首板筛选
                if today_is_trading_day and is_during_trading_time or is_after_trading_time:
                    is_today_bar = True
                if len(df) >= 3:
                    bar_target = df.iloc[-1]  # 上一个交易日
                    bar_prev_target = df.iloc[-2]  # 上上一个交易日
                    is_today_bar = False

                    if self.is_limit_up_bar(code, bar_target, is_today_bar) and \
                        not self.is_limit_up_bar(code, bar_prev_target, False):
                        limit_up_candidates.append(code)
                        log_selection(f"首板: {code}")

            logger.info(f"统计: 总股票数={total_stocks}, 有数据股票数={stocks_with_data}")

            # 3.1 盘口验证：剔除有卖单的股票（针对首板必须封死）
            if limit_up_candidates:
                limit_up_candidates = self.filter_by_sell_orders(limit_up_candidates)

            # 记录筛选结果
            if today_is_trading_day:
                if is_before_trading_time:
                    logger.info(f"交易日-盘前：上交易日首板筛选结果: {len(limit_up_candidates)} 只")
                elif is_during_trading_time:
                    logger.info(f"交易日-盘中：当日首板筛选结果: {len(limit_up_candidates)} 只")
                else:
                    logger.info(f"交易日-盘后：当日首板筛选结果: {len(limit_up_candidates)} 只")
            else:
                logger.info(f"非交易日：上个交易日首板筛选结果: {len(limit_up_candidates)} 只")

            if limit_up_candidates:
                logger.info(f"涨停股列表: {limit_up_candidates[:10]}")
                # 保存首板股票到firstlimit.csv
                self._save_first_limit_stocks(limit_up_candidates)
            else:
                logger.info("未发现符合条件的涨停股票")

            if not limit_up_candidates:
                if is_before_trading_time:
                    logger.info("上交易日无涨停候选股")
                else:
                    logger.info("当日无涨停候选股")
                # 写入空结果
                self._save_result([])
                return []

            # 4. 获取候选股的60日数据用于回撤计算（使用交易日历）
            logger.info("获取60个交易日行情数据用于回撤计算...")
            data_60d = self.get_market_data_ex_with_trading_dates(
                fields=['high', 'low'],
                stock_list=limit_up_candidates,
                period='1d',
                count=60  # 直接使用60个交易日数据
            )
            # 保存60日数据到CSV
            if data_60d:
                all_rows = []
                for code, df in data_60d.items():
                    if df is not None and len(df) > 0:
                        df_copy = df.copy() if hasattr(df, 'copy') else pd.DataFrame(df)
                        df_copy['code'] = code
                        all_rows.append(df_copy)
                if all_rows:
                    pd.concat(all_rows, ignore_index=True).to_csv(data_dir / 'data_60d.csv', index=False)
                    logger.info(f"60日数据已保存至 {data_dir / 'data_60d.csv'}")
            
            # 5. 回撤检查
            logger.info("回撤检查")
            final_list = []
            rejected_count = 0

            for code in limit_up_candidates:
                if code not in data_60d:
                    rejected_count += 1
                    logger.info(f"{code} 回撤检查剔除: 无60日数据")
                    continue

                df = data_60d[code]
                if not self.check_drawdown_from_data(code, df, self.params['drawdown_limit']):
                    rejected_count += 1
                    continue

                final_list.append(code)

            # 6. 封单金额筛选
            if final_list:
                final_list = self.filter_by_seal_amount(final_list)

            # 7. 可选：高级筛选（L2数据、龙虎榜等）
            # final_list = self._apply_advanced_filters(final_list)

            # 8. 保存结果
            elapsed = time.time() - start_time
            msg = f"筛选完成: 初始 {len(basic_pool)}, 涨停候选 {len(limit_up_candidates)}, 回撤剔除 {rejected_count}, 封单筛选后剩余 {len(final_list)}"
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

            # temp_dir 已在模块顶部创建
            with open(CANDIDATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

            logger.info(f"结果已保存至 {CANDIDATE_FILE}")

        except Exception as e:
            logger.error(f"保存结果失败: {e}")

    def _save_first_limit_stocks(self, stock_codes: List[str]):
        """保存首板股票到firstlimit.csv文件（包含开盘价、收盘价和前一交易日收盘价）"""
        try:
            import csv
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            csv_file = data_dir / "firstlimit.csv"

            logger.info(f"获取首板股票的开盘价、收盘价和前一交易日收盘价...")

            # 判断当前时间，确定要获取哪一天的数据
            now = datetime.datetime.now()
            # 交易时间：9:30-15:00
            start_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
            end_time = now.replace(hour=15, minute=0, second=0, microsecond=0)

            # 如果是盘后时间（15:00之后），使用当日数据；否则使用上个交易日数据
            is_after_trading = now >= end_time
            data_date_desc = "当日" if is_after_trading else "上个交易日"

            logger.info(f"当前时间: {now.strftime('%H:%M:%S')}, 使用{data_date_desc}的开盘价和收盘价")

            # 获取首板股票的开盘价、收盘价和前一交易日收盘价
            stocks_data = []
            price_data = {}

            if stock_codes:
                # 获取2日数据用于获取开盘价、收盘价和前一交易日收盘价
                try:
                    price_data = self.get_market_data_ex_with_trading_dates(
                        fields=['open', 'close', 'preClose'],
                        stock_list=stock_codes,
                        period='1d',
                        count=2  # 获取最新的2天数据（需要前一日的preClose）
                    )
                    logger.info(f"成功获取 {len(price_data)} 只股票的价格数据")
                except Exception as e:
                    logger.warning(f"获取价格数据失败: {e}")

            # 整理数据
            for code in stock_codes:
                name = self.get_stock_name(code)

                # 获取开盘价、收盘价和前一交易日收盘价
                open_price = "-"
                close_price = "-"
                pre_close = "-"

                if code in price_data and len(price_data[code]) > 0:
                    df = price_data[code]
                    # 获取首板当天的数据（最后一条记录）
                    if len(df) >= 1:
                        open_price = df.iloc[-1]['open']
                        close_price = df.iloc[-1]['close']
                        # 保留2位小数
                        open_price = round(open_price, 2) if open_price else "-"
                        close_price = round(close_price, 2) if close_price else "-"

                    # 获取前一交易日的收盘价（preClose字段）
                    if len(df) >= 1:
                        pre_close = df.iloc[-1]['preClose']
                        pre_close = round(pre_close, 2) if pre_close else "-"

                stocks_data.append([code, name, open_price, close_price, pre_close])

            # 保存到CSV文件
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # 写入表头
                writer.writerow(['股票代码', '股票名称', f'{data_date_desc}开盘价', f'{data_date_desc}收盘价', '前一交易日收盘价'])
                # 写入数据
                writer.writerows(stocks_data)

            logger.info(f"首板股票已保存至 {csv_file}，共 {len(stock_codes)} 只，{data_date_desc}价格")

        except Exception as e:
            logger.error(f"保存首板股票失败: {e}", exc_info=True)

    # 以下是需要根据miniQMT实际API实现的方法
    def get_market_data_ex(self, fields: List[str], stock_list: List[str], period: str, count: int) -> Dict:
        """
        批量获取市场数据
        使用xtdata接口获取历史数据
        """
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

                    if data and code in data and len(data[code]) > 0:
                        # 只有非空数据才添加到结果中
                        result[code] = data[code]

                except AssertionError as e:
                    # 处理BSON断言错误
                    logger.warning(f"BSON错误，获取 {code} 数据失败: {str(e)[:100]}")
                    continue
                except Exception as e:
                    logger.warning(f"获取 {code} 历史数据失败: {e}")
                    continue

            logger.info(f"成功获取 {len(result)}/{len(stock_list)} 只股票的历史数据")
            return result

        except Exception as e:
            logger.error(f"获取市场数据失败: {e}")
            raise


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