from xtquant import xtdata
import datetime


def is_trading_day():
    # 获取今天的日期
    today = datetime.datetime.now().strftime('%Y%m%d')
    # 查询上证指数的交易日历
    trading_dates = xtdata.get_trading_dates('SH', today, today)
    
    return len(trading_dates) > 0