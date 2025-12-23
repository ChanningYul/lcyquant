# -*- coding: utf-8 -*-
import datetime
import time
import os
import json

# 全局变量：记录已挂单股票（用于防止重复挂单）
_order_cache_file = 'data/order_cache.json'
_order_cache = {}  # 结构: {stock_code: {'timestamp': timestamp, 'date': 'YYYYMMDD'}}

def load_order_cache():
    """加载订单缓存"""
    global _order_cache
    try:
        if os.path.exists(_order_cache_file):
            with open(_order_cache_file, 'r', encoding='utf-8') as f:
                _order_cache = json.load(f)
        else:
            _order_cache = {}
    except Exception as e:
        print(f"⚠️ 加载订单缓存失败: {e}")
        _order_cache = {}

def save_order_cache():
    """保存订单缓存"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(_order_cache_file), exist_ok=True)
        with open(_order_cache_file, 'w', encoding='utf-8') as f:
            json.dump(_order_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存订单缓存失败: {e}")

def is_order_already_placed(stock_code, current_date):
    """
    检查股票是否已经在指定日期挂过单
    防止重复挂单（并发控制）

    Args:
        stock_code: 股票代码
        current_date: 当前日期 (YYYYMMDD格式)

    Returns:
        bool: True if already ordered today, False otherwise
    """
    if stock_code in _order_cache:
        cache_info = _order_cache[stock_code]
        # 检查是否为今日订单
        if cache_info.get('date') == current_date:
            return True
    return False

def mark_order_placed(stock_code):
    """
    标记股票已挂单

    Args:
        stock_code: 股票代码
    """
    global _order_cache
    current_time = time.time()
    current_date = datetime.datetime.now().strftime('%Y%m%d')

    _order_cache[stock_code] = {
        'timestamp': current_time,
        'date': current_date
    }
    # 保存到文件
    save_order_cache()

def clean_old_order_cache():
    """清理过期的订单缓存（保留最近7天）"""
    global _order_cache
    try:
        current_time = time.time()
        cutoff_time = current_time - 7 * 24 * 3600  # 7天前

        # 过滤掉过期的缓存
        _order_cache = {
            code: info for code, info in _order_cache.items()
            if info.get('timestamp', 0) > cutoff_time
        }

        save_order_cache()
    except Exception as e:
        print(f"⚠️ 清理订单缓存失败: {e}")

def load_account_id():
    """
    从配置文件加载账号ID
    支持以下位置（按优先级）：
    1. ./config/trade_config.json
    2. ./account_id.txt
    3. 环境变量 ACCOUNT_ID
    4. 返回默认值并提示用户

    Returns:
        str: 资金账号ID
    """
    config_paths = [
        'config/trade_config.json',
        'account_id.txt',
    ]

    # 尝试从配置文件读取
    for config_path in config_paths:
        try:
            if os.path.exists(config_path):
                if config_path.endswith('.json'):
                    # JSON配置文件
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        account_id = config.get('account_id') or config.get('account')
                        if account_id:
                            print(f"✓ 从配置文件读取账号ID: {config_path}")
                            return account_id
                else:
                    # 文本文件
                    with open(config_path, 'r', encoding='utf-8') as f:
                        account_id = f.read().strip()
                        if account_id:
                            print(f"✓ 从配置文件读取账号ID: {config_path}")
                            return account_id
        except Exception as e:
            print(f"⚠️ 读取配置文件失败 {config_path}: {e}")

    # 尝试从环境变量读取
    import os
    account_id = os.environ.get('ACCOUNT_ID')
    if account_id:
        print("✓ 从环境变量读取账号ID")
        return account_id

    # 如果都失败，返回默认值并提示
    print("❌ 未找到账号ID配置，请通过以下方式之一配置：")
    print("   1. 创建 config/trade_config.json 文件，包含: {\"account_id\": \"YOUR_ACCOUNT_ID\"}")
    print("   2. 创建 account_id.txt 文件，内容为您的账号ID")
    print("   3. 设置环境变量 ACCOUNT_ID")
    print("   4. 修改 trade.py 文件中的默认账号ID")
    print("-" * 60)
    return 'YOUR_ACCOUNT_ID'

def init(ContextInfo):
    try:
        print(">>> 交易执行模块正在初始化 (init)...")

        # 0. 加载订单缓存（用于并发控制）
        load_order_cache()
        clean_old_order_cache()

        # 1. 基础初始化 - 尝试从配置文件读取账号ID
        ContextInfo.account_id = load_account_id()

        # 2. 策略参数设置
        ContextInfo.params = {
            'stop_profit': 0.10,  # 止盈比例
            'stop_loss': -0.02,   # 止损比例
            'safety_margin': 0.05,  # 安全垫比例（预留5%资金作为手续费和安全边际）
            'transaction_cost_rate': 0.003,  # 交易手续费率（0.3%）
        }

        # 3. 定时任务设置 (ContextInfo.run_time)
        # 注意：run_time 的 start_time 参数指定"首次运行时间"，配合 period='1d' (1天间隔)，
        # 即可实现从该日期起，每天固定时间重复执行。此处设置一个过去的日期以确保启动即生效。
        start_date = "2023-01-01"

        # 任务1: 晚上挂单 (每天 21:00 启动)
        ContextInfo.run_time("run_night_order_task", "1d", f"{start_date} 21:00:00", "SH")

        # 任务2: 早上校验 (每天 09:25 启动线程)
        ContextInfo.run_time("run_morning_check_task", "1d", f"{start_date} 09:25:00", "SH")

        print("✓ 交易执行模块初始化完成")
        print(f"✓ 订单缓存已加载，已记录 {len(_order_cache)} 条历史订单")
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
                # 如果当前涨停，则不卖出（等待继续上涨）
                if check_is_limit_up_now(ContextInfo, code):
                    print(f"触发止盈线 {code}，但当前涨停，暂不卖出 (收益率: {profit_rate:.2%})")
                else:
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
            import os
            import re

            # 检查文件是否存在
            if not os.path.exists(candidate_file):
                print(f"❌ 候选股票文件不存在: {candidate_file}")
                return

            with open(candidate_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # 验证数据格式
                if not isinstance(data, dict):
                    print(f"❌ 候选股票数据格式错误：期望dict类型，实际为 {type(data).__name__}")
                    return

                candidates = data.get('candidates', [])

                # 验证数据是否为列表
                if not isinstance(candidates, list):
                    print(f"❌ 候选股票列表格式错误：期望list类型，实际为 {type(candidates).__name__}")
                    return

                # 验证股票代码格式（正则：6位数字.交易所代码）
                valid_pattern = re.compile(r'^\d{6}\.(SH|SZ|BJ)$')
                invalid_codes = [code for code in candidates if not valid_pattern.match(code)]

                if invalid_codes:
                    print(f"⚠️ 发现 {len(invalid_codes)} 个无效股票代码: {invalid_codes[:5]}{'...' if len(invalid_codes) > 5 else ''}")
                    # 过滤掉无效代码
                    candidates = [code for code in candidates if valid_pattern.match(code)]
                    print(f"过滤后有效股票代码数量: {len(candidates)}")

                # 检查数据时间戳（如果有）
                if 'timestamp' in data:
                    import time
                    file_time = data.get('timestamp', 0)
                    current_time = time.time()
                    # 检查文件是否超过24小时
                    if current_time - file_time > 86400:
                        print(f"⚠️ 候选股票数据已过期（超过24小时），请更新数据")

                print(f"✓ 成功读取 {len(candidates)} 只候选股票")
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析错误: {e}")
            return
        except Exception as e:
            print(f"❌ 读取候选股票列表失败: {e}")
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

        # 3. 计算单票仓位（预留手续费和安全垫后平分）
        # 预留交易手续费（买入时需要支付）
        # 预留安全垫（防止资金不足导致部分订单失败）
        if len(candidates) > 0:
            # 预留资金：总资金 * 安全垫比例 + 预估手续费
            safety_reserve = available_cash * ContextInfo.params['safety_margin']
            # 预估手续费：基于候选股票数量的粗略估算
            estimated_commission = available_cash * ContextInfo.params['transaction_cost_rate']
            # 可用资金 = 总资金 - 安全垫 - 预估手续费
            usable_cash = available_cash - safety_reserve - estimated_commission

            if usable_cash <= 0:
                print(f"⚠️ 可用资金不足，预留安全垫后剩余: {usable_cash:.2f}")
                return

            position_per_stock = usable_cash / len(candidates)
            print(f"可用资金: {available_cash:.2f}, 预留安全垫: {safety_reserve:.2f}, 预估手续费: {estimated_commission:.2f}")
            print(f"单票预算资金: {position_per_stock:.2f}")

        # 4. 为每只候选股票挂涨停价买单
        current_date = datetime.datetime.now().strftime('%Y%m%d')

        for stock_code in candidates:
            try:
                # 检查是否已经挂过单（并发控制）
                if is_order_already_placed(stock_code, current_date):
                    print(f"⏭️ 跳过 {stock_code}: 今日已挂单")
                    continue

                # 获取昨日收盘价
                last_close = ContextInfo.get_last_close(stock_code)
                if last_close <= 0:
                    print(f"跳过 {stock_code}: 无法获取昨收价")
                    continue

                # 计算涨停价（使用专用函数，自动处理不同板块和ST股）
                limit_up_price = calculate_limit_up_price(last_close, stock_code)

                if limit_up_price <= 0:
                    print(f"跳过 {stock_code}: 涨停价计算失败")
                    continue

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

                # 标记为已挂单（并发控制）
                mark_order_placed(stock_code)

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
            import os
            import re

            # 检查文件是否存在
            if not os.path.exists(candidate_file):
                print(f"❌ 候选股票文件不存在: {candidate_file}")
                return

            with open(candidate_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # 验证数据格式
                if not isinstance(data, dict):
                    print(f"❌ 候选股票数据格式错误：期望dict类型，实际为 {type(data).__name__}")
                    return

                candidates = data.get('candidates', [])

                # 验证数据是否为列表
                if not isinstance(candidates, list):
                    print(f"❌ 候选股票列表格式错误：期望list类型，实际为 {type(candidates).__name__}")
                    return

                # 验证股票代码格式（正则：6位数字.交易所代码）
                valid_pattern = re.compile(r'^\d{6}\.(SH|SZ|BJ)$')
                invalid_codes = [code for code in candidates if not valid_pattern.match(code)]

                if invalid_codes:
                    print(f"⚠️ 发现 {len(invalid_codes)} 个无效股票代码: {invalid_codes[:5]}{'...' if len(invalid_codes) > 5 else ''}")
                    # 过滤掉无效代码
                    candidates = [code for code in candidates if valid_pattern.match(code)]
                    print(f"过滤后有效股票代码数量: {len(candidates)}")

                # 检查数据时间戳（如果有）
                if 'timestamp' in data:
                    import time
                    file_time = data.get('timestamp', 0)
                    current_time = time.time()
                    # 检查文件是否超过24小时
                    if current_time - file_time > 86400:
                        print(f"⚠️ 候选股票数据已过期（超过24小时），请更新数据")

                print(f"✓ 候选股票总数: {len(candidates)} 只")
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析错误: {e}")
            return
        except Exception as e:
            print(f"❌ 读取候选股票列表失败: {e}")
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

        # 6. 计算补充挂单数量（预留手续费和安全垫后分配给未成功的股票）
        if len(not_buied) > 0:
            # 预留资金：总资金 * 安全垫比例 + 预估手续费
            safety_reserve = available_cash * ContextInfo.params['safety_margin']
            # 预估手续费：基于补充挂单数量的粗略估算
            estimated_commission = available_cash * ContextInfo.params['transaction_cost_rate']
            # 可用资金 = 总资金 - 安全垫 - 预估手续费
            usable_cash = available_cash - safety_reserve - estimated_commission

            if usable_cash <= 0:
                print(f"⚠️ 可用资金不足，预留安全垫后剩余: {usable_cash:.2f}")
                return

            position_per_stock = usable_cash / len(not_buied)
            print(f"可用资金: {available_cash:.2f}, 预留安全垫: {safety_reserve:.2f}, 预估手续费: {estimated_commission:.2f}")
            print(f"补充挂单单票预算资金: {position_per_stock:.2f}")

        # 7. 为未成功的股票补充挂单
        success_count = 0
        fail_count = 0
        current_date = datetime.datetime.now().strftime('%Y%m%d')

        for stock_code in not_buied:
            try:
                # 检查是否已经挂过单（并发控制）
                if is_order_already_placed(stock_code, current_date):
                    print(f"⏭️ 跳过 {stock_code}: 今日已挂单")
                    fail_count += 1
                    continue

                # 获取昨日收盘价
                last_close = ContextInfo.get_last_close(stock_code)
                if last_close <= 0:
                    print(f"跳过 {stock_code}: 无法获取昨收价")
                    fail_count += 1
                    continue

                # 计算涨停价（使用专用函数，自动处理不同板块和ST股）
                limit_up_price = calculate_limit_up_price(last_close, stock_code)

                if limit_up_price <= 0:
                    print(f"跳过 {stock_code}: 涨停价计算失败")
                    fail_count += 1
                    continue

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

                # 标记为已挂单（并发控制）
                mark_order_placed(stock_code)

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
            limit_threshold = calculate_limit_ratio(code)

            if pct < limit_threshold:
                return False

        return True
    except Exception as e:
        # print(f"判断涨停异常 {code}: {e}")
        return False

def calculate_limit_ratio(code):
    """
    计算涨停幅度比例
    """
    # ST股票：5%
    if code.startswith('st') or code.startswith('ST') or code.startswith('sst') or code.startswith('SST'):
        return 0.045  # 略低于5%，考虑精度问题
    # 创业板/科创板：20%
    elif code.startswith('30') or code.startswith('68'):
        return 0.195
    # 北交所：30%
    elif code.startswith('8') or code.startswith('4') or code.startswith('92'):
        return 0.295
    # 主板：10%
    else:
        return 0.095

def calculate_limit_up_price(last_close, code):
    """
    计算涨停价（修正版）
    注意：隔夜挂单需基于今日收盘价手动计算次日涨停价

    Args:
        last_close: 昨日收盘价
        code: 股票代码

    Returns:
        涨停价（保留2位小数）
    """
    if last_close <= 0:
        return 0

    ratio = calculate_limit_ratio(code)
    price = last_close * (1 + ratio)

    # 使用round()修约到2位小数，符合交易所价格精度要求
    return round(price, 2)
