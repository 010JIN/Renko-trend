# 不同币种的推荐参数配置

## 📊 对数百分比参数表

基于历史波动率和回测结果的推荐参数

### 主流币种（推荐）

```yaml
# BTC/USDT - 比特币
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0035  # 0.35%
  
# 预期表现:
# - 价格 90,000 → 砖块约 1,530 USDT (1.7%)
# - 日均砖块: 15-25个
# - 日均交易: 5-10笔

---

# ETH/USDT - 以太坊
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0045  # 0.45%
  
# 预期表现:
# - 价格 3,300 → 砖块约 160 USDT (4.8%)
# - 日均砖块: 20-30个
# - 日均交易: 6-12笔

---

# BNB/USDT - 币安币
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0055  # 0.55%
  
# 预期表现:
# - 价格 600 → 砖块约 35 USDT (5.8%)
# - 日均砖块: 25-35个
# - 日均交易: 8-15笔
```

### 中等波动币种

```yaml
# SOL/USDT - Solana
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0065  # 0.65%
  
# 预期表现:
# - 价格 200 → 砖块约 15 USDT (7.5%)
# - 日均砖块: 30-45个
# - 日均交易: 10-20笔

---

# ADA/USDT - 卡尔达诺
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0070  # 0.70%
  
# DOT/USDT - 波卡
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0075  # 0.75%
```

### 高波动币种（谨慎）

```yaml
# DOGE/USDT - 狗狗币
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0100  # 1.0%
  
# 警告: 高波动币种风险大！

---

# SHIB/USDT - 柴犬币
renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0120  # 1.2%
```

---

## 🎯 使用方法

### 快速切换币种

```bash
# 1. 编辑 config/config.yaml
data:
  symbol: BTCUSDT  # 改成你要的币种

renko:
  method: log_percentage
  percentage: 0.0035  # 使用对应的推荐值

# 2. 运行系统
python live_simulation.py
```

---

## 🔧 参数微调指南

### 如果交易太频繁

```yaml
# 问题: 日均交易 > 20笔，手续费太高
# 解决: 增大 percentage

当前: 0.35%
调整: 0.40% (+14% 砖块大小)
或:   0.45% (+28% 砖块大小)

效果: 减少砖块数量 → 减少交易次数
```

### 如果交易太少

```yaml
# 问题: 日均交易 < 3笔，错过趋势
# 解决: 减小 percentage

当前: 0.35%
调整: 0.30% (-14% 砖块大小)
或:   0.25% (-29% 砖块大小)

效果: 增加砖块数量 → 增加交易机会
```

### 如果震荡市场亏损

```yaml
# 问题: 横盘震荡，频繁止损
# 解决: 增大 percentage + 增加确认条件

percentage: 0.35% → 0.50%
trend_confirm: 2 → 3  # 需要3个砖块确认

效果: 过滤假突破
```

### 如果单边市场错过机会

```yaml
# 问题: 大行情来了，开仓太晚
# 解决: 减小 percentage

percentage: 0.35% → 0.25%

效果: 更早捕捉趋势
```

---

## 📊 回测优化流程

### 步骤1：基准测试

```bash
# 使用推荐参数回测
python run_backtest.py --symbol BTCUSDT --percentage 0.0035

# 记录结果
收益: +5.2%
交易次数: 45
胜率: 55%
最大回撤: -2.1%
```

### 步骤2：参数扫描

```python
# 测试不同参数
percentages = [0.0025, 0.0030, 0.0035, 0.0040, 0.0045, 0.0050]

for pct in percentages:
    result = backtest(symbol='BTCUSDT', percentage=pct)
    print(f"{pct:.4f}: 收益={result['profit']:.2f}%, 交易={result['trades']}")

# 输出示例:
# 0.0025: 收益=4.2%, 交易=78  (太频繁)
# 0.0030: 收益=5.8%, 交易=62  (较好)
# 0.0035: 收益=5.2%, 交易=45  (推荐) ⭐
# 0.0040: 收益=4.5%, 交易=32  (可以)
# 0.0045: 收益=3.8%, 交易=25  (太少)
```

### 步骤3：选择最优参数

```
选择标准：
1. 最高收益？
2. 最高夏普比率？
3. 最低回撤？
4. 平衡综合表现？

推荐: 综合考虑
  - 收益 > 4%
  - 胜率 > 50%
  - 回撤 < 5%
  - 交易次数 30-60笔/月
```

---

## 💡 高级技巧

### 技巧1：牛熊切换

```yaml
# 牛市配置（价格上涨为主）
percentage: 0.0030  # 更敏感，及时开多

# 熊市配置（价格下跌为主）
percentage: 0.0040  # 更保守，避免频繁开空

# 震荡市配置
percentage: 0.0050  # 过滤噪音
```

### 技巧2：时段调整

```yaml
# 欧美交易时段（波动大）
percentage: 0.0040

# 亚洲交易时段（波动小）
percentage: 0.0030
```

### 技巧3：消息面配合

```yaml
# 重大新闻前后
percentage: 0.0050  # 避免误触发

# 平稳期
percentage: 0.0035  # 正常
```

---

## 📈 实际案例

### 案例1：BTC 从 85,000 → 95,000

```yaml
# 配置
symbol: BTCUSDT
method: log_percentage
percentage: 0.0035

# 结果
砖块数: 8个上涨砖块
交易: 开多 @ 86,500
      持有中（趋势持续）
      平多 @ 94,000 (趋势反转)
      
盈利: +8.67% (扣除手续费)
用时: 3天
```

### 案例2：ETH 震荡 3,200-3,400

```yaml
# 配置
symbol: ETHUSDT
method: log_percentage
percentage: 0.0045

# 结果
砖块数: 12个（来回震荡）
交易: 5笔（3盈2亏）
      
盈亏: -1.2% (手续费侵蚀利润)
建议: 增大 percentage 到 0.0060
```

---

## 🎯 快速配置模板

### 保守型（适合新手）

```yaml
data:
  interval: 1m
  symbol: BTCUSDT

renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0040  # 较大砖块，稳定

strategy:
  initial_capital: 10000
  trend_confirm: 3  # 需要3个砖块确认
```

### 激进型（适合高频）

```yaml
data:
  interval: 1m
  symbol: BTCUSDT

renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0025  # 较小砖块，敏感

strategy:
  initial_capital: 10000
  trend_confirm: 2  # 2个砖块就开仓
```

### 平衡型（推荐）⭐

```yaml
data:
  interval: 1m
  symbol: BTCUSDT

renko:
  method: log_percentage
  log_base: 10.0
  percentage: 0.0035  # 适中

strategy:
  initial_capital: 10000
  trend_confirm: 2
```

---

## 📝 参数记录表

建议记录每次调整，便于后续优化：

```
日期: 2025-12-12
币种: BTCUSDT
参数: percentage=0.0035
结果: 收益+5.2%, 交易45笔, 胜率55%
评价: 满意，保持

---

日期: 2025-12-13
币种: BTCUSDT
参数: percentage=0.0030 (调小)
结果: 收益+4.8%, 交易68笔, 胜率52%
评价: 交易太频繁，手续费高
决定: 改回 0.0035

---

日期: 2025-12-14
币种: ETHUSDT
参数: percentage=0.0045
结果: 收益+6.1%, 交易38笔, 胜率58%
评价: 很好！继续使用
```

---

**记住**：没有完美的参数，只有适合当前市场的参数。持续优化是关键！🎯
