# 快速入门指南

## 第一步：环境准备

```bash
cd ~/quant_project/砖型图趋势过滤系统

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
source venv/bin/activate  # Mac/Linux
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

## 第二步：运行示例

### 选项1：运行快速示例（推荐新手）

```bash
python quick_start.py
```

这将运行多个示例，展示：
- 砖型图的构建
- 趋势分析
- 支撑阻力位识别
- 不同方法对比
- 趋势强度计算

### 选项2：分析真实市场数据

```bash
# 分析BTC/USDT，使用最近30天数据
python main.py --symbol BTC/USDT --days 30

# 分析ETH/USDT，使用最近7天数据
python main.py --symbol ETH/USDT --days 7
```

### 选项3：NQ / MNQ 期货回测 & 模拟（Profimr 50K）

```bash
# 1. 下载 NQ=F 历史K线（需联网，使用 yfinance）
python fetch_nq_data.py

# 2. 批量回测：遍历 5m / 15m / 1h + ATR / 固定砖块，找最优参数
python nq_backtest.py

# 3. 生成可读报告（最优参数排名 + Profimr 条件评估）
python nq_report.py

# 4. 启动 MNQ 实时模拟交易（Profimr 50K 参数，100 根K线预热）
python live_simulation_mnq.py
# 按 Ctrl+C 停止，交易记录自动保存到 data/processed/
```

**MNQ 合约规格备忘**：

| 参数 | 值 |
|------|-----|
| 点值 | $2 / 点（MNQ Micro）|
| 交易时段（北京时间）| 周一 06:10 → 周六 04:00（跨午夜）|
| 每日限损（Profimr）| $2,000 |
| 挑战目标 | 盈利 $3,000 |

## 第三步：查看结果

分析完成后，结果保存在：

```
data/
├── processed/
│   ├── BTCUSDT_renko.csv      # 砖型图数据
│   └── BTCUSDT_report.txt     # 分析报告
└── raw/
    └── BTCUSDT_5m_30d.csv     # 原始K线数据
```

## 第四步：自定义配置

编辑 `config/config.yaml` 来调整参数：

```yaml
# 修改砖块大小计算方法
renko:
  method: atr  # 改为 fixed 或 percentage
  atr_multiplier: 2.0  # 调整ATR倍数

# 修改趋势过滤条件
trend_filter:
  min_bricks: 3  # 最小连续砖块数
  strength_threshold: 0.6  # 趋势强度阈值
```

## 第五步：开发自己的策略

创建新策略文件 `strategies/my_strategy.py`：

```python
from core.renko_builder import RenkoBuilder
from core.trend_filter import TrendFilter

class MyStrategy:
    def __init__(self):
        self.renko_builder = RenkoBuilder(method='atr')
        self.trend_filter = TrendFilter()

    def analyze(self, ohlc_data):
        # 1. 构建砖型图
        renko_df = self.renko_builder.build(ohlc_data)

        # 2. 分析趋势
        signal = self.trend_filter.analyze(renko_df)

        # 3. 生成交易信号
        if signal.direction == 1 and signal.confidence > 0.8:
            return "BUY"
        elif signal.direction == -1 and signal.confidence > 0.8:
            return "SELL"
        else:
            return "HOLD"
```

## 常见问题

### Q: 如何选择合适的砖块大小？

A: 推荐使用 ATR 方法，它会根据市场波动率自动调整：
- 高波动市场：增大 `atr_multiplier`（如 3.0）
- 低波动市场：减小 `atr_multiplier`（如 1.5）

### Q: 趋势信号太多或太少？

A: 调整 `trend_filter.min_bricks` 参数：
- 信号太多：增加 `min_bricks`（如 5）
- 信号太少：减少 `min_bricks`（如 2）

### Q: 如何提高信号准确率？

A:
1. 启用成交量过滤 `use_volume_filter: true`
2. 提高可信度阈值 `confidence_threshold: 0.8`
3. 使用多周期确认 `multi_timeframe.enabled: true`

## 下一步

1. 📊 **可视化**：安装 Jupyter 并运行 `notebooks/` 中的分析笔记本
2. 🔙 **回测**：使用 `backtest.py` 测试策略历史表现
3. 🔴 **实盘**：配置 API 密钥后启动实时监控
4. 📈 **优化**：使用参数优化工具寻找最佳配置

## 学习资源

- [砖型图原理](https://www.investopedia.com/terms/r/renko-chart.asp)
- [趋势跟踪策略](https://www.investopedia.com/articles/trading/06/trendtrade.asp)
- 项目完整文档：`README.md`

## 获取帮助

遇到问题？查看：
1. `logs/app.log` - 系统日志
2. `README.md` - 完整文档
3. 示例代码 - `quick_start.py`

---

祝你交易顺利！🚀
