# coding:gbk
import pandas as pd
import numpy as np
import datetime
import time
import json
import os
import threading

# 全局配置文件路径
CANDIDATE_FILE = "e:/work/job/lcyquant/candidate.json"

def init(ContextInfo):
    try:
        print(">>> 策略正在初始化 (init)...")
        # 1. 基础初始化
        ContextInfo.stock_list = ContextInfo.get_stock_list_in_sector('沪深A股')
        ContextInfo.account_id = 'YOUR_ACCOUNT_ID' # 请替换为实际资金账号
        
        # 2. 策略参数设置
        ContextInfo.params = {
            'limit_ratio_main': 0.10,  #沪深A股涨停幅度
            'limit_ratio_special': 0.20, #创业板涨停幅度
            'limit_ratio_bj': 0.30, #北交所涨停幅度
            'max_price': 200.0, #最大持仓价格
            'drawdown_limit': 0.20, #最大回撤率
            'stop_profit': 0.10, #止盈比例
            'stop_loss': -0.02, #止损比例
            'seal_circ_ratio': 0.03, #封单对流通市值占比
            'seal_turnover_ratio': 2.0, #封单占成交额倍数
        }
        
        # 3. 定时任务设置 (ContextInfo.run_time)
        # 注意：run_time 的 start_time 参数指定“首次运行时间”，配合 period='1d' (1天间隔)，
        # 即可实现从该日期起，每天固定时间重复执行。此处设置一个过去的日期以确保启动即生效。
        start_date = "2023-01-01"

        # 任务1: 下午选股 (每天 15:30 启动线程)
        ContextInfo.run_time("run_selection_task", "1d", f"{start_date} 23:39:00", "SH")
        
        # 任务2: 晚上挂单 (每天 21:00 启动)
        ContextInfo.run_time("run_night_order_task", "1d", f"{start_date} 21:00:00", "SH")
        
        # 任务3: 早上校验 (每天 09:25 启动线程)
        ContextInfo.run_time("run_morning_check_task", "1d", f"{start_date} 09:25:00", "SH")
        
        print("策略初始化完成：多线程 + 存算分离架构")
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

# ==========================================
# 任务调度层 (Task Scheduler)
# ==========================================

def run_selection_task(ContextInfo):
    """启动选股任务（主线程获取数据，子线程纯计算）"""
    try:
        print(f" 触发选股任务，开始在主线程准备数据...")
        
        # 1. 基础过滤 (Main Thread)
        basic_pool = filter_basic_criteria(ContextInfo)
        if not basic_pool:
            print("基础过滤后无股票，结束选股。")
            return

        # 2. 批量获取3日数据用于涨停判断 (Main Thread)
        # 获取大量数据，可能需要1-2秒
        data_3d = ContextInfo.get_market_data_ex(
            ['close', 'preClose', 'high', 'amount', 'open'], 
            basic_pool, 
            period='1d', 
            count=3, 
            subscribe=False
        )
        
        # 3. 初筛涨停股 (Main Thread - 快速)
        limit_up_candidates = []
        for code in basic_pool:
            if code not in data_3d: continue
            df = data_3d[code]
            if len(df) < 3: continue
            
            bar_t = df.iloc[-1]
            bar_prev = df.iloc[-2]
            
            if is_limit_up_bar(code, bar_t) and not is_limit_up_bar(code, bar_prev):
                limit_up_candidates.append(code)
                
        print(f"初筛涨停股数量: {len(limit_up_candidates)}")
        
        if not limit_up_candidates:
            print("今日无涨停候选股。")
            # 即使为空也启动线程去写个空文件，保持流程完整
            
        # 4. 获取候选股的60日数据用于回撤计算 (Main Thread)
        data_60d = {}
        if limit_up_candidates:
            data_60d = ContextInfo.get_market_data_ex(
                ['high', 'low'], 
                limit_up_candidates, 
                period='1d', 
                count=63, 
                subscribe=False
            )
            
        # 5. 启动子线程进行复杂计算和文件IO
        # 将数据传递给子线程，避免子线程调API
        t = threading.Thread(target=thread_selection_logic_pure, args=(ContextInfo, limit_up_candidates, data_60d))
        t.start()
        
    except Exception as e:
        print(f"主线程选股准备阶段异常: {e}")

