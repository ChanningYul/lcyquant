#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
QMT连接测试脚本
"""

import sys
from pathlib import Path

# 添加xtquant路径
xtquant_path = Path(__file__).parent / "xtquant"
if xtquant_path.exists():
    sys.path.insert(0, str(xtquant_path))

print("="*60)
print("QMT连接测试")
print("="*60)

from xtquant import xtdata

# 常见的QMT端口
ports_to_try = [
    None,          # 默认端口
    6166,          # 常见QMT端口
    9999,          # 备用端口
    7777,          # 另一个常见端口
]

# 常见的QMT IP
ips_to_try = [
    '',            # 本地
    '127.0.0.1',   # 本地IP
    'localhost',   # 本地主机
]

print("\n正在尝试连接QMT...")

for ip in ips_to_try:
    for port in ports_to_try:
        try:
            print(f"\n尝试连接: ip={ip}, port={port}")
            xtdata.connect(ip, port)
            print(f"  [SUCCESS] 连接成功！")

            # 测试获取股票列表
            print("  测试获取股票列表...")
            stock_list = xtdata.get_stock_list_in_sector('沪深A股')
            print(f"  [SUCCESS] 获取到 {len(stock_list)} 只股票")

            # 断开连接
            xtdata.disconnect()
            print("  [INFO] 已断开连接")

            print("\n" + "="*60)
            print("QMT连接成功！")
            print("="*60)
            print(f"\n有效配置: ip={ip}, port={port}")
            print("\n在select.py中使用此配置：")
            print(f"  xtdata.connect('{ip}', {port})")

            sys.exit(0)

        except Exception as e:
            print(f"  [FAILED] {str(e)[:100]}")

print("\n" + "="*60)
print("所有连接尝试都失败")
print("="*60)
print("""
请检查：
1. QMT客户端是否完全启动并登录？
2. QMT版本是否为专业版或极简版？
3. 是否以管理员权限运行QMT？
4. QMT安装路径是否正确？
5. 防火墙是否阻止了连接？
""")
