@echo off
:: 选股脚本启动脚本 (Windows)
:: 使用方法: 直接双击运行或在命令行执行

echo.
echo ========================================
echo     选股脚本启动器
echo ========================================
echo.

:: 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到Python，请先安装Python 3.7+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [信息] Python已安装

:: 进入脚本目录
cd /d "%~dp0"

:: 检查依赖
echo [信息] 检查依赖包...
python -c "import pandas, numpy, apscheduler" >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 缺少依赖包，正在安装...
    pip install pandas numpy apscheduler psutil
    if %errorlevel% neq 0 (
        echo [错误] 依赖包安装失败
        pause
        exit /b 1
    )
)

echo [信息] 依赖包检查完成

:: 检查配置文件
if not exist "select_config.py" (
    echo [错误] 配置文件 select_config.py 不存在
    pause
    exit /b 1
)

:: 显示启动选项
echo.
echo 请选择运行模式:
echo   1. 直接运行一次选股（测试用）
echo   2. 启动调度器（7x24小时运行）
echo   3. 查看日志
echo   4. 退出
echo.

set /p choice="请输入选择 (1-4): "

if "%choice%"=="1" goto run_once
if "%choice%"=="2" goto run_scheduler
if "%choice%"=="3" goto view_log
if "%choice%"=="4" goto exit
goto invalid

:run_once
echo.
echo [信息] 启动选股脚本...
python select.py
if %errorlevel% neq 0 (
    echo.
    echo [错误] 脚本运行出错
    pause
)
goto end

:run_scheduler
echo.
echo [信息] 启动调度器...
echo [提示] 按 Ctrl+C 可停止调度器
echo.
python select_scheduler.py
goto end

:view_log
echo.
echo ========================================
echo  日志文件列表
echo ========================================
echo.

if exist "select.log" (
    echo [1] select.log          - 选股日志
) else (
    echo [无] select.log
)

if exist "select_detail.log" (
    echo [2] select_detail.log   - 详细日志
) else (
    echo [无] select_detail.log
)

if exist "select_scheduler.log" (
    echo [3] select_scheduler.log - 调度器日志
) else (
    echo [无] select_scheduler.log
)

if exist "candidate.json" (
    echo [4] candidate.json      - 选股结果
) else (
    echo [无] candidate.json
)

echo.
set /p log_choice="请选择要查看的文件 (输入数字或回车返回): "

if "%log_choice%"=="1" (
    if exist "select.log" (
        type "select.log"
    )
) else if "%log_choice%"=="2" (
    if exist "select_detail.log" (
        type "select_detail.log"
    )
) else if "%log_choice%"=="3" (
    if exist "select_scheduler.log" (
        type "select_scheduler.log"
    )
) else if "%log_choice%"=="4" (
    if exist "candidate.json" (
        type "candidate.json"
    )
) else if "%log_choice%"=="" (
    goto start
) else (
    echo [错误] 无效选择
)

echo.
pause
goto view_log

:invalid
echo.
echo [错误] 无效选择，请重新运行脚本
pause
goto end

:exit
echo.
echo 退出
goto end

:end
echo.
echo 脚本已结束
pause