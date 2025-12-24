# -*- coding: utf-8 -*-
"""
独立运行的 miniQMT 交易策略

基于 XtQuant 的独立交易脚本，实现：
1. 自动连接 miniQMT
2. 夜间挂单（21:00）
3. 晨间校验（09:25）
4. 实时止盈止损监控
5. 订单缓存防重复挂单
"""

import datetime
import time
import os
import json
import sys
import signal
import schedule
import threading
from xtquant import xtconstant
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtdata

# ============================================================================
# 全局配置
# ============================================================================

# miniQMT 连接路径（需要根据实际情况修改）
MINIQMT_PATH = 'D:\\xtqmt_gs\\userdata_mini'

# 会话ID（不同策略使用不同ID）
SESSION_ID = 123456

# 订单缓存文件
ORDER_CACHE_FILE = 'data/order_cache.json'

# 候选股票文件
CANDIDATE_FILE = 'data/candidate.json'

# 全局变量
_order_cache = {}  # 结构: {stock_code: {'timestamp': timestamp, 'date': 'YYYYMMDD'}}
_xt_trader = None
_account = None
_running = False
_subscribed_stocks = set()  # 当前订阅的股票列表
_candidate_stocks = []  # 候选股票列表
_last_positions = {}  # 上次持仓快照，用于检测持仓变化
_last_subscription_update = 0  # 上次订阅更新时间
_data_lock = threading.Lock()  # 线程锁保护共享变量
_reconnect_count = 0  # 重连次数
_last_connect_time = 0  # 上次连接时间


# ============================================================================
# 订单缓存管理
# ============================================================================

def load_order_cache():
    """加载订单缓存"""
    global _order_cache
    with _data_lock:
        try:
            if os.path.exists(ORDER_CACHE_FILE):
                with open(ORDER_CACHE_FILE, 'r', encoding='utf-8') as f:
                    _order_cache = json.load(f)
            else:
                _order_cache = {}
        except Exception as e:
            print(f"⚠️ 加载订单缓存失败: {e}")
            _order_cache = {}


