# -*- coding: utf-8 -*-
"""
选股脚本配置文件
"""

# =============================================================================
# 基础配置
# =============================================================================

# 股票池配置
STOCK_POOL = {
    'sector': '沪深A股',  # 股票池名称
    'exclude_st': True,  # 是否剔除ST股票
    'exclude_bj': True,  # 是否剔除北交所
    'exclude_gemboard': True,  # 是否剔除创业板/科创板
}

# 策略参数
PARAMS = {
    # 涨停判断参数
    'limit_ratio_main': 0.10,  # 沪深A股涨停幅度
    'limit_ratio_special': 0.20,  # 创业板/科创板涨停幅度
    'limit_ratio_bj': 0.30,  # 北交所涨停幅度
    'limit_threshold_offset': 0.015,  # 涨停阈值偏移（容差）

    # 价格过滤
    'max_price': 200.0,  # 最大持仓价格
    'min_price': 1.0,  # 最小价格（防止低价股）

    # 回撤控制
    'drawdown_limit': 0.20,  # 最大回撤率（20%）

    # 交易参数
    'stop_profit': 0.10,  # 止盈比例
    'stop_loss': -0.02,  # 止损比例

    # L2数据过滤
    'seal_circ_ratio': 0.03,  # 封单对流通市值占比
    'seal_turnover_ratio': 2.0,  # 封单占成交额倍数
}

# =============================================================================
# 定时任务配置
# =============================================================================

# 选股任务调度
SELECTION_SCHEDULE = {
    'hour': 15,  # 执行小时（24小时制）
    'minute': 38,  # 执行分钟
    'timezone': 'Asia/Shanghai',  # 时区
}

# 健康检查间隔（分钟）
HEALTH_CHECK_INTERVAL = 10

# 每日重启时间
DAILY_RESTART = {
    'hour': 23,
    'minute': 59,
}

# =============================================================================
# 文件路径配置
# =============================================================================

PATHS = {
    'candidate_file': 'candidate.json',  # 候选股票文件
    'select_log': 'select.log',  # 选股日志
    'select_detail_log': 'select_detail.log',  # 详细日志
    'scheduler_log': 'select_scheduler.log',  # 调度器日志
    'state_file': 'scheduler_state.json',  # 状态文件
}

# =============================================================================
# 日志配置
# =============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
        },
        'file': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.FileHandler',
            'filename': 'select.log',
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default', 'file'],
            'level': 'INFO',
            'propagate': False
        }
    }
}

# =============================================================================
# 高级筛选配置（可选）
# =============================================================================

ADVANCED_FILTERS = {
    'enable_level2': False,  # 是否启用L2数据筛选
    'enable_lhb': False,  # 是否启用龙虎榜筛选
    'enable_volume': False,  # 是否启用成交量筛选
    'enable_market_cap': False,  # 是否启用市值筛选
}

# 成交量筛选
VOLUME_FILTER = {
    'min_volume_ratio': 2.0,  # 最小量比（当日成交量/5日平均成交量）
    'min_turnover': 100000000,  # 最小成交额（元）
}

# 市值筛选
MARKET_CAP_FILTER = {
    'min_market_cap': 1000000000,  # 最小市值（元）
    'max_market_cap': 100000000000,  # 最大市值（元）
}

# =============================================================================
# API配置（根据实际miniQMT接口调整）
# =============================================================================

API_CONFIG = {
    'timeout': 30,  # API超时时间（秒）
    'retry_times': 3,  # 重试次数
    'retry_interval': 5,  # 重试间隔（秒）
    'batch_size': 100,  # 批量获取数据的批次大小
}

# =============================================================================
# 调试配置
# =============================================================================

DEBUG = {
    'enabled': False,  # 是否启用调试模式
    'save_intermediate_data': False,  # 是否保存中间数据
    'log_sql': False,  # 是否记录SQL
    'mock_data': False,  # 是否使用模拟数据
}

# =============================================================================
# 通知配置（可选）
# =============================================================================

NOTIFICATION = {
    'enable': False,  # 是否启用通知
    'methods': ['email', 'wechat'],  # 通知方式
    'email': {
        'smtp_server': '',
        'smtp_port': 587,
        'username': '',
        'password': '',
        'to_addrs': [],
    },
    'wechat': {
        'webhook_url': '',  # 企业微信机器人webhook
    }
}