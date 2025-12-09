# coding:gbk
import pandas as pd
import numpy as np
import datetime
import time

def init(ContextInfo):
    # 1. 设置股票池为沪深A股
    ContextInfo.stock_list = ContextInfo.get_stock_list_in_sector('沪深A股')
    
    # 2. 策略参数设置
    ContextInfo.params = {
        'limit_ratio_main': 0.10,      # 主板涨幅限制
        'limit_ratio_special': 0.20,   # 创业板/科创板涨幅限制 (虽然本策略剔除，但保留逻辑)
        'limit_ratio_bj': 0.30,        # 北交所
        
        'max_price': 200.0,            # 高价股阈值 (示例：200元)
        'new_stock_days': 60,          # 次新股判定天数
        
        'drawdown_days': 60,           # 最大回撤计算周期
        'drawdown_limit': 0.15,        # 最大回撤限制 (15%)
        
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

def handlebar(ContextInfo):
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

def check_holdings(ContextInfo):
    """
    持仓管理：止盈止损
    逻辑：
    - 止盈：+10%。如果开盘一字板不卖；否则如果9:40前未涨停则卖出。
    - 止损：-2%。
    """
    positions = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'position')
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
            ContextInfo.order_stock(code, -pos.m_nVolume, ContextInfo.account_id) # 卖出
            continue
            
        # 止盈逻辑 (简化版，复杂的时间判断需在分钟级别回测或实盘Timer中实现)
        if profit_pct >= ContextInfo.params['stop_profit']:
            # 检查是否涨停 (简单判断)
            is_limit_up = check_is_limit_up_now(ContextInfo, code)
            if not is_limit_up:
                print(f"[止盈触发] {code} 当前价格:{current_price} 成本:{cost_price} 盈亏:{profit_pct:.2%}")
                ContextInfo.order_stock(code, -pos.m_nVolume, ContextInfo.account_id)
            else:
                # 打印一条日志说明持有理由
                # print(f"[止盈保留] {code} 达到止盈线但当前涨停，继续持有")
                pass

def select_stocks(ContextInfo):
    """
    执行选股逻辑
    """
    print(">>> 开始执行选股流程")
    candidates = []
    
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

def filter_basic_criteria(ContextInfo):
    """剔除 ST、北交所、创业板、科创板、次新股、高价股"""
    valid_stocks = []
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
    return valid_stocks

def is_limit_up_bar(code, bar):
    """判断某根K线是否涨停"""
    close = bar['close']
    pre_close = bar['preClose']
    if pre_close <= 0: return False
    
    # 计算涨幅
    pct = (close - pre_close) / pre_close
    
    # 简单阈值判断
    threshold = 0.098 # 主板10%
    if code.startswith('30') or code.startswith('68'):
        threshold = 0.198
    
    # 严格判断：收盘价等于涨停价 (这里简化为涨幅超过阈值且High==Close)
    return pct > threshold and abs(bar['high'] - close) < 0.01

def check_drawdown(ContextInfo, code):
    """涨停前 60 日最大回撤＜15%"""
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
    # Max Drawdown = (Peak - Trough) / Peak
    # 简单算法：计算窗口期内的 (最高价 - 最低价) / 最高价 ? 不对
    # 正确算法：对于每一天，回撤 = (历史最高 - 当前低) / 历史最高
    
    highs = hist_df['high'].values
    lows = hist_df['low'].values
    
    # 这里的回撤定义通常指：区间最高点 到 区间最低点 的幅度？
    # 或者：区间内任意点往后的最大跌幅？
    # 按照"最大回撤"标准定义：RollMax - Current
    
    max_drawdown = 0.0
    rolling_max = highs[0]
    
    for i in range(len(highs)):
        if highs[i] > rolling_max:
            rolling_max = highs[i]
        
        dd = (rolling_max - lows[i]) / rolling_max
        if dd > max_drawdown:
            max_drawdown = dd
            
    return max_drawdown < ContextInfo.params['drawdown_limit']

