#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
股票代码转中文名称脚本 (code to name)
功能：读取candidate.json中的股票代码，转换为中文简称，保存至candiname.json
"""

import sys
import os
import json
import time
import logging
import datetime
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional

# 添加xtquant路径
xtquant_path = Path(__file__).parent / "xtquant"
if xtquant_path.exists():
    sys.path.insert(0, str(xtquant_path))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('c2n.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('Code2Name')

# 文件路径
CANDIDATE_FILE = "candidate.json"
OUTPUT_FILE = "candiname.json"


def load_candidate_stocks() -> List[str]:
    """从candidate.json读取股票代码列表"""
    try:
        if not os.path.exists(CANDIDATE_FILE):
            logger.error(f"文件不存在: {CANDIDATE_FILE}")
            return []

        with open(CANDIDATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        candidates = data.get('candidates', [])
        logger.info(f"加载 {len(candidates)} 只股票代码")
        return candidates

    except Exception as e:
        logger.error(f"加载候选股票失败: {e}")
        return []


def get_stock_names(stock_codes: List[str]) -> Dict[str, str]:
    """
    获取股票中文名称
    优先使用akshare库，其次使用手动映射表，最后使用QMT
    """
    stock_names = {}

    # 方法1：尝试使用akshare
    try:
        import akshare as ak
        logger.info("使用akshare获取股票名称...")

        # 获取A股股票列表
        stock_info = ak.stock_info_a_code_name()
        logger.info(f"akshare获取到 {len(stock_info)} 只股票信息")

        # 创建代码到名称的映射
        name_map = dict(zip(stock_info['code'], stock_info['name']))

        for code in stock_codes:
            # 转换代码格式：603696.SH -> 603696
            clean_code = code.replace('.SH', '').replace('.SZ', '')
            if clean_code in name_map:
                stock_names[code] = name_map[clean_code]
                logger.info(f"{code} -> {name_map[clean_code]}")
            else:
                stock_names[code] = f"未知({code})"
                logger.warning(f"{code} -> 无法在akshare中找到")

        logger.info(f"akshare成功获取 {len([k for k, v in stock_names.items() if not v.startswith('未知')])} 只股票名称")
        return stock_names

    except ImportError:
        logger.warning("akshare未安装，使用手动映射表...")
    except Exception as e:
        logger.warning(f"akshare获取失败: {e}，使用手动映射表...")

    # 方法2：使用手动维护的映射表
    try:
        from stock_names_manual import STOCK_NAMES
        logger.info("使用手动映射表获取股票名称...")

        found_count = 0
        for code in stock_codes:
            if code in STOCK_NAMES:
                stock_names[code] = STOCK_NAMES[code]
                logger.info(f"{code} -> {STOCK_NAMES[code]}")
                found_count += 1
            else:
                stock_names[code] = f"未知({code})"
                logger.warning(f"{code} -> 手动映射表中未找到")

        logger.info(f"手动映射表成功匹配 {found_count} 只股票名称")
        return stock_names

    except ImportError:
        logger.warning("手动映射表不存在，使用QMT...")
    except Exception as e:
        logger.error(f"手动映射表获取失败: {e}，使用QMT...")

    # 方法3：使用QMT（但QMT mini版本可能不返回股票名称）
    try:
        from xtquant import xtdata

        logger.info(f"使用QMT获取 {len(stock_codes)} 只股票的中文名称...")

        # QMT mini版本可能不提供股票名称，使用备用方案
        # 这里我们尝试获取，如果失败则返回带代码的名称
        for i, code in enumerate(stock_codes):
            # 暂时无法从QMT获取股票名称，使用代码作为标识
            stock_names[code] = f"未知({code})"
            logger.warning(f"[{i+1}/{len(stock_codes)}] {code} -> QMT无法获取名称，使用默认")

        return stock_names

    except Exception as e:
        logger.error(f"获取股票名称失败: {e}")

    # 方法4：返回默认名称
    for code in stock_codes:
        stock_names[code] = f"未知({code})"

    return stock_names


def save_stock_names(stock_names: Dict[str, str]):
    """保存股票名称到candiname.json"""
    try:
        # 转换为列表格式，保持与candidate.json相同的结构
        candidates_with_names = []
        for code, name in stock_names.items():
            candidates_with_names.append({
                "code": code,
                "name": name
            })

        data = {
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "candidates": candidates_with_names,
            "timestamp": time.time(),
            "count": len(candidates_with_names)
        }

        os.makedirs(os.path.dirname(OUTPUT_FILE) if os.path.dirname(OUTPUT_FILE) else '.', exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        logger.info(f"结果已保存至 {OUTPUT_FILE}")

    except Exception as e:
        logger.error(f"保存结果失败: {e}")


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("股票代码转中文名称脚本启动")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        # 连接QMT
        logger.info("连接QMT...")
        from xtquant import xtdata
        xtdata.connect()
        logger.info("QMT连接成功")

        # 1. 加载候选股票代码
        stock_codes = load_candidate_stocks()
        if not stock_codes:
            logger.error("未找到候选股票，退出")
            return 1

        # 2. 获取股票中文名称
        stock_names = get_stock_names(stock_codes)

        # 3. 保存结果
        save_stock_names(stock_names)

        # 4. 输出统计
        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info(f"转换完成，耗时: {elapsed:.2f}秒")
        logger.info(f"共转换 {len(stock_names)} 只股票")
        logger.info(f"结果文件: {OUTPUT_FILE}")
        logger.info("=" * 60)

        # 显示前几个示例
        logger.info("转换示例:")
        for i, (code, name) in enumerate(list(stock_names.items())[:5]):
            logger.info(f"  {code} -> {name}")
        if len(stock_names) > 5:
            logger.info(f"  ... (还有 {len(stock_names) - 5} 只)")

        return 0

    except Exception as e:
        logger.error(f"脚本运行异常: {e}", exc_info=True)
        return 1
    finally:
        # 断开QMT连接
        try:
            from xtquant import xtdata
            xtdata.disconnect()
            logger.info("已断开QMT连接")
        except:
            pass


if __name__ == '__main__':
    sys.exit(main())
