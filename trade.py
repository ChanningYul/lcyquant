# -*- coding: utf-8 -*-
import datetime
import time

def init(ContextInfo):
    try:
        print(">>> 交易执行模块正在初始化 (init)...")
        # 1. 基础初始化
        ContextInfo.account_id = 'YOUR_ACCOUNT_ID' # 请替换为实际资金账号

        # 2. 策略参数设置
        ContextInfo.params = {
            'stop_profit': 0.10,  # 止盈比例
            'stop_loss': -0.02,   # 止损比例
        }

        # 3. 定时任务设置 (ContextInfo.run_time)
        # 注意：run_time 的 start_time 参数指定"首次运行时间"，配合 period='1d' (1天间隔)，
        # 即可实现从该日期起，每天固定时间重复执行。此处设置一个过去的日期以确保启动即生效。
        start_date = "2023-01-01"

        # 任务1: 晚上挂单 (每天 21:00 启动)
        ContextInfo.run_time("run_night_order_task", "1d", f"{start_date} 21:00:00", "SH")

        # 任务2: 早上校验 (每天 09:25 启动线程)
        ContextInfo.run_time("run_morning_check_task", "1d", f"{start_date} 09:25:00", "SH")

        print("交易执行模块初始化完成")
    except Exception as e:
        print(f"!!! 策略初始化发生严重错误: {e}")

def handlebar(ContextInfo):
    now = time.time()

    # 初始化计时器
    if not hasattr(ContextInfo, 'last_log_time'):
        ContextInfo.last_log_time = 0
    if not hasattr(ContextInfo, 'last_check_time'):
        ContextInfo.last_check_time = 0

    # 每5秒打印一次日志
    if now - ContextInfo.last_log_time >= 5:
        print(f"本条提示每5秒打印1次，但止盈止损判断会每1秒执行1次。")
        ContextInfo.last_log_time = now

    # 每1秒执行一次持仓检查
    if now - ContextInfo.last_check_time >= 1:
        check_holdings(ContextInfo)
        ContextInfo.last_check_time = now

def check_holdings(ContextInfo):
    """
    检查持仓，执行止盈止损
    """
    try:
        # 获取持仓
        positions = []
        if 'get_trade_detail_data' in globals():
            positions = get_trade_detail_data(ContextInfo.account_id, 'stock', 'position')
        elif hasattr(ContextInfo, 'get_trade_detail_data'):
            positions = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'position')

        if not positions:
            return

        for pos in positions:
            code = pos.m_strInstrumentID
            volume = pos.m_nVolume
            can_use_volume = pos.m_nCanUseVolume
            avg_price = pos.m_dOpenPrice # 开仓均价

            if can_use_volume <= 0:
                continue

            # 获取当前行情
            last_tick = ContextInfo.get_full_tick([code])
            if code not in last_tick:
                continue

            curr_price = last_tick[code]['lastPrice']

            # 计算收益率
            if avg_price <= 0: continue
            profit_rate = (curr_price - avg_price) / avg_price

            # 止盈: > 10%
            if profit_rate >= ContextInfo.params['stop_profit']:
                print(f"触发止盈: {code}, 收益率 {profit_rate:.2%}")
                do_sell(ContextInfo, code, curr_price, can_use_volume, "止盈卖出")

            # 止损: < -2%
            elif profit_rate <= ContextInfo.params['stop_loss']:
                print(f"触发止损: {code}, 收益率 {profit_rate:.2%}")
                do_sell(ContextInfo, code, curr_price, can_use_volume, "止损卖出")

    except Exception as e:
        print(f"持仓检查异常: {e}")

def do_sell(ContextInfo, stock_code, price, volume, msg):
    """执行卖出"""
    try:
        print(f"执行卖出: {stock_code}, 价格 {price}, 数量 {volume}, 原因: {msg}")
        if 'pass_order' in globals():
            # 24:卖出, 1101:限价
            pass_order(24, 1101, ContextInfo.account_id, stock_code, 11, price, volume, msg, 2, "", ContextInfo)
        else:
            ContextInfo.sell_stock(stock_code, volume, ContextInfo.account_id)
    except Exception as e:
        print(f"卖出异常: {e}")