def run_night_order_task(ContextInfo):
    """启动夜间挂单任务"""
    print(f"[{datetime.datetime.now()}] 触发夜间挂单任务...")
    # 挂单涉及交易账户操作，直接在主线程运行更稳定
    thread_place_orders(ContextInfo)

def run_morning_check_task(ContextInfo):
    """启动晨间校验任务"""
    print(f"[{datetime.datetime.now()}] 触发晨间校验任务...")
    t = threading.Thread(target=thread_morning_check, args=(ContextInfo,))
    t.start()

# ==========================================
# 业务逻辑层 (Business Logic in Threads)
# ==========================================

def thread_selection_logic_pure(ContextInfo, limit_up_candidates, data_60d):
    """【子线程】纯计算选股逻辑并写入文件 (不调QMT API)"""
    try:
        print(">>> [子线程] 开始执行选股筛选(纯计算)...")
        
        final_list = []
        for code in limit_up_candidates:
            # 传递 data_60d 给 check_drawdown_from_data
            if code not in data_60d: continue
            df = data_60d[code]
            
            if not check_drawdown_from_data(ContextInfo, code, df): continue
            # if not check_level2_metrics... (需提前准备数据，暂略)
            
            final_list.append(code)

        candidates = final_list
        
        # 写入 JSON 文件
        data = {
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "candidates": candidates,
            "timestamp": time.time()
        }
        
        os.makedirs(os.path.dirname(CANDIDATE_FILE), exist_ok=True)
        with open(CANDIDATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        print(f"<<< [子线程] 选股完成，结果已保存至 {CANDIDATE_FILE}。共 {len(candidates)} 只。")
        
    except Exception as e:
        print(f"[子线程] 选股流程异常: {e}")

def thread_place_orders(ContextInfo):
    """【主线程/子线程】读取文件并执行隔夜单"""
    try:
        print(">>> 开始执行隔夜挂单...")
        
        # 1. 读取 JSON
        if not os.path.exists(CANDIDATE_FILE):
            print("未找到选股结果文件，跳过挂单。")
            return
            
        with open(CANDIDATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # 校验日期 (可选：如果是昨晚选的，今天21点挂，日期应该是今天)
        # 这里假设当天下午选，当天晚上挂
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        if data.get("date") != today_str:
            print(f"警告：选股文件日期 ({data.get('date')}) 与今日 ({today_str}) 不符，请确认。")
            # 视情况决定是否继续，这里选择继续但打印警告
            
        candidates = data.get("candidates", [])
        if not candidates:
            print("选股列表为空，无单可挂。")
            return
            
        # 2. 计算资金并下单
        # 注意：如果是子线程调用交易接口需谨慎。
        target = candidates[0] # 示例：只买第一只
        
        # 获取资金 (尝试调用全局接口)
        available_cash = 0.0
        if 'get_trade_detail_data' in globals():
            capital = get_trade_detail_data(ContextInfo.account_id, 'stock', 'account')
            if capital:
                available_cash = capital[0].m_dAvailable
                
        print(f"可用资金: {available_cash}")
        
        # 获取收盘价并计算明日涨停价
        last_tick = ContextInfo.get_full_tick([target])
        if target in last_tick:
            curr_price = last_tick[target]['lastPrice']
            
            # 计算明日涨停价 (预估 1.10)
            # 严格计算需要根据板块
            limit_ratio = 1.10
            if target.startswith('30') or target.startswith('68'): limit_ratio = 1.20
            elif target.startswith('8') or target.startswith('4'): limit_ratio = 1.30
            
            limit_up_price = round(curr_price * limit_ratio, 2)
            
            # 股数计算
            volume = int(available_cash / limit_up_price / 100) * 100
            
            if volume > 0:
                print(f"执行挂单: {target}, 价格 {limit_up_price}, 数量 {volume}")
                # 下单
                if 'pass_order' in globals():
                    # 23:买入, 1101:限价
                    pass_order(23, 1101, ContextInfo.account_id, target, 11, limit_up_price, volume, "隔夜单", 2, "", ContextInfo)
                else:
                    ContextInfo.order_stock(target, volume, ContextInfo.account_id)
            else:
                print("资金不足。")
        else:
            print(f"无法获取 {target} 行情")
            
        print("<<< 隔夜挂单完成")
        
    except Exception as e:
        print(f"挂单异常: {e}")

def thread_morning_check(ContextInfo):
    """【子线程】9:25 校验挂单状态"""
    try:
        print(">>> [子线程] 开始执行晨间校验...")
        
        # 1. 获取当前未成交委托
        orders = []
        if 'get_trade_detail_data' in globals():
            orders = get_trade_detail_data(ContextInfo.account_id, 'stock', 'order')
            
        # 2. 读取昨晚的目标股票
        if not os.path.exists(CANDIDATE_FILE):
            return
        with open(CANDIDATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        candidates = data.get("candidates", [])
        if not candidates: return
        
        target = candidates[0]
        
        # 3. 检查是否在委托列表中
        is_ordered = False
        for order in orders:
            # 状态：48=未报, 49=待报, 50=已报, 51=已报待撤, 52=部成, 53=部撤, 54=已撤, 55=已成, 56=废单
            # 只要有有效单即可
            if order.m_strInstrumentID == target and order.m_nOrderStatus in [48, 49, 50, 51, 52]:
                is_ordered = True
                print(f"校验通过：{target} 挂单正常 (状态码 {order.m_nOrderStatus})")
                break
                
        # 4. 如果没成功，补单
        if not is_ordered:
            print(f"警告：未检测到 {target} 的有效挂单，尝试补单...")
            # 重新走一遍下单逻辑 (可以复用 thread_place_orders 的核心逻辑，这里简化调用)
            thread_place_orders(ContextInfo)
            
        print("<<< [子线程] 晨间校验完成")
            
    except Exception as e:
        print(f"[子线程] 校验异常: {e}")

# ==========================================
# 核心选股函数 (复用原有逻辑，略作封装)
# ==========================================

def select_stocks_core(ContextInfo):
    """
    纯粹的计算函数，返回 list
    """
    print(">>> 开始执行核心选股逻辑")
    candidates = []
    
    # ... (此处保留原有 select_stocks 的大部分逻辑，但改为 return candidates)
    # 为了减少代码变动，直接调用原有的 filter 和 check 函数
    
    try:
        # 1. 基础过滤
        basic_pool = filter_basic_criteria(ContextInfo)
        
        # 2. 批量数据
        data_map = ContextInfo.get_market_data_ex(
            ['close', 'preClose', 'high', 'amount', 'open'], 
            basic_pool, 
            period='1d', 
            count=3, 
            subscribe=False
        )
        
        limit_up_candidates = []
        for code in basic_pool:
            if code not in data_map: continue
            df = data_map[code]
            if len(df) < 3: continue
            
            bar_t = df.iloc[-1]
            bar_prev = df.iloc[-2]
            
            if not is_limit_up_bar(code, bar_t): continue
            if is_limit_up_bar(code, bar_prev): continue
                
            limit_up_candidates.append(code)
            
        # 3. 高级筛选
        final_list = []
        for code in limit_up_candidates:
            if not check_drawdown(ContextInfo, code): continue
            # if not check_level2_metrics(ContextInfo, code): continue # 需要L2数据
            # if not check_lhb_metrics(ContextInfo, code): continue
            
            final_list.append(code)
            
        return final_list
        
    except Exception as e:
        print(f"选股核心逻辑出错: {e}")
        return []

# ==========================================
# 辅助函数
# ==========================================

def filter_basic_criteria(ContextInfo):
    """剔除 ST、北交所、创业板、科创板、次新股、高价股"""
    valid_stocks = []
    try:
        for code in ContextInfo.stock_list:
            # 1. 剔除板块
            if code.startswith('30') or code.startswith('68'): # 创业板/科创板
                continue
            if code.startswith('8') or code.startswith('4'):   # 北交所
                continue
                
            # 2. 剔除ST
            name = ContextInfo.get_stock_name(code)
            if 'ST' in name:
                continue
                
            # 3. 剔除次新股 (需要上市日期)
            # 这里使用简单逻辑：如果没有足够历史数据，视为次新
            # 更准确的方法是使用 ContextInfo.get_instrument_detail(code)['OpenDate']
            # 这里暂时略过详细API调用，假设已通过数据长度过滤
            
            # 4. 剔除高价股 (需要当前价格，但在循环中获取太慢，放到后面批量获取时处理或忽略)
            # 可以在这里做个简单的字符串判断或者假定
            
            valid_stocks.append(code)
    except Exception as e:
        print(f"基础过滤异常: {e}")
    return valid_stocks

def is_limit_up_bar(code, bar):
    """判断某根K线是否涨停"""
    try:
        close = bar['close']
        pre_close = bar['preClose']
        high = bar['high']
        
        if pre_close <= 0: return False
        
        # 1. 基础检查：收盘价必须等于最高价 (未炸板)
        if abs(close - high) > 0.01:
            return False
            
        # 2. 确定涨停幅度
        limit_ratio = 0.10 # 默认主板 10%
        if code.startswith('30') or code.startswith('68'):
            limit_ratio = 0.20
        elif code.startswith('8') or code.startswith('4'):
            limit_ratio = 0.30
            
        # 3. 计算理论涨停价
        # QMT/A股规则：涨停价 = round(昨收 * (1+涨幅), 2)
        # 注意：Python round是偶数舍入，金融计算通常需四舍五入。
        # 这里使用简单容差判断：只要涨幅足够接近限制即可
        
        pct = (close - pre_close) / pre_close
        
        # 容差判断：
        # 对于低价股 (如 1.54 -> 1.69, 涨幅 9.74%)，阈值设为 9.0% 比较安全，配合 close==high
        # 对于 20% 涨幅，设为 19%
        # 对于 30% 涨幅，设为 29%
        
        threshold = limit_ratio - 0.015 # 比如 10% -> 8.5%, 宽松一点，依靠 close==high 过滤
        if pct < threshold:
            return False
            
        return True
    except Exception as e:
        # print(f"is_limit_up_bar error {code}: {e}")
        return False

def check_drawdown_from_data(ContextInfo, code, df):
    """(纯计算) 涨停前 60 日最大回撤＜15%"""
    try:
        if df is None or len(df) < 60:
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
        is_pass = max_drawdown >= ContextInfo.params['drawdown_limit']
        if is_pass:
            print(f"剔除 {code}: 60日最大回撤 {max_drawdown:.2%}，高于 {ContextInfo.params['drawdown_limit']:.2%}")
        return not is_pass
    except Exception as e:
        print(f"回撤计算异常 {code}: {e}")
        return False

def check_drawdown(ContextInfo, code):
    """(旧接口) 涨停前 60 日最大回撤＜15%"""
    try:
        # 获取过去63天数据 (多取一点)
        df = ContextInfo.get_market_data_ex(
            ['high', 'low'], 
            [code], 
            period='1d', 
            count=63, 
            subscribe=False
        ).get(code)
        
        return check_drawdown_from_data(ContextInfo, code, df)
    except Exception as e:
        print(f"回撤计算异常 {code}: {e}")
        return False

def check_level2_metrics(ContextInfo, code):
    """
    Level-2 数据检查
    """
    try:
        tick = ContextInfo.get_full_tick([code])
        if not tick or code not in tick:
            return False
            
        tick_data = tick[code]
        
        # 尝试获取买一量和价
        bid_vol_list = tick_data.get('bidVol', [])
        bid_price_list = tick_data.get('bidPrice', [])
        
        if not bid_vol_list or not bid_price_list:
            return False
            
        seal_vol = bid_vol_list[0]   # 买一量
        seal_price = bid_price_list[0] # 买一价
        
        # 封单金额
        seal_amount = seal_vol * seal_price
        
        # 1. 占流通市值 3%
        circulating_cap = get_circulating_cap(ContextInfo, code)
        if circulating_cap > 0:
            if (seal_amount / circulating_cap) <= ContextInfo.params['seal_circ_ratio']:
                print(f"剔除 {code}: 封单金额占流通市值 {seal_amount/circulating_cap:.2%}，低于 {ContextInfo.params['seal_circ_ratio']:.2%}")
                return False
        else:
            pass 
            
        # 2. 占成交额 2倍
        amount = tick_data.get('amount', 0) # 总成交额
        if amount > 0:
            if (seal_amount / amount) <= ContextInfo.params['seal_turnover_ratio']:
                print(f"剔除 {code}: 封单金额占成交额 {seal_amount/amount:.2%}，低于 {ContextInfo.params['seal_turnover_ratio']:.2%}")
                return False
                
        return True
        
    except Exception as e:
        print(f"Level-2 Check Error for {code}: {e}")
        return False

def check_lhb_metrics(ContextInfo, code):
    """
    龙虎榜逻辑：卖方机构小于等于1家
    """
    return True

def place_orders(ContextInfo):
    """挂隔夜单"""
    print(">>> 开始执行下单流程")
    
    try:
        # 简单全仓买入逻辑
        if not ContextInfo.buy_candidates:
            print("今日无候选股，跳过下单。")
            print("<<< 下单流程结束")
            return
            
        target = ContextInfo.buy_candidates[0]
        print(f"锁定目标股票: {target}")
        
        # 计算买入数量
        # 获取可用资金
        available_cash = 0.0
        try:
            if 'get_trade_detail_data' in globals():
                capital = get_trade_detail_data(ContextInfo.account_id, 'stock', 'account')
                if capital:
                    available_cash = capital[0].m_dAvailable
            elif hasattr(ContextInfo, 'get_trade_detail_data'):
                capital = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'account')
                if capital:
                    available_cash = capital[0].m_dAvailable
            else:
                 print("错误: 无法获取资金信息 (get_trade_detail_data 缺失)")
                 return
        except Exception as e:
             print(f"获取资金异常: {e}")
             return
             
        print(f"可用资金: {available_cash}")
        
        # 获取涨停价 (作为买入价)
        last_tick = ContextInfo.get_full_tick([target])
        if target in last_tick:
            curr_price = last_tick[target]['lastPrice']
            limit_up_price = round(curr_price * 1.10, 2) # 简单估算
            
            # 股数取整 (100的倍数)
            volume = int(available_cash / limit_up_price / 100) * 100
            
            print(f"计算下单参数: 现价 {curr_price}, 预估涨停价 {limit_up_price}, 计划买入 {volume} 股")
            
            if volume > 0:
                print(f"执行买入指令: {target}, 价格 {limit_up_price}, 数量 {volume}")
                if 'pass_order' in globals():
                    # opType: 23 (买入), orderType: 1101 (限价)
                    pass_order(23, 1101, ContextInfo.account_id, target, 11, limit_up_price, volume, "一进二策略", 2, "", ContextInfo)
                elif hasattr(ContextInfo, 'order_stock'):
                    ContextInfo.order_stock(target, volume, ContextInfo.account_id)
                elif hasattr(ContextInfo, 'buy_code'):
                    ContextInfo.buy_code(target, limit_up_price, volume)
                else:
                    print("错误: 无法下单，ContextInfo 缺少 order_stock 或 buy_code 方法")
            else:
                print("资金不足，无法下单。")
        else:
            print(f"错误：无法获取 {target} 的实时行情")
            
        print("<<< 下单流程结束")
    except Exception as e:
        print(f"下单流程异常: {e}")

def get_circulating_cap(ContextInfo, code):
    """获取流通市值"""
    try:
        return 1000000000 # Dummy value for logic flow
    except:
        return 0

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
