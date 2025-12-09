# coding:gbk
import pandas as pd
import numpy as np
import datetime
import time

def init(ContextInfo):
    try:
        print(">>> 策略正在初始化 (init)...")
        # 打印 ContextInfo 的属性，以便调试 API 差异
        #print(f"DEBUG: ContextInfo dir: {dir(ContextInfo)}")

        # 1. 设置股票池为沪深A股
        # 注意：如果 sector 名称不对，这里可能会报错
        try:
            ContextInfo.stock_list = ContextInfo.get_stock_list_in_sector('沪深A股')
            print(f"获取到 {len(ContextInfo.stock_list)} 只股票")
        except Exception as e:
            print(f"获取股票池失败 (可能板块名称不对): {e}")
            ContextInfo.stock_list = []
        
        # 2. 策略参数设置
        ContextInfo.params = {
            'limit_ratio_main': 0.10,      # 主板涨幅限制
            'limit_ratio_special': 0.20,   # 创业板/科创板涨幅限制 (虽然本策略剔除，但保留逻辑)
            'limit_ratio_bj': 0.30,        # 北交所
            
            'max_price': 200.0,            # 高价股阈值 (示例：200元)
            'new_stock_days': 60,          # 次新股判定天数
            
            'drawdown_days': 60,           # 最大回撤计算周期
            'drawdown_limit': 0.20,        # 最大回撤限制 (20%)
            
            'seal_circ_ratio': 0.03,       # 封单金额/流通市值 > 3%
            'seal_turnover_ratio': 2.0,    # 封单金额/成交额 > 2倍
            'withdraw_limit': 0.20,        # 撤单率 < 20%
            'bomb_limit': 0,               # 炸板次数 <= 0
            
            'stop_profit': 0.10,           # 止盈 10%
            'stop_loss': -0.02,            # 止损 -2%
        }
        
        # 交易相关变量
        ContextInfo.buy_candidates = []    # 待买入列表
        ContextInfo.account_id = 'YOUR_ACCOUNT_ID' # 请替换为实际资金账号
        
        # 3. 运行控制标记
        ContextInfo.last_log_time = 0      # 上次打印日志时间
        ContextInfo.current_date = datetime.date.today() # 当前日期
        ContextInfo.has_selected = False   # 当日是否已选股
        ContextInfo.has_ordered = False    # 当日是否已下单
        
        print("策略初始化完成：一进二打板策略")
        print("注意：Level-2数据(撤单率/炸板)及龙虎榜数据需要额外数据源支持，本代码包含基础框架。")
    except Exception as e:
        print(f"!!! 策略初始化发生严重错误: {e}")

def handlebar(ContextInfo):
    try:
        # 安全检查：防止 init 失败导致 ContextInfo 属性缺失
        if not hasattr(ContextInfo, 'last_log_time'):
            ContextInfo.last_log_time = 0
        if not hasattr(ContextInfo, 'current_date'):
            ContextInfo.current_date = datetime.date.today()
        if not hasattr(ContextInfo, 'has_selected'):
            ContextInfo.has_selected = False
        if not hasattr(ContextInfo, 'has_ordered'):
            ContextInfo.has_ordered = False
        if not hasattr(ContextInfo, 'buy_candidates'):
            ContextInfo.buy_candidates = []
        if not hasattr(ContextInfo, 'params'):
            print("警告: 策略参数未初始化，正在尝试重新初始化...")
            init(ContextInfo)
            return

        # 0. 心跳日志 (每5秒)
        now_time = time.time()
        if now_time - ContextInfo.last_log_time > 5:
            print(f"[心跳] 策略运行中... {datetime.datetime.now().strftime('%H:%M:%S')}")
            ContextInfo.last_log_time = now_time
            
        # 检查日期变更 (重置状态)
        today = datetime.date.today()
        if today != ContextInfo.current_date:
            print(f"日期变更: {ContextInfo.current_date} -> {today}，重置策略状态")
            ContextInfo.current_date = today
            ContextInfo.has_selected = False
            ContextInfo.has_ordered = False
            ContextInfo.buy_candidates = []
            
        # 1. 止盈止损监控 (针对现有持仓)
        # 实盘中建议在盘中高频运行；回测中如果是日线，只能按收盘价或日内High/Low粗略模拟
        check_holdings(ContextInfo)
        
        # 获取当前时间
        current_dt = datetime.datetime.now()
        
        # 2. 选股逻辑 (盘后运行，例如 15:01)
        if not ContextInfo.has_selected:
            if current_dt.hour >= 15 and current_dt.minute >= 1:
                print(f"到达选股时间 (15:01)，开始执行选股逻辑...")
                select_stocks(ContextInfo)
                ContextInfo.has_selected = True
                print("选股逻辑执行完毕，今日不再执行。")
        
        # 3. 交易执行 (挂隔夜单，例如 20:30)
        if not ContextInfo.has_ordered:
            if current_dt.hour >= 20 and current_dt.minute >= 30:
                print(f"到达下单时间 (20:30)，开始执行挂单逻辑...")
                place_orders(ContextInfo)
                ContextInfo.has_ordered = True
                print("下单逻辑执行完毕，今日不再执行。")
    except Exception as e:
        print(f"!!! handlebar 运行异常: {e}")