def run_night_order_task(ContextInfo):
    """夜间挂单任务（20:30执行）- 为候选股票挂次日涨停价买单"""
    print(f"\n[{datetime.datetime.now()}] === 夜间挂单任务开始 ===")
    try:
        # 1. 读取候选股票列表
        candidate_file = 'data/candidate.json'
        candidates = []
        try:
            import json
            with open(candidate_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                candidates = data.get('candidates', [])
                print(f"读取到 {len(candidates)} 只候选股票")
        except Exception as e:
            print(f"读取候选股票列表失败: {e}")
            return

        if not candidates:
            print("候选股票列表为空，无需挂单")
            return

        # 2. 获取可用资金
        try:
            asset = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'asset')
            if asset:
                available_cash = asset[0].m_dAvailableCash if hasattr(asset[0], 'm_dAvailableCash') else asset[0].m_dEnableBalance
                print(f"可用资金: {available_cash:.2f}")
            else:
                print("获取资金信息失败")
                return
        except Exception as e:
            print(f"获取资金信息异常: {e}")
            return

        # 3. 计算单票仓位（全仓除以候选股票数）
        if len(candidates) > 0:
            position_per_stock = available_cash / len(candidates)
            print(f"单票预算资金: {position_per_stock:.2f}")

        # 4. 为每只候选股票挂涨停价买单
        for stock_code in candidates:
            try:
                # 获取昨日收盘价
                last_close = ContextInfo.get_last_close(stock_code)
                if last_close <= 0:
                    print(f"跳过 {stock_code}: 无法获取昨收价")
                    continue

                # 计算涨停价（根据板块不同，涨停幅度不同）
                if stock_code.startswith('30') or stock_code.startswith('68'):
                    # 创业板/科创板 20%
                    limit_up_price = last_close * 1.20
                elif stock_code.startswith('8') or stock_code.startswith('4'):
                    # 北交所 30%
                    limit_up_price = last_close * 1.30
                else:
                    # 主板 10%
                    limit_up_price = last_close * 1.10

                # 计算买入数量（按涨停价计算）
                volume = int(position_per_stock / limit_up_price / 100) * 100  # 确保是100的整数倍

                if volume <= 0:
                    print(f"跳过 {stock_code}: 计算买入数量为0")
                    continue

                print(f"挂单: {stock_code}, 昨收: {last_close:.2f}, 涨停价: {limit_up_price:.2f}, 数量: {volume}")

                # 挂买单（11是买入）
                if 'pass_order' in globals():
                    # 使用 pass_order 接口
                    pass_order(23, 1101, ContextInfo.account_id, stock_code, 11, limit_up_price, volume,
                              f'夜间挂单-{datetime.datetime.now().strftime("%Y%m%d")}', 2, "", ContextInfo)
                else:
                    # 使用 ContextInfo 的接口
                    ContextInfo.buy_stock(stock_code, volume, ContextInfo.account_id)

            except Exception as e:
                print(f"挂单失败 {stock_code}: {e}")
                continue

        print(f"[{datetime.datetime.now()}] === 夜间挂单任务完成 ===\n")

    except Exception as e:
        print(f"夜间挂单任务异常: {e}")

