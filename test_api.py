#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
迅投SDK API测试脚本
用于验证所有API接口是否正常工作
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

print("=" * 60)
print("迅投SDK API测试")
print("=" * 60)
print()

# 测试1：导入模块
print("测试1: 导入模块...")
try:
    # 添加xtquant路径
    xtquant_path = Path.cwd() / "xtquant"
    if xtquant_path.exists():
        sys.path.insert(0, str(xtquant_path))
        print(f"  已添加路径: {xtquant_path}")
    else:
        print(f"  [ERROR] 未找到 xtquant 目录")
        sys.exit(1)

    import xtdata
    import xtquant
    from xtquant import xttype, xttrader
    print("✅ 模块导入成功")
except ImportError as e:
    print(f"❌ 模块导入失败: {e}")
    print("\n解决方案:")
    print("  运行: python quick_test.py")
    sys.exit(1)

print()

# 测试2：获取股票列表
print("测试2: 获取股票列表...")
try:
    stock_list = xtdata.query_stock_list('沪深A股')
    print(f"✅ 成功获取 {len(stock_list)} 只股票")
    print(f"   示例: {stock_list[:5]}")
except Exception as e:
    print(f"❌ 获取股票列表失败: {e}")
    traceback.print_exc()

print()

# 测试3：获取股票名称
print("测试3: 获取股票名称...")
try:
    if stock_list:
        code = stock_list[0]
        name = xtdata.query_stock_name(code)
        print(f"✅ 成功获取 {code} 的名称: {name}")
    else:
        print("⚠️ 股票列表为空，跳过测试")
except Exception as e:
    print(f"❌ 获取股票名称失败: {e}")
    traceback.print_exc()

print()

# 测试4：获取历史数据
print("测试4: 获取历史数据...")
try:
    if stock_list:
        code = stock_list[0]
        data = xtdata.get_market_data_ex(
            field_list=['close', 'preClose', 'high'],
            stock_list=[code],
            period='1d',
            count=3
        )
        if data and code in data:
            df = data[code]
            print(f"✅ 成功获取 {code} 的历史数据")
            print(f"   数据形状: {df.shape}")
            print(f"   列名: {list(df.columns)}")
            print(f"   最新数据: {df.iloc[-1].to_dict()}")
        else:
            print(f"⚠️ 未获取到 {code} 的数据")
    else:
        print("⚠️ 股票列表为空，跳过测试")
except Exception as e:
    print(f"❌ 获取历史数据失败: {e}")
    traceback.print_exc()

print()

# 测试5：获取实时行情
print("测试5: 获取实时行情...")
try:
    if stock_list:
        code = stock_list[0]
        data = xtdata.get_latest_quota([code])
        if data and code in data:
            quota = data[code]
            print(f"✅ 成功获取 {code} 的实时行情")
            print(f"   最新价: {quota.get('lastPrice', 'N/A')}")
            print(f"   最高价: {quota.get('high', 'N/A')}")
            print(f"   最低价: {quota.get('low', 'N/A')}")
        else:
            print(f"⚠️ 未获取到 {code} 的实时行情")
    else:
        print("⚠️ 股票列表为空，跳过测试")
except Exception as e:
    print(f"❌ 获取实时行情失败: {e}")
    traceback.print_exc()

print()

# 测试6：交易接口
print("测试6: 交易接口...")
try:
    trader = xttrader.xt_trader()
    print("✅ 交易接口初始化成功")
    # 注意：这里只测试接口可用性，不实际交易
    print("   注意：实际交易需要有效的账户和密码")
except Exception as e:
    print(f"❌ 交易接口初始化失败: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("测试完成")
print("=" * 60)
print()
print("如果所有测试都显示 ✅，说明API正常工作")
print("如果有任何 ❌，请检查：")
print("  1. miniQMT是否正常运行")
print("  2. xtquant库是否正确安装")
print("  3. 账户权限是否充足")
print()