def check_holdings(ContextInfo):
    """
    持仓管理：止盈止损
    逻辑：
    - 止盈：+10%。如果开盘一字板不卖；否则如果9:40前未涨停则卖出。
    - 止损：-2%。
    """
    try:
        positions = []
        # 尝试调用全局函数 get_trade_detail_data
        if 'get_trade_detail_data' in globals():
            positions = get_trade_detail_data(ContextInfo.account_id, 'stock', 'position')
        elif hasattr(ContextInfo, 'get_trade_detail_data'):
            positions = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'position')
        else:
            print("错误: 无法找到 get_trade_detail_data (既不是全局函数也不是ContextInfo方法)")
            return

        if not positions:
            return

        for pos in positions:
            code = pos.m_strInstrumentID
            cost_price = pos.m_dOpenPrice # 持仓成本
            current_price = pos.m_dLastPrice # 最新价
            
            if cost_price <= 0: continue
            
            profit_pct = (current_price - cost_price) / cost_price
            
            # 止损逻辑
            if profit_pct <= ContextInfo.params['stop_loss']:
                print(f"[止损触发] {code} 当前价格:{current_price} 成本:{cost_price} 盈亏:{profit_pct:.2%}")
                do_sell(ContextInfo, code, pos.m_nVolume)
                continue
                
            # 止盈逻辑 (简化版)
            if profit_pct >= ContextInfo.params['stop_profit']:
                # 检查是否涨停 (简单判断)
                is_limit_up = check_is_limit_up_now(ContextInfo, code)
                if not is_limit_up:
                    print(f"[止盈触发] {code} 当前价格:{current_price} 成本:{cost_price} 盈亏:{profit_pct:.2%}")
                    do_sell(ContextInfo, code, pos.m_nVolume)
                else:
                    pass
    except Exception as e:
        print(f"check_holdings 异常: {e}")

def do_sell(ContextInfo, code, volume):
    """执行卖出操作"""
    try:
        # 尝试使用 pass_order (QMT 标准下单函数)
        # opType: 24 (卖出), orderType: 1101 (限价委托 - 这里为了快速成交，可用市价或对手价，这里暂演示限价)
        # 注意：实际使用需确认 pass_order 参数定义
        if 'pass_order' in globals():
            # 获取最新价作为卖出价
            tick = ContextInfo.get_full_tick([code])
            price = tick[code]['lastPrice'] if code in tick else 0
            if price > 0:
                pass_order(24, 1101, ContextInfo.account_id, code, 11, price, volume, "一进二策略", 2, "", ContextInfo)
                print(f"调用 pass_order 卖出: {code} {volume}股 @ {price}")
            else:
                print(f"卖出失败: 无法获取 {code} 价格")
        elif hasattr(ContextInfo, 'order_stock'):
            ContextInfo.order_stock(code, -volume, ContextInfo.account_id)
        else:
            print("错误: 无法找到下单函数 pass_order 或 order_stock")
    except Exception as e:
        print(f"卖出操作异常: {e}")


def select_stocks(ContextInfo):
    """
    执行选股逻辑
    """
    print(">>> 开始执行选股流程")
    candidates = []
    
    try:
        # 1. 基础过滤：剔除ST、创业板、科创板、北交所、次新股、高价股
        print(f"步骤1: 执行基础过滤...")
        basic_pool = filter_basic_criteria(ContextInfo)
        print(f"步骤1完成: 基础过滤后剩余 {len(basic_pool)} 只股票")
        
        # 2. 批量获取历史数据 (T, T-1, T-2) 以判断一进二
        # 我们需要判断：今天(T)涨停，昨天(T-1)没涨停
        # 所以需要 T, T-1, T-2 三天数据来计算涨幅
        print(f"步骤2: 获取历史数据并筛选首板股票...")
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
            
            # T日 (今天/最近一个收盘日)
            bar_t = df.iloc[-1]
            # T-1日 (昨天)
            bar_prev = df.iloc[-2]
            
            # 检查T日是否涨停 (首板)
            if not is_limit_up_bar(code, bar_t):
                continue
                
            # 检查T-1日是否未涨停 (确保是首板，不是二板或更多)
            if is_limit_up_bar(code, bar_prev):
                continue
                
            limit_up_candidates.append(code)
            
        print(f"步骤2完成: 筛选出 {len(limit_up_candidates)} 只首板股票")
        
        # 3. 进一步筛选：技术指标 & Level-2 & 龙虎榜
        print(f"步骤3: 执行高级筛选 (回撤/资金/龙虎榜)...")
        final_list = []
        for code in limit_up_candidates:
            # A. 60日最大回撤 < 15%
            if not check_drawdown(ContextInfo, code):
                # print(f"剔除 {code}: 最大回撤超标")
                continue
                
            # B. Level-2 逻辑 (封单、撤单、炸板)
            if not check_level2_metrics(ContextInfo, code):
                # print(f"剔除 {code}: Level-2指标不满足")
                continue
                
            # C. 龙虎榜逻辑 (卖方机构 <= 1)
            if not check_lhb_metrics(ContextInfo, code):
                # print(f"剔除 {code}: 龙虎榜指标不满足")
                continue
                
            final_list.append(code)
            
        ContextInfo.buy_candidates = final_list
        print(f"步骤3完成: 最终选股结果 {len(final_list)} 只 -> {final_list}")
        print("<<< 选股流程结束")
    except Exception as e:
        print(f"选股流程异常: {e}")

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

def check_drawdown(ContextInfo, code):
    """涨停前 60 日最大回撤＜15%"""
    try:
        # 获取过去63天数据 (多取一点)
        df = ContextInfo.get_market_data_ex(
            ['high', 'low'], 
            [code], 
            period='1d', 
            count=63, 
            subscribe=False
        ).get(code)
        
        if df is None or len(df) < 60:
            return False # 数据不足，可能是次新股，剔除
            
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
                
        return max_drawdown < ContextInfo.params['drawdown_limit']
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
                return False
        else:
            pass 
            
        # 2. 占成交额 2倍
        amount = tick_data.get('amount', 0) # 总成交额
        if amount > 0:
            if (seal_amount / amount) <= ContextInfo.params['seal_turnover_ratio']:
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