def run_morning_check_task(ContextInfo):
    """晨间校验任务（09:25执行）- 校验前一晚的挂单是否成功，如失败则补充挂单"""
    print(f"\n[{datetime.datetime.now()}] === 晨间校验任务开始 ===")
    try:
        # 1. 读取候选股票列表
        candidate_file = 'data/candidate.json'
        candidates = []
        try:
            import json
            with open(candidate_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                candidates = data.get('candidates', [])
                print(f"候选股票总数: {len(candidates)} 只")
        except Exception as e:
            print(f"读取候选股票列表失败: {e}")
            return

        if not candidates:
            print("候选股票列表为空，无需校验")
            return

        # 2. 获取当前持仓
        positions = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'position')

        # 3. 获取候选股票在持仓中的情况
        held_stocks = set()
        for pos in positions:
            code = pos.m_strInstrumentID
            volume = pos.m_nVolume
            if volume > 0:
                held_stocks.add(code)

        print(f"当前已持仓股票: {len(held_stocks)} 只")
        print(f"候选股票中已买入: {len(held_stocks.intersection(candidates))} 只")

        # 4. 检查哪些候选股票未成功买入
        not_buied = [code for code in candidates if code not in held_stocks]

        if not not_buied:
            print("✓ 所有候选股票均已成功买入，无需补充挂单")
            print(f"[{datetime.datetime.now()}] === 晨间校验任务完成 ===\n")
            return

        print(f"\n⚠ 发现 {len(not_buied)} 只候选股票未成功买入，将补充挂单:")
        for code in not_buied:
            print(f"  - {code}")

        # 5. 获取可用资金
        try:
            asset = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'asset')
            if asset:
                available_cash = asset[0].m_dAvailableCash if hasattr(asset[0], 'm_dAvailableCash') else asset[0].m_dEnableBalance
                print(f"\n可用资金: {available_cash:.2f}")
            else:
                print("获取资金信息失败")
                return
        except Exception as e:
            print(f"获取资金信息异常: {e}")
            return

        # 6. 计算补充挂单数量（重新平均分配给未成功的股票）
        if len(not_buied) > 0:
            position_per_stock = available_cash / len(not_buied)
            print(f"补充挂单单票预算资金: {position_per_stock:.2f}")

        # 7. 为未成功的股票补充挂单
        success_count = 0
        fail_count = 0

        for stock_code in not_buied:
            try:
                # 获取昨日收盘价
                last_close = ContextInfo.get_last_close(stock_code)
                if last_close <= 0:
                    print(f"跳过 {stock_code}: 无法获取昨收价")
                    fail_count += 1
                    continue

                # 计算涨停价（根据板块不同）
                if stock_code.startswith('30') or stock_code.startswith('68'):
                    # 创业板/科创板 20%
                    limit_up_price = last_close * 1.20
                elif stock_code.startswith('8') or stock_code.startswith('4'):
                    # 北交所 30%
                    limit_up_price = last_close * 1.30
                else:
                    # 主板 10%
                    limit_up_price = last_close * 1.10

                # 计算买入数量（按涨停价计算）
                volume = int(position_per_stock / limit_up_price / 100) * 100  # 确保是100的整数倍

                if volume <= 0:
                    print(f"跳过 {stock_code}: 计算买入数量为0")
                    fail_count += 1
                    continue

                print(f"补充挂单: {stock_code}, 昨收: {last_close:.2f}, 涨停价: {limit_up_price:.2f}, 数量: {volume}")

                # 挂买单（11是买入）
                if 'pass_order' in globals():
                    # 使用 pass_order 接口
                    pass_order(23, 1101, ContextInfo.account_id, stock_code, 11, limit_up_price, volume,
                              f'补充挂单-{datetime.datetime.now().strftime("%Y%m%d")}', 2, "", ContextInfo)
                else:
                    # 使用 ContextInfo 的接口
                    ContextInfo.buy_stock(stock_code, volume, ContextInfo.account_id)

                success_count += 1

            except Exception as e:
                print(f"补充挂单失败 {stock_code}: {e}")
                fail_count += 1
                continue

        # 8. 输出校验结果
        print(f"\n=== 晨间校验结果 ===")
        print(f"候选股票总数: {len(candidates)}")
        print(f"已成功买入: {len(candidates) - len(not_buied)}")
        print(f"本次补充挂单: {success_count}")
        print(f"补充挂单失败: {fail_count}")
        print(f"[{datetime.datetime.now()}] === 晨间校验任务完成 ===\n")

    except Exception as e:
        print(f"晨间校验任务异常: {e}")

def check_is_limit_up_now(ContextInfo, code):
    """检查当前是否涨停"""
    try:
        # 获取实时行情
        tick = ContextInfo.get_full_tick([code])
        if code not in tick:
            return False

        last_price = tick[code]['lastPrice']
        high_price = tick[code]['high']

        # 1. 用户建议的核心逻辑：收盘价(最新价) == 最高价
        # 考虑到浮点数精度，使用差值判断
        if abs(last_price - high_price) > 0.01:
            return False

        # 2. 补充校验：涨幅必须达到涨停板水平，防止普通上涨被误判
        pre_close = 0.0

        # 尝试获取昨收
        if hasattr(ContextInfo, 'get_last_close'):
            pre_close = ContextInfo.get_last_close(code)

        # 如果 get_last_close 失败或返回0，尝试从 tick 计算 (有些接口 tick['lastClose'] 存在)
        if pre_close <= 0:
             # 简单的 fallback：如果获取不到昨收，就只能暂时信任 last == high
             # 但为了安全，最好还是返回 False (宁可卖错，不可被套)
             # 或者尝试用 get_market_data_ex
             return False

        if pre_close > 0:
            # 计算涨幅
            pct = (last_price - pre_close) / pre_close

            # 设定阈值
            limit_threshold = 0.095 # 主板 10%

            # 创业板/科创板 20%
            if code.startswith('30') or code.startswith('68'):
                limit_threshold = 0.195
            # 北交所 30%
            elif code.startswith('8') or code.startswith('4'):
                limit_threshold = 0.295
            # ST股 5% (简单判断，如需严谨需查名)

            if pct < limit_threshold:
                return False

        return True
    except Exception as e:
        # print(f"判断涨停异常 {code}: {e}")
        return False