def save_order_cache():
    """保存订单缓存"""
    with _data_lock:
        try:
            os.makedirs(os.path.dirname(ORDER_CACHE_FILE), exist_ok=True)
            with open(ORDER_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(_order_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存订单缓存失败: {e}")


def is_order_already_placed(stock_code, current_date):
    """
    检查股票是否已经在指定日期挂过单
    防止重复挂单（并发控制）
    """
    with _data_lock:
        if stock_code in _order_cache:
            cache_info = _order_cache[stock_code]
            if cache_info.get('date') == current_date:
                return True
        return False


def mark_order_placed(stock_code):
    """标记股票已挂单"""
    global _order_cache
    with _data_lock:
        current_time = time.time()
        current_date = datetime.datetime.now().strftime('%Y%m%d')

        _order_cache[stock_code] = {
            'timestamp': current_time,
            'date': current_date
        }
        save_order_cache()


def clean_old_order_cache():
    """清理过期的订单缓存（保留最近7天）"""
    global _order_cache
    try:
        current_time = time.time()
        cutoff_time = current_time - 7 * 24 * 3600

        _order_cache = {
            code: info for code, info in _order_cache.items()
            if info.get('timestamp', 0) > cutoff_time
        }
        save_order_cache()
    except Exception as e:
        print(f"⚠️ 清理订单缓存失败: {e}")


# ============================================================================
# 账号管理
# ============================================================================

def load_account_id():
    """
    从配置文件加载账号ID
    支持以下位置（按优先级）：
    1. ./config/trade_config.json
    2. ./account_id.txt
    3. 环境变量 ACCOUNT_ID
    4. 返回默认值并提示用户
    """
    config_paths = [
        'config/trade_config.json',
        'account_id.txt',
    ]

    for config_path in config_paths:
        try:
            if os.path.exists(config_path):
                if config_path.endswith('.json'):
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        account_id = config.get('account_id') or config.get('account')
                        if account_id:
                            print(f"✓ 从配置文件读取账号ID: {config_path}")
                            return account_id
                else:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        account_id = f.read().strip()
                        if account_id:
                            print(f"✓ 从配置文件读取账号ID: {config_path}")
                            return account_id
        except Exception as e:
            print(f"⚠️ 读取配置文件失败 {config_path}: {e}")

    account_id = os.environ.get('ACCOUNT_ID')
    if account_id:
        print("✓ 从环境变量读取账号ID")
        return account_id

    print("❌ 未找到账号ID配置，请通过以下方式之一配置：")
    print("   1. 创建 config/trade_config.json 文件，包含: {\"account_id\": \"YOUR_ACCOUNT_ID\"}")
    print("   2. 创建 account_id.txt 文件，内容为您的账号ID")
    print("   3. 设置环境变量 ACCOUNT_ID")
    print("-" * 60)
    return 'YOUR_ACCOUNT_ID'


# ============================================================================
# 订阅管理
# ============================================================================

def load_candidate_stocks():
    """加载候选股票列表"""
    global _candidate_stocks
    with _data_lock:
        try:
            if os.path.exists(CANDIDATE_FILE):
                with open(CANDIDATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    candidates = data.get('candidates', [])
                    if isinstance(candidates, list):
                        _candidate_stocks = candidates
                        print(f"✓ 加载候选股票 {len(_candidate_stocks)} 只")
                        return True
            print(f"⚠️ 候选股票文件不存在或格式错误: {CANDIDATE_FILE}")
            return False
        except Exception as e:
            print(f"⚠️ 加载候选股票失败: {e}")
            return False


def get_current_positions():
    """获取当前持仓股票列表 - 超时后重试一次"""
    global _xt_trader, _account
    if not _xt_trader or not _account:
        return set()

    try:
        import threading
        result = [None]
        exception = [None]

        def do_query():
            try:
                result[0] = _xt_trader.query_stock_positions(_account)
            except Exception as e:
                exception[0] = e

        # 第一次尝试
        t = threading.Thread(target=do_query)
        t.daemon = True
        t.start()
        t.join(timeout=3)

        if t.is_alive():
            # 超时，重试一次
            print("[TIMEOUT] query positions - retrying...")
            t = threading.Thread(target=do_query)
            t.daemon = True
            t.start()
            t.join(timeout=10)  # 重试给更长时间

            if t.is_alive():
                print("[TIMEOUT] query positions - failed after retry")
                return set()

        if exception[0]:
            print(f"[ERROR] query positions: {exception[0]}")
            return set()

        positions = result[0]
        if positions is None:
            return set()

        position_stocks = set()
        for pos in positions:
            if pos.volume > 0:
                position_stocks.add(pos.stock_code)
        return position_stocks
    except Exception as e:
        print(f"[ERROR] query positions: {e}")
        return set()


def calculate_desired_subscriptions():
    """计算需要订阅的股票列表（候选股票 + 持仓股票）"""
    desired_set = set(_candidate_stocks)
    position_set = get_current_positions()
    desired_set.update(position_set)
    return desired_set


def update_subscriptions():
    """更新订阅列表"""
    global _subscribed_stocks

    desired_stocks = calculate_desired_subscriptions()

    with _data_lock:
        # 需要新增的订阅
        new_subscriptions = desired_stocks - _subscribed_stocks
        # 需要取消的订阅
        unsubscribe_list = _subscribed_stocks - desired_stocks

        # 取消不需要的订阅
        if unsubscribe_list:
            print(f"🔄 取消订阅 {len(unsubscribe_list)} 只股票: {list(unsubscribe_list)[:5]}{'...' if len(unsubscribe_list) > 5 else ''}")
            for stock_code in unsubscribe_list:
                try:
                    # 注意：xtdata 没有直接的反订阅接口，这里只是记录状态
                    pass
                except Exception as e:
                    print(f"取消订阅失败 {stock_code}: {e}")

        # 添加新的订阅（带超时保护）
        if new_subscriptions:
            print(f"🔄 新增订阅 {len(new_subscriptions)} 只股票: {list(new_subscriptions)[:5]}{'...' if len(new_subscriptions) > 5 else ''}")
            for stock_code in new_subscriptions:
                try:
                    subscribe_stock(stock_code)
                except Exception as e:
                    print(f"订阅失败 {stock_code}: {e}")

        _subscribed_stocks = desired_stocks
        print(f"📡 当前订阅 {len(_subscribed_stocks)} 只股票")


_subscribe_ids = {}  # 股票订阅ID映射 {stock_code: subscribe_id}


def subscribe_stock(stock_code):
    """订阅单只股票行情（防重复订阅）- 超时后重试一次"""
    global _subscribe_ids
    try:
        with _data_lock:
            if stock_code in _subscribe_ids:
                return True

        import threading
        result = [None]
        exception = [None]

        def do_subscribe():
            try:
                subscribe_id = xtdata.subscribe_quote(stock_code, period='tick', callback=on_tick_data)
                result[0] = subscribe_id
            except Exception as e:
                exception[0] = e

        # 第一次尝试
        t = threading.Thread(target=do_subscribe)
        t.daemon = True
        t.start()
        t.join(timeout=1)

        if t.is_alive():
            # 超时，重试一次
            print(f"[TIMEOUT] subscribe {stock_code} - retrying...")
            t = threading.Thread(target=do_subscribe)
            t.daemon = True
            t.start()
            t.join(timeout=3)  # 重试给更长时间

            if t.is_alive():
                print(f"[TIMEOUT] subscribe {stock_code} - failed after retry")
                return False

        if exception[0]:
            print(f"[ERROR] subscribe {stock_code}: {exception[0]}")
            return False

        if result[0] is None:
            return False

        with _data_lock:
            _subscribe_ids[stock_code] = result[0]
        return True
    except Exception as e:
        print(f"[ERROR] subscribe {stock_code}: {e}")
        return False


def on_tick_data(datas):
    """行情数据回调 - 处理止盈止损逻辑"""
    try:
        for stock_code, tick_list in datas.items():
            if not tick_list:
                continue

            # 获取最新一条数据
            latest_tick = tick_list[-1]
            curr_price = latest_tick.get('lastPrice', 0)

            if curr_price <= 0:
                continue

            # 检查是否触发止盈止损
            check_stop_conditions(stock_code, curr_price)

    except Exception as e:
        print(f"处理行情数据异常: {e}")


# ============================================================================
# XtQuantTrader 回调类
# ============================================================================

class MyXtQuantTraderCallback(XtQuantTraderCallback):
    """交易回调类"""

    def on_disconnected(self):
        """连接断开"""
        print("❌ 连接断开，尝试自动重连...")
        global _reconnect_count, _last_connect_time
        _reconnect_count += 1
        _last_connect_time = time.time()

    def on_stock_order(self, order):
        """委托回报推送"""
        print(f"📋 委托回报: {order.stock_code} 状态:{order.order_status} 合同号:{order.order_sysid}")

    def on_stock_trade(self, trade):
        """成交变动推送"""
        print(f"✅ 成交回报: {trade.stock_code} 成交价:{trade.traded_price} 数量:{trade.traded_volume}")

    def on_stock_position(self, position):
        """持仓变动推送"""
        print(f"📊 持仓变动: {position.stock_code} 数量:{position.volume}")

        # 持仓变化时更新订阅列表
        try:
            update_subscriptions()
        except Exception as e:
            print(f"更新订阅列表失败: {e}")

    def on_stock_asset(self, asset):
        """资金变动推送"""
        print(f"💰 资金变动: 可用{asset.cash:.2f} 总资产{asset.total_asset:.2f}")

    def on_order_error(self, order_error):
        """委托失败推送"""
        print(f"❌ 委托失败: 订单号{order_error.order_id} 错误码{order_error.error_id} {order_error.error_msg}")

    def on_cancel_error(self, cancel_error):
        """撤单失败推送"""
        print(f"❌ 撤单失败: 订单号{cancel_error.order_id} 错误码{cancel_error.error_id} {cancel_error.error_msg}")

    def on_account_status(self, status):
        """账号状态推送"""
        status_map = {
            xtconstant.ACCOUNT_STATUS_OK: "正常",
            xtconstant.ACCOUNT_STATUS_WAITING_LOGIN: "连接中",
            xtconstant.ACCOUNT_STATUS_CLOSED: "收盘后",
        }
        status_name = status_map.get(status.status, f"未知({status.status})")
        print(f"📡 账号状态: {status_name}")


# ============================================================================
# 重连机制
# ============================================================================

def try_reconnect():
    """尝试重连交易模块"""
    global _xt_trader, _account, _reconnect_count, _subscribe_ids

    print(f"\n🔄 尝试重连（第 {_reconnect_count} 次）...")

    try:
        # 停止旧的交易线程
        if _xt_trader:
            _xt_trader.stop()
            print("✓ 已停止旧交易线程")

        # 重新创建交易对象
        _xt_trader = XtQuantTrader(MINIQMT_PATH, SESSION_ID)
        callback = MyXtQuantTraderCallback()
        _xt_trader.register_callback(callback)
        _xt_trader.start()

        # 建立连接
        connect_result = _xt_trader.connect()
        if connect_result != 0:
            print(f"❌ 重连失败，错误码: {connect_result}")
            return False

        print("✓ 重连成功")

        # 重新订阅账号
        account_id = load_account_id()
        _account = StockAccount(account_id)
        subscribe_result = _xt_trader.subscribe(_account)
        if subscribe_result != 0:
            print(f"❌ 账号订阅失败，错误码: {subscribe_result}")
            return False

        # 清除旧的订阅记录，重新订阅
        _subscribe_ids = {}
        update_subscriptions()

        return True
    except Exception as e:
        print(f"❌ 重连异常: {e}")
        return False


# ============================================================================
# 交易逻辑
# ============================================================================

TRADE_PARAMS = {
    'stop_profit': 0.10,  # 止盈比例
    'stop_loss': -0.02,   # 止损比例
    'safety_margin': 0.05,  # 安全垫比例（预留5%资金作为手续费和安全边际）
    'transaction_cost_rate': 0.003,  # 交易手续费率（0.3%）
}


def check_stop_conditions(stock_code, curr_price):
    """检查指定股票的止盈止损条件"""
    try:
        if not _xt_trader or not _account:
            return

        # 查询该股票的持仓信息
        position = _xt_trader.query_stock_position(_account, stock_code)
        if not position:
            return

        volume = position.volume
        can_use_volume = position.can_use_volume
        avg_price = position.avg_price

        if can_use_volume <= 0:
            return

        if avg_price <= 0:
            return

        profit_rate = (curr_price - avg_price) / avg_price

        # 止盈: > 10%
        if profit_rate >= TRADE_PARAMS['stop_profit']:
            if check_is_limit_up_now(stock_code):
                print(f"触发止盈线 {stock_code}，但当前涨停，暂不卖出 (收益率: {profit_rate:.2%})")
            else:
                print(f"触发止盈: {stock_code}, 收益率 {profit_rate:.2%}")
                do_sell(stock_code, curr_price, can_use_volume, "止盈卖出")

        # 止损: < -2%
        elif profit_rate <= TRADE_PARAMS['stop_loss']:
            print(f"触发止损: {stock_code}, 收益率 {profit_rate:.2%}")
            do_sell(stock_code, curr_price, can_use_volume, "止损卖出")

    except Exception as e:
        print(f"止盈止损检查异常 {stock_code}: {e}")


def check_all_holdings():
    """检查所有持仓（用于定时检查）"""
    try:
        if not _xt_trader or not _account:
            return

        positions = _xt_trader.query_stock_positions(_account)
        if not positions:
            return

        for pos in positions:
            code = pos.stock_code
            volume = pos.volume
            can_use_volume = pos.can_use_volume

            if can_use_volume <= 0:
                continue

            # 获取当前价格
            tick = xtdata.get_full_tick([code])
            if code not in tick:
                continue

            curr_price = tick[code]['lastPrice']
            check_stop_conditions(code, curr_price)

    except Exception as e:
        print(f"持仓检查异常: {e}")


def do_sell(stock_code, price, volume, msg):
    """执行卖出"""
    try:
        print(f"执行卖出: {stock_code}, 价格 {price}, 数量 {volume}, 原因: {msg}")
        order_id = _xt_trader.order_stock(
            _account, stock_code, xtconstant.STOCK_SELL, volume,
            xtconstant.FIX_PRICE, price, 'trade_mini', msg
        )
        if order_id > 0:
            print(f"✓ 卖出委托成功，订单号: {order_id}")
        else:
            print(f"❌ 卖出委托失败")
    except Exception as e:
        print(f"卖出异常: {e}")


def run_night_order_task():
    """夜间挂单任务（21:00执行）- 为候选股票挂次日涨停价买单"""
    print(f"\n[{datetime.datetime.now()}] === 夜间挂单任务开始 ===")

    try:
        if not _xt_trader or not _account:
            print("❌ 交易接口未初始化")
            return

        # 1. 加载候选股票列表并更新订阅
        if not load_candidate_stocks():
            return

        # 更新订阅列表（候选股票 + 持仓股票）
        update_subscriptions()

        candidates = _candidate_stocks
        if not candidates:
            print("候选股票列表为空，无需挂单")
            return

        print(f"✓ 成功读取 {len(candidates)} 只候选股票")

        # 2. 获取可用资金
        asset = _xt_trader.query_stock_asset(_account)
        if asset:
            available_cash = asset.cash
            print(f"可用资金: {available_cash:.2f}")
        else:
            print("获取资金信息失败")
            return

        # 3. 计算已持仓股票的资金占用（排除候选股票）
        positions = _xt_trader.query_stock_positions(_account)
        held_positions_value = 0.0
        for pos in positions:
            code = pos.stock_code
            volume = pos.volume
            avg_price = pos.avg_price
            # 只计算不在候选列表中的持仓资金占用
            if code not in candidates and volume > 0 and avg_price > 0:
                held_positions_value += volume * avg_price
        print(f"已持仓（非候选）资金占用: {held_positions_value:.2f}")

        # 4. 计算单票仓位（扣除已持仓资金占用）
        usable_cash = available_cash - held_positions_value
        safety_reserve = usable_cash * TRADE_PARAMS['safety_margin']
        estimated_commission = usable_cash * TRADE_PARAMS['transaction_cost_rate']
        usable_cash = usable_cash - safety_reserve - estimated_commission

        if usable_cash <= 0:
            print(f"⚠️ 可用资金不足，预留安全垫后剩余: {usable_cash:.2f}")
            return

        position_per_stock = usable_cash / len(candidates)
        print(f"可用资金: {available_cash:.2f}, 预留安全垫: {safety_reserve:.2f}")
        print(f"单票预算资金: {position_per_stock:.2f}")

        # 4. 为每只候选股票挂涨停价买单
        current_date = datetime.datetime.now().strftime('%Y%m%d')
        success_count = 0
        fail_count = 0

        for stock_code in candidates:
            try:
                # 检查是否已经挂过单
                if is_order_already_placed(stock_code, current_date):
                    print(f"⏭️ 跳过 {stock_code}: 今日已挂单")
                    continue

                # 获取昨日收盘价
                last_close = xtdata.get_last_close(stock_code)
                if last_close <= 0:
                    print(f"跳过 {stock_code}: 无法获取昨收价")
                    fail_count += 1
                    continue

                # 计算涨停价
                limit_up_price = calculate_limit_up_price(last_close, stock_code)
                if limit_up_price <= 0:
                    print(f"跳过 {stock_code}: 涨停价计算失败")
                    fail_count += 1
                    continue

                # 计算买入数量
                volume = int(position_per_stock / limit_up_price / 100) * 100
                if volume <= 0:
                    print(f"跳过 {stock_code}: 计算买入数量为0")
                    fail_count += 1
                    continue

                print(f"挂单: {stock_code}, 昨收: {last_close:.2f}, 涨停价: {limit_up_price:.2f}, 数量: {volume}")

                # 挂买单
                order_id = _xt_trader.order_stock(
                    _account, stock_code, xtconstant.STOCK_BUY, volume,
                    xtconstant.FIX_PRICE, limit_up_price, 'trade_mini',
                    f'夜间挂单-{current_date}'
                )

                if order_id > 0:
                    print(f"✓ 挂单成功，订单号: {order_id}")
                    # 只有挂单成功才标记，避免因挂单失败导致无法重试
                    mark_order_placed(stock_code)
                    success_count += 1
                else:
                    print(f"❌ 挂单失败: {stock_code}")
                    fail_count += 1

            except Exception as e:
                print(f"挂单失败 {stock_code}: {e}")
                fail_count += 1
                continue

        print(f"\n=== 夜间挂单结果 ===")
        print(f"候选股票总数: {len(candidates)}")
        print(f"成功挂单: {success_count}")
        print(f"挂单失败: {fail_count}")
        print(f"[{datetime.datetime.now()}] === 夜间挂单任务完成 ===\n")

    except Exception as e:
        print(f"夜间挂单任务异常: {e}")


def run_morning_check_task():
    """晨间校验任务（09:25执行）- 校验前一晚的挂单是否成功，如失败则补充挂单"""
    print(f"\n[{datetime.datetime.now()}] === 晨间校验任务开始 ===")

    try:
        if not _xt_trader or not _account:
            print("❌ 交易接口未初始化")
            return

        # 1. 加载候选股票列表并更新订阅
        if not load_candidate_stocks():
            return

        # 更新订阅列表（候选股票 + 持仓股票）
        update_subscriptions()

        candidates = _candidate_stocks
        if not candidates:
            print("候选股票列表为空，无需校验")
            return

        print(f"✓ 候选股票总数: {len(candidates)} 只")

        # 2. 获取当前持仓
        positions = _xt_trader.query_stock_positions(_account)

        held_stocks = set()
        for pos in positions:
            code = pos.stock_code
            volume = pos.volume
            if volume > 0:
                held_stocks.add(code)

        print(f"当前已持仓股票: {len(held_stocks)} 只")
        print(f"候选股票中已买入: {len(held_stocks.intersection(candidates))} 只")

        # 3. 检查哪些候选股票未成功买入
        not_buied = [code for code in candidates if code not in held_stocks]

        if not not_buied:
            print("✓ 所有候选股票均已成功买入，无需补充挂单")
            print(f"[{datetime.datetime.now()}] === 晨间校验任务完成 ===\n")
            return

        print(f"\n⚠ 发现 {len(not_buied)} 只候选股票未成功买入，将补充挂单:")
        for code in not_buied:
            print(f"  - {code}")

        # 4. 获取可用资金
        asset = _xt_trader.query_stock_asset(_account)
        if asset:
            available_cash = asset.cash
            print(f"\n可用资金: {available_cash:.2f}")
        else:
            print("获取资金信息失败")
            return

        # 5. 计算已持仓股票的资金占用（排除候选股票和已买入的）
        held_positions_value = 0.0
        for pos in positions:
            code = pos.stock_code
            volume = pos.volume
            avg_price = pos.avg_price
            # 只计算不在候选列表中的持仓资金占用
            if code not in candidates and volume > 0 and avg_price > 0:
                held_positions_value += volume * avg_price
        print(f"已持仓（非候选）资金占用: {held_positions_value:.2f}")

        # 6. 计算补充挂单数量（扣除已持仓资金占用）
        usable_cash = available_cash - held_positions_value
        safety_reserve = usable_cash * TRADE_PARAMS['safety_margin']
        estimated_commission = usable_cash * TRADE_PARAMS['transaction_cost_rate']
        usable_cash = usable_cash - safety_reserve - estimated_commission

        if usable_cash <= 0:
            print(f"⚠️ 可用资金不足，预留安全垫后剩余: {usable_cash:.2f}")
            return

        position_per_stock = usable_cash / len(not_buied)
        print(f"补充挂单单票预算资金: {position_per_stock:.2f}")

        # 6. 为未成功的股票补充挂单
        success_count = 0
        fail_count = 0
        current_date = datetime.datetime.now().strftime('%Y%m%d')

        for stock_code in not_buied:
            try:
                if is_order_already_placed(stock_code, current_date):
                    print(f"⏭️ 跳过 {stock_code}: 今日已挂单")
                    fail_count += 1
                    continue

                last_close = xtdata.get_last_close(stock_code)
                if last_close <= 0:
                    print(f"跳过 {stock_code}: 无法获取昨收价")
                    fail_count += 1
                    continue

                limit_up_price = calculate_limit_up_price(last_close, stock_code)
                if limit_up_price <= 0:
                    print(f"跳过 {stock_code}: 涨停价计算失败")
                    fail_count += 1
                    continue

                volume = int(position_per_stock / limit_up_price / 100) * 100
                if volume <= 0:
                    print(f"跳过 {stock_code}: 计算买入数量为0")
                    fail_count += 1
                    continue

                print(f"补充挂单: {stock_code}, 昨收: {last_close:.2f}, 涨停价: {limit_up_price:.2f}, 数量: {volume}")

                order_id = _xt_trader.order_stock(
                    _account, stock_code, xtconstant.STOCK_BUY, volume,
                    xtconstant.FIX_PRICE, limit_up_price, 'trade_mini',
                    f'补充挂单-{current_date}'
                )

                if order_id > 0:
                    print(f"✓ 补充挂单成功，订单号: {order_id}")
                    # 只有挂单成功才标记，避免因挂单失败导致无法重试
                    mark_order_placed(stock_code)
                    success_count += 1
                else:
                    print(f"❌ 补充挂单失败: {stock_code}")
                    fail_count += 1

            except Exception as e:
                print(f"补充挂单失败 {stock_code}: {e}")
                fail_count += 1
                continue

        # 7. 输出校验结果
        print(f"\n=== 晨间校验结果 ===")
        print(f"候选股票总数: {len(candidates)}")
        print(f"已成功买入: {len(candidates) - len(not_buied)}")
        print(f"本次补充挂单: {success_count}")
        print(f"补充挂单失败: {fail_count}")
        print(f"[{datetime.datetime.now()}] === 晨间校验任务完成 ===\n")

    except Exception as e:
        print(f"晨间校验任务异常: {e}")


def check_is_limit_up_now(code):
    """检查当前是否涨停"""
    try:
        tick = xtdata.get_full_tick([code])
        if code not in tick:
            return False

        last_price = tick[code]['lastPrice']
        high_price = tick[code]['high']

        if abs(last_price - high_price) > 0.01:
            return False

        pre_close = xtdata.get_last_close(code)
        if pre_close <= 0:
            return False

        pct = (last_price - pre_close) / pre_close
        limit_threshold = calculate_limit_ratio(code)

        return pct >= limit_threshold
    except Exception as e:
        return False


def calculate_limit_ratio(code):
    """计算涨停幅度比例"""
    if code.lower().startswith('st'):
        return 0.045
    elif code.startswith('30') or code.startswith('68'):
        return 0.195
    elif code.startswith('8') or code.startswith('4') or code.startswith('92'):
        return 0.295
    else:
        return 0.095


def calculate_limit_up_price(last_close, code):
    """计算涨停价"""
    if last_close <= 0:
        return 0

    ratio = calculate_limit_ratio(code)
    price = last_close * (1 + ratio)
    return round(price, 2)


# ============================================================================
# 定时任务调度
# ============================================================================

def setup_scheduler():
    """设置定时任务调度（使用定时基准时间，避免累积延迟）"""
    # 清空之前的任务
    schedule.clear()

    # 获取当前时间
    now = datetime.datetime.now()

    # 夜间挂单任务 - 每天 21:00
    night_time = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if now > night_time:
        night_time += datetime.timedelta(days=1)
    schedule.every().day.at("21:00").do(run_night_order_task)

    # 晨间校验任务 - 每天 09:25
    schedule.every().day.at("09:25").do(run_morning_check_task)

    print("✓ 定时任务已设置:")
    print("  - 夜间挂单任务: 每天 21:00")
    print("  - 晨间校验任务: 每天 09:25")


# ============================================================================
# 主程序
# ============================================================================

# 全局退出标志
_exit_flag = False


def signal_handler(sig, frame):
    """信号处理器 - 设置退出标志"""
    global _exit_flag
    _exit_flag = True
    print("\n[CTRL+C] Signal received, exiting...")
    os._exit(0)


def check_exit_key():
    """检查是否按下了退出键 (q 或 Q) 或 Ctrl+C 标志"""
    global _exit_flag
    try:
        import msvcrt
        if msvcrt.kbhit():
            key = msvcrt.getch()
            if key in [b'q', b'Q', b'\r']:
                return True
            while msvcrt.kbhit():
                msvcrt.getch()
    except:
        pass
    if _exit_flag:
        return True
    return False


def exit_monitor():
    """监控线程：定期检查是否需要退出"""
    global _exit_flag
    import time
    while not _exit_flag:
        if check_exit_key():
            print("\n[MONITOR] Exit key pressed")
            os._exit(0)
        time.sleep(0.2)


def main():
    """主程序"""
    global _xt_trader, _account, _running, _exit_flag

    # 启动退出监控线程
    monitor_thread = threading.Thread(target=exit_monitor, daemon=True)
    monitor_thread.start()

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("🚀 miniQMT 独立交易策略启动")
    print("=" * 60)

    try:
        # 1. 加载订单缓存
        print("\n📋 初始化订单缓存...")
        load_order_cache()
        clean_old_order_cache()
        print(f"✓ 订单缓存已加载，已记录 {len(_order_cache)} 条历史订单")

        # 2. 加载账号ID
        print("\n👤 加载交易账号...")
        account_id = load_account_id()
        if account_id == 'YOUR_ACCOUNT_ID':
            print("❌ 未配置有效账号ID，程序退出")
            return

        # 3. 初始化 xtdata（行情模块）
        print("\n📡 初始化行情模块...")
        print(f"✓ miniQMT 路径: {MINIQMT_PATH}")

        # 4. 创建交易对象
        print("\n🔌 连接交易模块...")
        _xt_trader = XtQuantTrader(MINIQMT_PATH, SESSION_ID)

        # 注册回调
        callback = MyXtQuantTraderCallback()
        _xt_trader.register_callback(callback)

        # 启动交易线程
        _xt_trader.start()

        # 建立连接
        connect_result = _xt_trader.connect()
        if connect_result != 0:
            print(f"❌ 交易连接失败，错误码: {connect_result}")
            return

        print("✓ 交易连接成功")

        # 创建账号对象
        _account = StockAccount(account_id)

        # 订阅账号信息
        subscribe_result = _xt_trader.subscribe(_account)
        if subscribe_result != 0:
            print(f"❌ 账号订阅失败，错误码: {subscribe_result}")
            return

        print(f"✓ 账号订阅成功: {account_id}")

        # 5. 设置定时任务
        print("\n⏰ 设置定时任务...")
        setup_scheduler()

        # 6. 初始订阅列表
        print("\n📡 初始化订阅列表...")
        load_candidate_stocks()
        update_subscriptions()

        # 7. 启动行情数据处理线程
        print("\n📡 启动行情数据处理线程...")
        def run_xtdata():
            """运行 xtdata 处理行情回调"""
            try:
                xtdata.run()
            except Exception as e:
                print(f"行情数据处理异常: {e}")

        xtdata_thread = threading.Thread(target=run_xtdata, daemon=True)
        xtdata_thread.start()
        print("✓ 行情数据处理线程已启动")

        # 8. 主循环（仅处理定时任务）
        print("\n[INFO] Main loop started")
        print("  - Real-time stop-profit/stop-loss monitoring")
        print("  - Scheduled tasks: night orders(21:00) and morning check(09:25)")
        print("  - Press 'q' or Ctrl+C to exit")
        print("-" * 60)

        _running = True

        # 启动主循环线程
        def main_loop():
            """主循环线程"""
            global _reconnect_count

            while _running:
                try:
                    # 检查是否按下了退出键
                    if check_exit_key():
                        print("\n主循环收到退出命令...")
                        return

                    # 检测是否需要重连
                    if _reconnect_count > 0:
                        now = time.time()
                        # 至少等待30秒再重连，避免频繁重连
                        if now - _last_connect_time >= 30:
                            if try_reconnect():
                                _reconnect_count = 0
                                print("✓ 重连成功，恢复正常运行")
                            else:
                                # 重连失败，等待10秒后重试
                                print("⏳ 等待10秒后重试...")
                                for _ in range(10):
                                    if not _running:
                                        return
                                    time.sleep(1)
                            continue  # 重连后跳过本次schedule检查

                    # 执行定时任务调度（非阻塞）
                    schedule.run_pending(blocking=False)

                    # 每分钟检查一次持仓变化，更新订阅列表
                    now = time.time()
                    if now - _last_subscription_update >= 60:
                        update_subscriptions()
                        _last_subscription_update = now

                    # 短暂sleep
                    time.sleep(0.5)
                    if not _running:
                        break

                except Exception as e:
                    print(f"主循环异常: {e}")
                    time.sleep(1)

        main_thread = threading.Thread(target=main_loop, name="MainLoop")
        main_thread.start()

        # 主线程循环：无限循环
        # 注意：主线程中的 time.sleep() 可被 Ctrl+C 的 KeyboardInterrupt 中断
        # signal_handler 会直接调用 os._exit(0) 退出
        # 同时支持按 'q' 键退出
        try:
            while True:
                time.sleep(0.5)
                # 检查是否按下了退出键
                if check_exit_key():
                    print("\n收到退出命令，正在退出...")
                    os._exit(0)
        except KeyboardInterrupt:
            pass

    except Exception as e:
        print(f"❌ 程序启动失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 清理资源
        print("\n🧹 清理资源...")
        if _xt_trader:
            _xt_trader.stop()
        print("✓ 程序已退出")


if __name__ == "__main__":
    # 检查配置文件
    if not os.path.exists('config/trade_config.json') and not os.path.exists('account_id.txt'):
        print("⚠️  警告: 未找到账号配置文件")
        print("请创建以下文件之一:")
        print("1. config/trade_config.json: {\"account_id\": \"您的账号ID\"}")
        print("2. account_id.txt: 您的账号ID")
        print("-" * 60)

    # 检查候选股票文件
    if not os.path.exists(CANDIDATE_FILE):
        print(f"⚠️  警告: 未找到候选股票文件: {CANDIDATE_FILE}")
        print("请确保候选股票数据文件存在")
        print("-" * 60)

    main()
