#!/bin/bash
# 选股脚本启动脚本 (Linux/macOS)
# 使用方法: bash start_selector.sh 或 ./start_selector.sh

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 显示标题
echo -e "${BLUE}"
echo "========================================"
echo "     选股脚本启动器"
echo "========================================"
echo -e "${NC}"

# 检查Python
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo -e "${RED}[错误] 未找到Python，请先安装Python 3.7+${NC}"
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

echo -e "${GREEN}[信息] Python已安装: $($PYTHON_CMD --version)${NC}"

# 进入脚本目录
cd "$(dirname "$0")"

# 检查依赖
echo -e "${YELLOW}[信息] 检查依赖包...${NC}"
$PYTHON_CMD -c "import pandas, numpy, apscheduler" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}[警告] 缺少依赖包，正在安装...${NC}"
    pip3 install pandas numpy apscheduler psutil 2>/dev/null
    if [ $? -ne 0 ]; then
        echo -e "${RED}[错误] 依赖包安装失败${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}[信息] 依赖包检查完成${NC}"

# 检查配置文件
if [ ! -f "select_config.py" ]; then
    echo -e "${RED}[错误] 配置文件 select_config.py 不存在${NC}"
    exit 1
fi

# 启动菜单
echo
echo "请选择运行模式:"
echo -e "  ${GREEN}1${NC}. 直接运行一次选股（测试用）"
echo -e "  ${GREEN}2${NC}. 启动调度器（7x24小时运行）"
echo -e "  ${GREEN}3${NC}. 后台运行调度器（nohup）"
echo -e "  ${GREEN}4${NC}. 查看日志"
echo -e "  ${GREEN}5${NC}. 停止所有选股进程"
echo -e "  ${GREEN}6${NC}. 退出"
echo

read -p "请输入选择 (1-6): " choice

case $choice in
    1)
        echo
        echo -e "${YELLOW}[信息] 启动选股脚本...${NC}"
        $PYTHON_CMD select.py
        if [ $? -ne 0 ]; then
            echo
            echo -e "${RED}[错误] 脚本运行出错${NC}"
            read -p "按回车键继续..."
        fi
        ;;
    2)
        echo
        echo -e "${YELLOW}[信息] 启动调度器...${NC}"
        echo -e "${YELLOW}[提示] 按 Ctrl+C 可停止调度器${NC}"
        echo
        $PYTHON_CMD select_scheduler.py
        ;;
    3)
        echo
        echo -e "${YELLOW}[信息] 后台运行调度器...${NC}"
        nohup $PYTHON_CMD select_scheduler.py > scheduler.log 2>&1 &
        echo $! > selector.pid
        echo -e "${GREEN}[成功] 调度器已在后台启动，PID: $(cat selector.pid)${NC}"
        echo -e "${YELLOW}[提示] 查看日志: tail -f scheduler.log${NC}"
        echo -e "${YELLOW}[提示] 停止进程: kill $(cat selector.pid)${NC}"
        ;;
    4)
        echo
        echo "========================================"
        echo " 日志文件列表"
        echo "========================================"
        echo

        if [ -f "select.log" ]; then
            echo -e "[1] select.log          - 选股日志 ($(wc -l < select.log) 行)"
        else
            echo "[无] select.log"
        fi

        if [ -f "select_detail.log" ]; then
            echo -e "[2] select_detail.log   - 详细日志 ($(wc -l < select_detail.log) 行)"
        else
            echo "[无] select_detail.log"
        fi

        if [ -f "select_scheduler.log" ]; then
            echo -e "[3] select_scheduler.log - 调度器日志 ($(wc -l < select_scheduler.log) 行)"
        else
            echo "[无] select_scheduler.log"
        fi

        if [ -f "candidate.json" ]; then
            echo -e "[4] candidate.json      - 选股结果"
        else
            echo "[无] candidate.json"
        fi

        echo
        read -p "请选择要查看的文件 (输入数字或回车返回): " log_choice

        case $log_choice in
            1)
                if [ -f "select.log" ]; then
                    tail -n 100 select.log
                fi
                ;;
            2)
                if [ -f "select_detail.log" ]; then
                    tail -n 100 select_detail.log
                fi
                ;;
            3)
                if [ -f "select_scheduler.log" ]; then
                    tail -n 100 select_scheduler.log
                fi
                ;;
            4)
                if [ -f "candidate.json" ]; then
                    cat candidate.json
                fi
                ;;
            "")
                bash "$0"
                exit 0
                ;;
            *)
                echo -e "${RED}[错误] 无效选择${NC}"
                ;;
        esac

        echo
        read -p "按回车键继续..."
        bash "$0"
        ;;
    5)
        echo
        echo -e "${YELLOW}[信息] 查找选股进程...${NC}"

        # 查找Python进程
        PIDS=$(pgrep -f "select_scheduler.py")

        if [ -z "$PIDS" ]; then
            echo -e "${GREEN}[信息] 未找到运行中的选股进程${NC}"
        else
            echo -e "${YELLOW}[信息] 找到以下进程:${NC}"
            ps -p $PIDS -o pid,ppid,cmd

            read -p "是否停止这些进程? (y/N): " confirm
            if [[ $confirm =~ ^[Yy]$ ]]; then
                kill $PIDS
                echo -e "${GREEN}[成功] 进程已停止${NC}"
            else
                echo "已取消"
            fi
        fi
        ;;
    6)
        echo
        echo "退出"
        exit 0
        ;;
    *)
        echo
        echo -e "${RED}[错误] 无效选择，请重新运行脚本${NC}"
        read -p "按回车键继续..."
        bash "$0"
        ;;
esac

echo
echo "脚本已结束"