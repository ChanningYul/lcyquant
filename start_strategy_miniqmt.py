#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
miniQMT策略启动器
提供交互式菜单，方便启动和管理miniQMT交易策略
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path

# 颜色定义（支持Windows）
class Colors:
    RED = '\033[0;31m' if os.name != 'nt' else ''
    GREEN = '\033[0;32m' if os.name != 'nt' else ''
    YELLOW = '\033[1;33m' if os.name != 'nt' else ''
    BLUE = '\033[0;34m' if os.name != 'nt' else ''
    NC = '\033[0m' if os.name != 'nt' else ''  # No Color


def print_header():
    """打印标题"""
    print(f"\n{Colors.BLUE}{'='*60}")
    print("     miniQMT交易策略启动器")
    print("=" * 60 + Colors.NC)
    print()


def check_python():
    """检查Python版本"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 7):
        print(f"{Colors.RED}[错误] 需要Python 3.7+，当前版本: {version.major}.{version.minor}{Colors.NC}")
        return False
    print(f"{Colors.GREEN}[PASS] Python版本: {version.major}.{version.minor}.{version.micro}{Colors.NC}")
    return True


def check_dependencies():
    """检查依赖包"""
    print(f"{Colors.YELLOW}[检查] 验证依赖包...{Colors.NC}")

    required_packages = {
        'xtquant': 'xtquant (QMT Python SDK)',
        'pandas': 'pandas',
        'numpy': 'numpy',
    }

    missing = []
    for package, desc in required_packages.items():
        try:
            __import__(package)
            print(f"  {Colors.GREEN}[OK]{Colors.NC} {desc}")
        except ImportError:
            print(f"  {Colors.RED}[FAIL]{Colors.NC} {desc}")
            missing.append(package)

    if missing:
        print(f"\n{Colors.RED}[错误] 缺少以下依赖包:{Colors.NC}")
        for pkg in missing:
            print(f"  - {pkg}")
        print(f"\n{Colors.YELLOW}[提示] 请运行以下命令安装:{Colors.NC}")
        print(f"  pip install {' '.join(missing)}\n")
        return False

    print(f"{Colors.GREEN}[PASS] 所有依赖包检查完成{Colors.NC}\n")
    return True


def check_files():
    """检查必要文件"""
    print(f"{Colors.YELLOW}[检查] 验证必要文件...{Colors.NC}")

    required_files = {
        'strategy_miniqmt.py': 'miniQMT策略文件',
        'candidate.json': '候选股票文件（可选）',
        'xtquant/': 'QMT SDK目录',
    }

    all_exist = True
    for file, desc in required_files.items():
        path = Path(file)
        if path.exists():
            print(f"  {Colors.GREEN}[OK]{Colors.NC} {desc}: {file}")
        else:
            if file == 'candidate.json':
                print(f"  {Colors.YELLOW}[警告]{Colors.NC} {desc}: {file} (不存在，将自动创建)")
            else:
                print(f"  {Colors.RED}[FAIL]{Colors.NC} {desc}: {file}")
                all_exist = False

    if not all_exist:
        print(f"\n{Colors.RED}[错误] 缺少必要文件{Colors.NC}\n")
        return False

    print(f"{Colors.GREEN}[通过] 文件检查完成{Colors.NC}\n")
    return True


def check_qmt_connection():
    """检查QMT连接"""
    print(f"{Colors.YELLOW}[检查] 检查QMT连接...{Colors.NC}")

    # 尝试导入并连接
    try:
        from xtquant import xtdata
        xtdata.connect()
        print(f"  {Colors.GREEN}[OK]{Colors.NC} QMT连接成功")
        return True
    except Exception as e:
        print(f"  {Colors.RED}[FAIL]{Colors.NC} QMT连接失败: {str(e)[:50]}")
        print(f"\n{Colors.YELLOW}[提示] 请确保:{Colors.NC}")
        print(f"  1. QMT mini客户端已启动")
        print(f"  2. 已登录交易账号")
        print(f"  3. 防火墙未阻止连接")
        return False


def run_strategy():
    """运行策略"""
    print(f"\n{Colors.GREEN}[启动] 正在启动miniQMT策略...{Colors.NC}\n")
    print(f"{Colors.YELLOW}[提示] 按 Ctrl+C 可以停止策略{Colors.NC}\n")

    try:
        from strategy_miniqmt import main
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[信息] 用户中断，正在退出...{Colors.NC}")
        return 0
    except Exception as e:
        print(f"\n{Colors.RED}[错误] 策略运行异常: {e}{Colors.NC}")
        return 1


def view_logs():
    """查看日志"""
    log_files = {
        'strategy.log': '策略主日志',
        'strategy_run.log': '策略运行日志（后台运行）',
    }

    print(f"\n{Colors.BLUE}日志文件列表:{Colors.NC}\n")

    available_logs = []
    for log_file, desc in log_files.items():
        if Path(log_file).exists():
            size = Path(log_file).stat().st_size
            lines = subprocess.run(['wc', '-l', log_file],
                                 capture_output=True, text=True).stdout.split()[0]
            print(f"  {Colors.GREEN}[{len(available_logs)+1}]{Colors.NC} {log_file}")
            print(f"      {desc} ({lines} 行, {size/1024:.1f} KB)")
            available_logs.append(log_file)
        else:
            print(f"  {Colors.YELLOW}[-]{Colors.NC} {log_file} (不存在)")

    if not available_logs:
        print(f"\n{Colors.YELLOW}暂无日志文件{Colors.NC}\n")
        return

    print()
    choice = input(f"{Colors.YELLOW}请选择要查看的日志 (输入数字或回车返回): {Colors.NC}").strip()

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(available_logs):
            log_file = available_logs[idx]
            print(f"\n{Colors.BLUE}=== {log_file} (最近100行) ==={Colors.NC}\n")

            # 使用tail命令查看最后100行
            try:
                subprocess.run(['tail', '-n', '100', log_file])
            except FileNotFoundError:
                # Windows系统没有tail命令，使用Python实现
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines[-100:]:
                        print(line.rstrip())

            print()
        else:
            print(f"{Colors.RED}无效选择{Colors.NC}\n")


def view_status():
    """查看运行状态"""
    print(f"\n{Colors.BLUE}当前状态:{Colors.NC}\n")

    # 检查候选股票文件
    if Path('candidate.json').exists():
        try:
            import json
            with open('candidate.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            candidates = data.get('candidates', [])
            date = data.get('date', '未知')
            print(f"  {Colors.GREEN}[OK]{Colors.NC} 候选股票: {len(candidates)} 只 (日期: {date})")
        except:
            print(f"  {Colors.YELLOW}[警告]{Colors.NC} 候选股票文件格式错误")
    else:
        print(f"  {Colors.YELLOW}[警告]{Colors.NC} 候选股票文件不存在")

    # 检查策略日志
    if Path('strategy.log').exists():
        stat = Path('strategy.log').stat()
        mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
        print(f"  {Colors.GREEN}[OK]{Colors.NC} 策略日志: 存在 (最后修改: {mtime})")
    else:
        print(f"  {Colors.YELLOW}[警告]{Colors.NC} 策略日志: 不存在")

    print()


def show_menu():
    """显示菜单"""
    print(f"\n{Colors.BLUE}请选择操作:{Colors.NC}\n")
    print(f"  {Colors.GREEN}1{Colors.NC}. 启动miniQMT策略")
    print(f"  {Colors.GREEN}2{Colors.NC}. 查看运行状态")
    print(f"  {Colors.GREEN}3{Colors.NC}. 查看日志")
    print(f"  {Colors.GREEN}4{Colors.NC}. 重新检查环境")
    print(f"  {Colors.GREEN}5{Colors.NC}. 退出")
    print()


def main():
    """主函数"""
    print_header()

    # 初始化检查
    checks_passed = False
    attempts = 0
    max_attempts = 3

    while not checks_passed and attempts < max_attempts:
        checks_passed = True

        if not check_python():
            checks_passed = False

        if not check_dependencies():
            checks_passed = False

        if not check_files():
            checks_passed = False

        attempts += 1

        if not checks_passed and attempts < max_attempts:
            print(f"\n{Colors.YELLOW}检查未通过，{3-attempts}次重试机会{Colors.NC}\n")
            retry = input(f"{Colors.YELLOW}是否重新检查? (y/n): {Colors.NC}").strip().lower()
            if retry != 'y':
                break

    if not checks_passed:
        print(f"\n{Colors.RED}[错误] 环境检查未通过，无法启动策略{Colors.NC}\n")
        return 1

    # 主菜单循环
    while True:
        show_menu()

        try:
            choice = input(f"{Colors.YELLOW}请输入选择 (1-5): {Colors.NC}").strip()

            if choice == '1':
                # 运行策略
                run_strategy()

            elif choice == '2':
                # 查看状态
                view_status()
                input(f"{Colors.YELLOW}按回车键继续...{Colors.NC}")

            elif choice == '3':
                # 查看日志
                view_logs()
                input(f"{Colors.YELLOW}按回车键继续...{Colors.NC}")

            elif choice == '4':
                # 重新检查
                print()
                if check_python() and check_dependencies() and check_files():
                    print(f"\n{Colors.GREEN}[通过] 环境检查通过{Colors.NC}\n")
                else:
                    print(f"\n{Colors.RED}[错误] 环境检查未通过{Colors.NC}\n")
                input(f"{Colors.YELLOW}按回车键继续...{Colors.NC}")

            elif choice == '5':
                # 退出
                print(f"\n{Colors.GREEN}再见!{Colors.NC}\n")
                return 0

            else:
                print(f"\n{Colors.RED}无效选择，请重新输入{Colors.NC}\n")

        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}[信息] 用户中断{Colors.NC}")
            print(f"{Colors.YELLOW}[提示] 选择 '5' 可以正常退出{Colors.NC}\n")
        except Exception as e:
            print(f"\n{Colors.RED}[错误] 发生异常: {e}{Colors.NC}\n")


if __name__ == '__main__':
    sys.exit(main())
