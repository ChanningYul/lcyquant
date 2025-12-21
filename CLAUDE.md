## 任务执行规则
1. 所有测试类脚本都必须写到test目录下
2. 所有测试类脚本的文件名必须以test_开头
3. 所有业务逻辑脚本中途生成的文件，必须写到data目录下
4. 所有任务执行后完成的总结性Markdown文件必须写到summary目录下

## 项目技术栈
1. Python 3.12.12
2. xtdata 1.0.0
3. xtquant 1.0.0
4. 文档路径./docs

## 本项目主要由三部分组成：
1. 数据获取模块(download_all_stocks.py)：负责从交易所获取历史数据。
2. 股票筛选模块(select.py)：根据用户定义的策略，筛选出符合条件的股票。
3. 交易执行模块(trade.py)：负责将策略转换为实际的交易操作。

## 项目结构
```
lcyquant/
├── data/
│   ├── all_stocks.csv
│   └── ...
├── docs/
│   ├── xtdata.md
│   └── ...
├── log/
│   ├── strategy.log
│   └── ...
├── util/
│   ├── __init__.py
│   ├── functools.py
│   └── ...
├── download_all_stocks.py
├── select.py
├── trade.py
└── README.md
```