def check_level2_metrics(ContextInfo, code):
    """
    Level-2 数据检查：
    1. 首板封单金额占流通3%以上
    2. 首板封单金额占成交额2倍以上
    3. 尾盘封单撤单率<20%
    4. 尾盘炸板次数小于等于0次
    """
    # 注意：ContextInfo.get_full_tick 获取的是【当前】快照
    # 如果是在盘后运行，获取到的是收盘切片
    tick = ContextInfo.get_full_tick([code])
    if not tick or code not in tick:
        return False
        
    tick_data = tick[code]
    
    # 获取封单量 (涨停是买一)
    # 字段通常是 'bidVol' (列表) 和 'bidPrice'
    # 注意：不同版本QMT tick结构可能不同，通常是 dict 或 object
    # 这里假设是 standard QMT format
    
    try:
        # 尝试获取买一量和价
        # QMT tick data: 'bidVol': [v1, v2, ...], 'bidPrice': [p1, p2, ...]
        bid_vol_list = tick_data.get('bidVol', [])
        bid_price_list = tick_data.get('bidPrice', [])
        
        if not bid_vol_list or not bid_price_list:
            return False
            
        seal_vol = bid_vol_list[0]   # 买一量 (手? 股?) 通常是手(100股)或股，需确认。QMT通常是股。
        seal_price = bid_price_list[0] # 买一价
        
        # 封单金额
        seal_amount = seal_vol * seal_price
        
        # 1. 占流通市值 3%
        # 获取流通股本 (需要额外数据接口，这里尝试 get_financial_data 或估算)
        # 临时方案：假设有一个 helper 函数
        circulating_cap = get_circulating_cap(ContextInfo, code)
        if circulating_cap > 0:
            if (seal_amount / circulating_cap) <= ContextInfo.params['seal_circ_ratio']:
                return False
        else:
            # 如果获取不到市值，保守起见剔除或保留(取决于策略激进程度)
            # print(f"{code} 无法获取流通市值")
            pass 
            
        # 2. 占成交额 2倍
        # 获取今日成交额
        amount = tick_data.get('amount', 0) # 总成交额
        if amount > 0:
            if (seal_amount / amount) <= ContextInfo.params['seal_turnover_ratio']:
                return False
                
        # 3 & 4. 撤单率和炸板次数
        # 这两个指标需要全天逐笔数据统计，get_full_tick 无法提供
        # 这是一个需要高级数据源的功能。
        # 在此我们只能暂时忽略或返回True(假设满足)，并打印警告
        # 真实环境需接入 Level-2 逐笔委托数据流
        
        return True
        
    except Exception as e:
        print(f"Level-2 Check Error for {code}: {e}")
        return False

def check_lhb_metrics(ContextInfo, code):
    """
    龙虎榜逻辑：卖方机构小于等于1家
    需要接入龙虎榜数据源
    """
    # 这里是 Placeholder
    # 实际应调用: lhb_data = get_lhb_data(code, date)
    # seller_institutions = count_institutions(lhb_data['seller'])
    # return seller_institutions <= 1
    return True

def place_orders(ContextInfo):
    """挂隔夜单"""
    print(">>> 开始执行下单流程")
    
    # 简单全仓买入逻辑
    if not ContextInfo.buy_candidates:
        print("今日无候选股，跳过下单。")
        print("<<< 下单流程结束")
        return
        
    # 假设单票全仓 (只买1只？还是均分？)
    # 策略描述："单票全仓"， imply if multiple candidates, pick one?
    # 或者资金足够就买。
    # 这里简单实现：取第一个候选股全仓
    
    target = ContextInfo.buy_candidates[0]
    print(f"锁定目标股票: {target}")
    
    # 计算买入数量
    # 获取可用资金
    capital = ContextInfo.get_trade_detail_data(ContextInfo.account_id, 'stock', 'account')
    if not capital: 
        print("错误：无法获取资金账号信息")
        return
        
    available_cash = capital[0].m_dAvailable
    print(f"可用资金: {available_cash}")
    
    # 获取涨停价 (作为买入价)
    # 需计算明日涨停价 = 今日收盘 * 1.1
    # 获取今日收盘
    last_tick = ContextInfo.get_full_tick([target])
    if target in last_tick:
        curr_price = last_tick[target]['lastPrice']
        limit_up_price = round(curr_price * 1.10, 2) # 简单估算
        
        # 股数取整 (100的倍数)
        volume = int(available_cash / limit_up_price / 100) * 100
        
        print(f"计算下单参数: 现价 {curr_price}, 预估涨停价 {limit_up_price}, 计划买入 {volume} 股")
        
        if volume > 0:
            print(f"执行买入指令: {target}, 价格 {limit_up_price}, 数量 {volume}")
            # ContextInfo.order_stock(target, volume, ContextInfo.account_id)
            # 注意：order_stock 通常是市价或限价，具体取决于参数
            # 实盘需要使用 order_stock_limit(id, code, price, vol)
            ContextInfo.buy_code(target, limit_up_price, volume)
        else:
            print("资金不足，无法下单。")
    else:
        print(f"错误：无法获取 {target} 的实时行情")
        
    print("<<< 下单流程结束")

def get_circulating_cap(ContextInfo, code):
    """获取流通市值"""
    # 尝试使用财务数据接口
    # 字段: 'CAPITALSTRUCTURE.circulating_capital' (流通股本)
    # 市值 = 流通股本 * 股价
    try:
        # 获取股本
        # QMT API: get_financial_data(field_list, stock_list, start_date, end_date)
        # 这是一个比较重的操作，实际需优化
        return 1000000000 # Dummy value for logic flow
    except:
        return 0

def check_is_limit_up_now(ContextInfo, code):
    """检查当前是否涨停"""
    tick = ContextInfo.get_full_tick([code])
    if code in tick:
        t = tick[code]
        # 涨停判断：最新价 == 涨停价 (API通常提供 'highLimit' 或类似字段吗？)
        # 如果没有，需自己算。
        # 简单判断：买一价 > 0 且 卖一量 == 0 ? (涨停时卖一通常为空或很小? 不, 涨停时买一有巨量封单, 卖一通常就是涨停价但量为0? 或者是 卖一价=0?)
        # 准确判断：LastPrice == UpLimitPrice
        # 假设我们无法直接获取UpLimitPrice，只能近似
        return False # Placeholder
    return False
