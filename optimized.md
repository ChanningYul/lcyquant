在量化交易系统的设计模式中，**“计算（Alpha Generation）”与“交易（Execution）”的分离**是一个核心原则。

`handlebar` 是一个事件驱动的回调函数（通常由行情 Tick 驱动），它的核心职责是**风控**和**即时信号执行**。如果在这里面塞入耗时的选股逻辑，会导致行情处理阻塞、下单延迟，甚至导致客户端卡死。

针对你提出的“每天只运行一次但耗时”的选股策略，商业级程序通常有以下三种处理层级，由轻量级到企业级排列：

-----

### 1\. QMT 原生方案：利用 `run_time` 定时任务

QMT 提供了专门的定时任务机制，独立于 `handlebar`。这是最简单的实现方式，适用于计算量尚可（例如几秒钟能跑完），不需要极低延迟的场景。

**核心逻辑：**
使用 `ContextInfo.run_time` 来调度任务，而不是在 `handlebar` 里判断时间。

```python
# coding:gbk

def init(ContextInfo):
    # 设定每天 09:30:00 运行一次 heavy_stock_selection
    # period='1d' 表示日线级别调度
    ContextInfo.run_time("heavy_stock_selection", "1d", "2023-01-01 09:30:00", "SH")

def heavy_stock_selection(ContextInfo):
    print("开始执行耗时选股策略...")
    # 模拟耗时操作，例如遍历3000只股票计算指标
    import time
    time.sleep(5) 
    
    # 选股完成后，将结果存入 ContextInfo，供 handlebar 使用
    ContextInfo.target_stocks = ['600000.SH', '000001.SZ']
    ContextInfo.needs_rebalance = True
    print("选股完成，等待 handlebar 执行调仓")

def handlebar(ContextInfo):
    # handlebar 只负责执行，不负责计算
    if hasattr(ContextInfo, 'needs_rebalance') and ContextInfo.needs_rebalance:
        print(f"检测到新目标池：{ContextInfo.target_stocks}，开始下单...")
        # 执行下单逻辑 order_target_percent 等
        # ...
        ContextInfo.needs_rebalance = False # 重置标记
```

**局限性：** 在 QMT 单线程模式下，如果 `heavy_stock_selection` 计算耗时极长（如超过1分钟），依然可能会暂时阻塞客户端的响应，因为它们可能共享同一个 Python 解释器进程。

-----

### 2\. 进阶方案：Python 多线程/异步 (Non-blocking)

如果选股计算非常重（比如涉及机器学习模型预测），必须保证主线程（负责接收行情和报单）不卡顿，可以使用 Python 的 `threading`。

**核心逻辑：**
在后台线程计算，计算完更新全局变量，主线程只负责“查表”。

```python
import threading
import time

# 全局变量或通过 ContextInfo 传递
global_targets = []
is_calculating = False

def heavy_task(ContextInfo):
    global global_targets, is_calculating
    is_calculating = True
    
    # --- 这里是你的复杂算法 ---
    time.sleep(10) # 假设跑了很久
    new_picks = ['600519.SH']
    # ------------------------
    
    global_targets = new_picks
    is_calculating = False
    ContextInfo.signal_ready = True # 通知主线程

def run_daily_job(ContextInfo):
    # 启动一个独立线程去跑计算
    t = threading.Thread(target=heavy_task, args=(ContextInfo,))
    t.start()

def init(ContextInfo):
    ContextInfo.signal_ready = False
    # 每天 09:00 触发线程启动
    ContextInfo.run_time("run_daily_job", "1d", "2023-01-01 09:00:00", "SH")

def handlebar(ContextInfo):
    # 极其轻量，只检查标志位
    if ContextInfo.signal_ready:
        print(f"线程计算完毕，获取到目标：{global_targets}")
        # 执行调仓
        # ...
        ContextInfo.signal_ready = False
```

-----

### 3\. 商业级/企业级方案：存算分离 (Decoupled Architecture)

这是专业私募和机构最常用的架构。其核心思想是：**QMT 客户端只作为一个“执行终端（Execution Gateway）”，不负责任何策略计算。**

#### 架构设计：

1.  **计算端 (Alpha Engine)：** \* 这是一个完全独立的 Python 脚本或服务器程序。

      * 它可能运行在另一台高性能服务器上，或者本地的另一个进程。
      * 它负责处理大量数据、运行 AI 模型、计算选股池。
      * **输出：** 它将计算好的“目标持仓”写入数据库（MySQL/Redis）或本地文件（CSV/JSON）。

2.  **数据交换层 (Data Bus)：**

      * Redis（最推荐，速度快）、CSV文件（最简单）、ZeroMQ。

3.  **交易端 (QMT Strategy)：**

      * QMT 里的策略代码非常薄。
      * **任务：** `handlebar` 或定时器每隔几秒钟读取一次 Redis/CSV。
      * **逻辑：** “我看了一眼文件，目标仓位变了吗？变了我就下单调仓。没变我就不动。”

#### 代码逻辑示例 (QMT 端):

```python
import pandas as pd
import os

def init(ContextInfo):
    # 设定一个定时器，比如每分钟检查一次外部信号文件
    ContextInfo.run_time("check_external_signal", "1m", "2023-01-01 09:30:00", "SH")
    ContextInfo.last_signal_time = 0

def check_external_signal(ContextInfo):
    file_path = "D:/strategies/daily_targets.csv"
    
    try:
        # 检查文件修改时间，只有文件更新了才读取
        mtime = os.path.getmtime(file_path)
        if mtime > ContextInfo.last_signal_time:
            df = pd.read_csv(file_path)
            target_stocks = df['stock_code'].tolist()
            
            print(f"接收到外部策略文件更新，目标：{target_stocks}")
            
            # 在这里触发调仓逻辑，或存入ContextInfo让handlebar执行
            rebalance_portfolio(ContextInfo, target_stocks)
            
            ContextInfo.last_signal_time = mtime
    except Exception as e:
        print(f"读取信号文件失败: {e}")

def handlebar(ContextInfo):
    # handlebar 甚至可以留空，或者只做风控止损
    pass

def rebalance_portfolio(ContextInfo, targets):
    # 执行具体的下单操作
    pass
```

### 总结与建议

| 方案 | 复杂度 | 稳定性 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **QMT定时任务** | 低 | 中 | 逻辑简单，计算耗时在几秒内的策略。 |
| **Python多线程** | 中 | 高 | 单机运行，计算耗时较长，不想引入外部数据库。 |
| **存算分离** | 高 | 极高 | **商业级首选**。策略复杂、需要高性能计算、或多策略管理。 |

**对于你的需求：**
如果你的选股逻辑只需要每天跑一次，且是在本地运行，我建议先尝试 **方案 1 (利用 `run_time`)**。

如果发现计算时界面卡顿明显，建议升级为 **方案 3 的“文件交换模式”**：写一个独立的 `.py` 脚本专门跑选股，跑完生成一个 CSV；QMT 里只写读取 CSV 进行调仓的代码。这是最稳健且解耦最彻底的做法。

**下一步：**
你需要我为你提供一个具体的 **“外部脚本生成CSV + QMT读取并调仓”** 的完整代码模板吗？