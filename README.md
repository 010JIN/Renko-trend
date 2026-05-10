# 砖型图趋势过滤系统 (Renko Trend Filtering System)

> 基于砖型图（Renko Chart）的趋势识别和过滤交易系统

## 项目概述

砖型图趋势过滤系统是一个专注于趋势识别的量化交易框架。通过将传统K线转换为砖型图，过滤市场噪音，捕捉真实趋势。

### 核心特点

- 🧱 **砖型图构建**: 多种砖块大小计算方法（固定、ATR、百分比）
- 📊 **趋势过滤**: 多层次趋势确认机制
- 🎯 **信号生成**: 基于砖块反转的入场/出场信号
- 📈 **多周期分析**: 支持多时间框架趋势对齐
- 🔄 **实时监控**: WebSocket实时数据处理
- 📉 **回测引擎**: 内置策略回测和性能评估

## 项目结构

```
砖型图趋势过滤系统/
├── config/                  # 配置文件
│   ├── config.yaml         # 主配置文件
│   └── exchanges.yaml      # 交易所配置
├── core/                   # 核心模块
│   ├── renko_builder.py    # 砖型图构建器
│   ├── trend_filter.py     # 趋势过滤器
│   ├── data_collector.py   # 数据采集
│   └── signal_generator.py # 信号生成器
├── strategies/             # 策略实现
│   ├── base_strategy.py    # 策略基类
│   ├── renko_trend.py      # 砖型图趋势策略
│   └── multi_timeframe.py  # 多周期策略
├── utils/                  # 工具函数
│   ├── logger.py           # 日志工具
│   ├── indicators.py       # 技术指标
│   └── visualizer.py       # 可视化工具
├── data/                   # 数据目录
│   ├── raw/                # 原始数据
│   ├── processed/          # 处理后数据
│   └── models/             # 模型文件
├── notebooks/              # Jupyter笔记本
│   ├── renko_analysis.ipynb    # 砖型图分析
│   └── strategy_backtest.ipynb # 策略回测
├── tests/                  # 测试文件
├── logs/                   # 日志文件
├── main.py                 # 主程序
├── backtest.py             # 回测脚本
├── requirements.txt        # 依赖包
└── README.md              # 本文件
```

## 快速开始

### 环境配置

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 配置设置

```bash
# 复制配置文件
cp config/config.yaml.example config/config.yaml
cp .env.example .env

# 编辑配置文件，填入API密钥
vim config/config.yaml
```

### 运行示例

```bash
# 1. 数据采集
python main.py --mode collect --symbol BTCUSDT --days 30

# 2. 构建砖型图
python main.py --mode build --brick-size ATR --period 14

# 3. 回测策略
python backtest.py --strategy renko_trend --start 2024-01-01 --end 2024-12-01

# 4. 实时监控
python main.py --mode live --symbol BTCUSDT
```

## 砖型图原理

### 什么是砖型图？

砖型图（Renko Chart）是一种只关注价格变动、忽略时间因素的图表类型：

- **砖块形成**: 价格变动达到设定阈值时才形成新砖块
- **趋势清晰**: 过滤小幅震荡，显示纯粹的趋势方向
- **简单规则**: 只有涨（绿）和跌（红）两种砖块

### 砖块大小计算方法

#### 1. 固定点数法
```python
brick_size = 100  # 固定100个点
```

#### 2. ATR动态法（推荐）
```python
brick_size = ATR(14) * multiplier
# 根据市场波动率自动调整
```

#### 3. 百分比法
```python
brick_size = current_price * 0.001  # 0.1%
```

## 策略逻辑

### 趋势过滤条件

1. **砖块方向**: 连续N个同向砖块
2. **趋势强度**: 砖块形成速度（时间/砖块数）
3. **多周期确认**: 大周期与小周期方向一致
4. **支撑阻力**: 关键价位突破确认

### 入场信号

**做多条件**:
- 连续2-3个红转绿的砖块
- 大周期（如1小时）趋势向上
- 成交量放大
- 突破前期阻力位

**做空条件**:
- 连续2-3个绿转红的砖块
- 大周期趋势向下
- 成交量放大
- 跌破前期支撑位

### 出场信号

