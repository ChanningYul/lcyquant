#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
选股脚本调度器 (miniQMT版本)
实现7x24小时稳定运行，定时执行选股任务
"""

import sys
import os
import time
import signal
import logging
import traceback
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

# 导入选股模块
from select import StockSelector, CANDIDATE_FILE

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('select_scheduler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('SelectionScheduler')


class SelectionScheduler:
    """选股调度器"""

    def __init__(self):
        self.running = False
        self.scheduler = BackgroundScheduler()
        self.selector = StockSelector()
        self.last_run_time = None
        self.start_time = None

    def setup_schedules(self):
        """设置定时任务"""
        logger.info("设置定时任务...")

        # 每天15:38执行选股（避开收盘时间）
        self.scheduler.add_job(
            func=self.run_stock_selection,
            trigger=CronTrigger(hour=15, minute=38),
            id='stock_selection',
            name='选股任务',
            replace_existing=True,
            max_instances=1,  # 防止并发
            coalesce=True  # 合并错过的任务
        )

        # 每天重启一次（防止内存泄漏）
        self.scheduler.add_job(
            func=self.graceful_restart,
            trigger=CronTrigger(hour=23, minute=59),
            id='daily_restart',
            name='每日重启',
            replace_existing=True
        )

        # 健康检查（每10分钟）
        self.scheduler.add_job(
            func=self.health_check,
            trigger=CronTrigger(minute='*/10'),
            id='health_check',
            name='健康检查',
            replace_existing=True
        )

        logger.info("定时任务设置完成")

    def run_stock_selection(self):
        """执行选股任务"""
        try:
            logger.info("=" * 60)
            logger.info("开始执行选股任务")

            start_time = time.time()

            # 初始化数据
            if not self.selector.init_data():
                logger.error("数据初始化失败")
                return False

            # 执行选股
            result = self.selector.run_selection()

            elapsed = time.time() - start_time
            self.last_run_time = start_time

            if result is None:
                logger.error("选股任务执行失败")
                return False

            logger.info(f"选股任务执行成功，耗时: {elapsed:.2f}秒")
            logger.info(f"最终选出 {len(result)} 只股票")
            logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"选股任务异常: {e}", exc_info=True)
            return False

    def graceful_restart(self):
        """优雅重启"""
        logger.info("执行优雅重启...")
        self.running = False

        # 保存状态
        self._save_state()

        # 1秒后重启
        time.sleep(1)
        logger.info("重启进程...")
        import os
        os.execl(sys.executable, sys.executable, *sys.argv)

    def health_check(self):
        """健康检查"""
        try:
            # 检查上次选股时间
            if self.last_run_time:
                hours_since_last = (time.time() - self.last_run_time) / 3600
                if hours_since_last > 24:
                    logger.warning(f"距离上次选股已超过24小时: {hours_since_last:.1f}小时")
                else:
                    logger.debug(f"距离上次选股: {hours_since_last:.1f}小时")

            # 检查候选文件是否存在
            if os.path.exists(CANDIDATE_FILE):
                file_time = os.path.getmtime(CANDIDATE_FILE)
                hours_old = (time.time() - file_time) / 3600
                if hours_old > 24:
                    logger.warning(f"候选文件已超过24小时未更新")
            else:
                logger.warning("候选文件不存在")

            # 检查内存使用
            try:
                import psutil
                memory_percent = psutil.virtual_memory().percent
                if memory_percent > 80:
                    logger.warning(f"内存使用率过高: {memory_percent}%")
                else:
                    logger.debug(f"内存使用率: {memory_percent}%")
            except ImportError:
                logger.debug("psutil未安装，跳过内存检查")

            logger.debug("健康检查完成")

        except Exception as e:
            logger.error(f"健康检查异常: {e}")

    def _save_state(self):
        """保存程序状态"""
        try:
            state = {
                'last_run_time': self.last_run_time,
                'start_time': self.start_time,
                'timestamp': time.time()
            }
            with open('scheduler_state.json', 'w') as f:
                import json
                json.dump(state, f)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"收到信号 {signum}，准备退出...")
        self.running = False

    def start(self):
        """启动调度器"""
        logger.info("选股调度器启动")

        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.running = True
        self.start_time = time.time()

        try:
            # 启动调度器
            self.scheduler.start()
            logger.info("调度器已启动")

            # 注册退出处理
            atexit.register(self.shutdown)

            # 主循环
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("收到键盘中断")
        except Exception as e:
            logger.error(f"调度器异常: {e}", exc_info=True)
        finally:
            self.shutdown()

    def shutdown(self):
        """关闭调度器"""
        logger.info("正在关闭调度器...")
        self.running = False

        try:
            if self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("调度器已关闭")
        except Exception as e:
            logger.error(f"关闭调度器时出错: {e}")


def main():
    """主函数"""
    logger.info("选股调度器启动")
    logger.info(f"工作目录: {os.getcwd()}")
    logger.info(f"Python版本: {sys.version}")

    # 创建并启动调度器
    scheduler = SelectionScheduler()
    scheduler.setup_schedules()
    scheduler.start()

    return 0


if __name__ == '__main__':
    sys.exit(main())