- 砖块反转信号（颜色改变）
- 达到止盈目标（如5个砖块）
- 触发止损（如2个砖块）
- 趋势强度减弱

## 核心模块说明

### 1. RenkoBuilder (砖型图构建器)

```python
from core.renko_builder import RenkoBuilder

builder = RenkoBuilder(method='atr', period=14)
renko_data = builder.build(ohlc_data)
```

**支持方法**:
- `fixed`: 固定点数
- `atr`: ATR动态
- `percentage`: 百分比

### 2. TrendFilter (趋势过滤器)

```python
from core.trend_filter import TrendFilter

filter = TrendFilter(min_bricks=3, strength_threshold=0.7)
trend = filter.analyze(renko_data)
```

**输出**:
- `direction`: 1(上涨), -1(下跌), 0(震荡)
- `strength`: 0-1 趋势强度
- `confidence`: 0-1 信号可信度

### 3. SignalGenerator (信号生成器)

```python
from core.signal_generator import SignalGenerator

generator = SignalGenerator(strategy='renko_trend')
signals = generator.generate(renko_data, trend)
```

**信号类型**:
- `BUY`: 做多信号
- `SELL`: 做空信号
- `CLOSE_LONG`: 平多
- `CLOSE_SHORT`: 平空

## 配置说明

### config/config.yaml

```yaml
# 数据源配置
data:
  exchange: binance
  symbol: BTCUSDT
  timeframe: 5m

# 砖型图配置
renko:
  method: atr           # fixed | atr | percentage
  brick_size: 100       # 固定法使用
  atr_period: 14        # ATR法参数
  atr_multiplier: 2.0
  percentage: 0.001     # 百分比法参数

# 趋势过滤配置
trend_filter:
  min_bricks: 3         # 最小连续砖块数
  strength_threshold: 0.7
  multi_timeframe: true
  timeframes: [5m, 15m, 1h]

# 策略配置
strategy:
  name: renko_trend
  entry_bricks: 2       # 入场信号确认砖块数
  take_profit_bricks: 5 # 止盈砖块数
  stop_loss_bricks: 2   # 止损砖块数
  use_volume_filter: true

# 风险管理
risk:
  max_position_size: 1000  # USDT
  max_loss_per_trade: 50   # USDT
  max_daily_loss: 200      # USDT
```

## 回测示例

```python
from backtest import BacktestEngine
from strategies.renko_trend import RenkoTrendStrategy

# 初始化回测引擎
engine = BacktestEngine(
    initial_capital=10000,
    commission=0.001
)

# 加载策略
strategy = RenkoTrendStrategy(
    brick_method='atr',
    entry_bricks=2,
    tp_bricks=5,
    sl_bricks=2
)

# 运行回测
results = engine.run(
    strategy=strategy,
    symbol='BTCUSDT',
    start_date='2024-01-01',
    end_date='2024-12-01'
)

# 打印结果
print(f"总收益率: {results['total_return']:.2%}")
print(f"夏普比率: {results['sharpe_ratio']:.2f}")
print(f"最大回撤: {results['max_drawdown']:.2%}")
print(f"胜率: {results['win_rate']:.2%}")
```

## 实时交易

```python
from main import LiveTrader

trader = LiveTrader(
    strategy='renko_trend',
    symbol='BTCUSDT',
    brick_method='atr',
    test_mode=True  # 测试模式，不实际下单
)

# 启动实时监控
trader.start()
```

## 可视化分析

```python
from utils.visualizer import RenkoVisualizer

viz = RenkoVisualizer()

# 绘制砖型图
viz.plot_renko(renko_data, signals)

# 绘制趋势强度
viz.plot_trend_strength(trend_data)

# 绘制回测结果
viz.plot_backtest_results(results)
```

## 性能指标

系统会计算以下性能指标：

- **收益指标**: 总收益率、年化收益率、累计收益
- **风险指标**: 最大回撤、夏普比率、索提诺比率、波动率
- **交易指标**: 胜率、盈亏比、平均持仓时间、交易次数
- **趋势指标**: 趋势识别准确率、假信号率

## 优化建议

### 参数优化

1. **砖块大小**: 根据回测结果调整ATR倍数
2. **入场确认**: 调整连续砖块数要求
3. **止盈止损**: 优化盈亏比
4. **多周期权重**: 调整不同周期的权重

### 策略增强

1. **成交量过滤**: 加入成交量确认
2. **波动率过滤**: 避免在低波动期交易
3. **时间过滤**: 避开流动性差的时段
4. **组合策略**: 与其他指标结合

## 注意事项

### 砖型图的局限性

- ⚠️ **滞后性**: 砖块形成需要价格确认
- ⚠️ **信号频率**: 在震荡市场可能产生频繁信号
- ⚠️ **参数敏感**: 砖块大小对结果影响很大

### 最佳实践

1. **先回测再实盘**: 充分验证策略有效性
2. **小仓位开始**: 实盘从小资金测试
3. **监控性能**: 定期检查策略表现
4. **及时调整**: 根据市场变化调整参数

## 技术栈

- **Python 3.9+**: 核心语言
- **Pandas/NumPy**: 数据处理
- **CCXT**: 交易所接口
- **Matplotlib/Plotly**: 可视化
- **Jupyter**: 交互式分析
- **WebSocket**: 实时数据

## 开发路线图

- [x] 基础项目结构
- [x] 砖型图构建器（固定 / ATR / 百分比 / 对数百分比）
- [x] 砖型图反转策略（含合约模式、每日限损、时段过滤）
- [x] NQ 期货批量回测（nq_backtest.py + nq_report.py）
- [x] MNQ 实时模拟交易（live_simulation_mnq.py）
- [x] 多账户实时模拟（multi_account_live_simulation.py）
- [ ] Web 可视化界面
- [ ] 策略参数自动优化工具
- [ ] 风险监控系统（实盘告警）

## NQ / MNQ 期货使用指南

### 合约规格（Micro NQ E-mini，MNQ）

| 参数 | 值 |
|------|-----|
| 点值 | $2 / 点 |
| 最小跳动 | 0.25 点 = $0.50 / 张 |
| 最大持仓 | 30 张（日内保证金约 $1,000 / 张）|
| 典型风险 | 10 点止损 × 30 张 = $600 |

### 交易时段（CME Globex）

| 时区 | 开始 | 结束 | 备注 |
|------|------|------|------|
| 北京时间 (CST) | 06:10 | 04:00（次日）| 周一开盘–周六凌晨关闭 |
| UTC | 22:10（前一日）| 20:00 | 跨午夜会话 |

### Profimr 50K 账户挑战参数

| 规则 | 值 |
|------|-----|
| 初始资金 | $50,000 |
| 每日最大回撤 | $2,000（相对当日开盘余额）|
| 挑战号盈利目标 | $3,000 总盈利 |
| 出金号 | 连续 5 个盈利日，每日 ≥ $200 |

### 快速开始 NQ 模拟交易

```bash
# 1. 安装依赖（需要 yfinance）
pip install -r requirements.txt

# 2. 可选：先下载历史数据 & 运行回测，筛选最优参数
python fetch_nq_data.py          # 下载 NQ=F 历史K线
python nq_backtest.py            # 批量回测（5m / 15m / 1h，ATR + 固定法）
python nq_report.py              # 生成回测报告，输出最优参数

# 3. 启动实时模拟（5 分钟周期，ATR 法，100 根K线预热）
python live_simulation_mnq.py

# 按 Ctrl+C 停止，自动保存交易记录到 data/processed/
```

### 参数调整

编辑 `live_simulation_mnq.py` 顶部常量，或直接修改 `config/config.yaml` 中的 `mnq` 区块：

```yaml
mnq:
  interval: '5m'           # 改为 '15m' 使用 15 分钟周期
  renko_method: 'atr'      # 改为 'fixed' 使用固定砖块
  atr_multiplier: 1.0      # 调小 → 砖块更小，交易更频繁
  fixed_brick_size: 20.0   # 固定法砖块大小（NQ 点数）
  reversal_count: 2        # 1=每砖触发，2=两砖确认，3=保守型
```

## 贡献指南

欢迎提交Issue和Pull Request！

## 许可证

MIT License

---

**创建日期**: 2025-12-10
**最后更新**: 2025-12-10
**状态**: 🚧 开发中
