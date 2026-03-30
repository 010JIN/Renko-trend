"""
MNQ 回测系统 - 参数优化与交易报告生成

功能：
1. 下载MNQ历史数据 (使用QQQ/NQ作为代理)
2. 多参数组合回测
3. 生成最优参数报告
4. 生成详细交易报告
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from itertools import product
import json
import warnings
warnings.filterwarnings('ignore')

from loguru import logger
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from strategies.mnq_renko_sar_strategy import MNQRenkoSARStrategy


def generate_synthetic_mnq_data(
    n_bars: int = 5000,
    start_price: float = 19800.0,
    volatility: float = 0.0008,
    trend_strength: float = 0.0001
) -> pd.DataFrame:
    """
    生成模拟的MNQ数据用于回测
    
    Args:
        n_bars: K线数量
        start_price: 起始价格
        volatility: 波动率
        trend_strength: 趋势强度
        
    Returns:
        OHLCV DataFrame
    """
    np.random.seed(42)  # 可重复性
    
    # 生成价格序列
    returns = np.random.normal(trend_strength, volatility, n_bars)
    
    # 添加一些趋势周期
    trend_cycle = np.sin(np.linspace(0, 8 * np.pi, n_bars)) * 0.0002
    returns = returns + trend_cycle
    
    prices = start_price * np.cumprod(1 + returns)
    
    # 生成OHLC数据
    timestamps = pd.date_range(start='2024-01-01', periods=n_bars, freq='5min')
    
    data = []
    for i, (ts, close) in enumerate(zip(timestamps, prices)):
        intrabar_vol = volatility * close
        high = close + np.random.uniform(0, intrabar_vol * 2)
        low = close - np.random.uniform(0, intrabar_vol * 2)
        open_price = prices[i-1] if i > 0 else start_price
        
        # 确保OHLC逻辑正确
        high = max(high, open_price, close)
        low = min(low, open_price, close)
        
        data.append({
            'timestamp': ts,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': np.random.randint(1000, 10000)
        })
    
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    
    return df


def download_mnq_data(
    period: str = "60d",
    interval: str = "5m",
    use_proxy: bool = True
) -> pd.DataFrame:
    """
    下载MNQ数据
    
    由于MNQ没有免费的公开数据源，使用QQQ ETF作为代理
    如果网络不可用，使用模拟数据
    
    Args:
        period: 数据周期
        interval: K线周期
        use_proxy: 是否使用代理数据
        
    Returns:
        OHLCV DataFrame
    """
    try:
        import yfinance as yf
        
        if use_proxy:
            # 使用QQQ ETF作为MNQ代理
            logger.info(f"下载QQQ数据作为MNQ代理 (周期={period}, 间隔={interval})...")
            ticker = yf.Ticker("QQQ")
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                logger.warning("下载数据失败，使用模拟数据")
                return generate_synthetic_mnq_data()
            
            df.columns = df.columns.str.lower()
            
            # 模拟MNQ价格 (QQQ价格 * ~45-50 ≈ MNQ价格)
            mnq_multiplier = 45
            df['open'] = df['open'] * mnq_multiplier
            df['high'] = df['high'] * mnq_multiplier
            df['low'] = df['low'] * mnq_multiplier
            df['close'] = df['close'] * mnq_multiplier
            
            logger.info(f"成功下载 {len(df)} 条K线数据")
            logger.info(f"价格范围: {df['low'].min():.2f} - {df['high'].max():.2f}")
            logger.info(f"时间范围: {df.index[0]} - {df.index[-1]}")
            
            return df
        else:
            # 尝试下载NQ期货数据
            logger.info("尝试下载NQ期货数据...")
            ticker = yf.Ticker("NQ=F")
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                logger.warning("NQ期货数据不可用，回退到QQQ代理")
                return download_mnq_data(period, interval, use_proxy=True)
            
            df.columns = df.columns.str.lower()
            logger.info(f"成功下载 {len(df)} 条K线数据")
            
            return df
            
    except Exception as e:
        logger.warning(f"下载数据失败: {e}，使用模拟数据")
        return generate_synthetic_mnq_data()


def run_single_backtest(
    df: pd.DataFrame,
    params: Dict
) -> Dict:
    """
    运行单次回测
    
    Args:
        df: OHLCV数据
        params: 策略参数
        
    Returns:
        回测统计结果
    """
    strategy = MNQRenkoSARStrategy(**params)
    stats = strategy.run_backtest(df)
    
    # 添加参数信息
    stats['params'] = params
    
    return stats


def optimize_parameters(
    df: pd.DataFrame,
    param_grid: Dict,
    metric: str = 'total_return_pct'
) -> Tuple[Dict, pd.DataFrame]:
    """
    参数优化
    
    Args:
        df: OHLCV数据
        param_grid: 参数网格
        metric: 优化指标
        
    Returns:
        (最优参数, 所有结果DataFrame)
    """
    logger.info("="*60)
    logger.info("开始参数优化")
    logger.info("="*60)
    
    # 生成所有参数组合
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    all_combinations = list(product(*param_values))
    
    logger.info(f"参数组合数量: {len(all_combinations)}")
    
    results = []
    best_result = None
    best_metric_value = float('-inf')
    
    for i, combo in enumerate(all_combinations):
        params = dict(zip(param_names, combo))
        
        # 添加固定参数
        params['initial_capital'] = 10000.0
        params['commission_per_contract'] = 2.0
        params['tick_value'] = 0.50
        params['tick_size'] = 0.25
        params['contracts_per_trade'] = 1
        params['max_daily_loss'] = 300.0
        
        try:
            # 运行回测
            stats = run_single_backtest(df, params)
            
            # 记录结果
            result = {
                'combo_id': i + 1,
                **params,
                'total_return': stats['total_return'],
                'total_return_pct': stats['total_return_pct'],
                'win_rate': stats['win_rate'],
                'max_drawdown': stats['max_drawdown'],
                'total_trades': stats['total_trades'],
                'profit_factor': stats['profit_factor'] if stats['profit_factor'] != float('inf') else 999,
                'expectancy': stats.get('expectancy', 0)
            }
            results.append(result)
            
            # 更新最优结果
            metric_value = stats.get(metric, 0)
            if metric_value > best_metric_value and stats['total_trades'] >= 5:  # 至少5笔交易
                best_metric_value = metric_value
                best_result = stats
            
            if (i + 1) % 10 == 0:
                logger.info(f"进度: {i+1}/{len(all_combinations)}")
                
        except Exception as e:
            logger.warning(f"参数组合 {i+1} 回测失败: {e}")
            continue
    
    # 转换为DataFrame
    results_df = pd.DataFrame(results)
    
    # 排序
    if metric in results_df.columns:
        results_df = results_df.sort_values(metric, ascending=False)
    
    logger.info("="*60)
    logger.info("参数优化完成")
    logger.info("="*60)
    
    return best_result, results_df


def generate_trading_report(
    df: pd.DataFrame,
    stats: Dict,
    output_dir: Path
) -> str:
    """
    生成详细交易报告
    
    Args:
        df: 原始数据
        stats: 回测统计
        output_dir: 输出目录
        
    Returns:
        报告文件路径
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    report_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = output_dir / f"MNQ_Trading_Report_{report_time}.md"
    
    params = stats.get('params', {})
    trades = stats.get('trades', [])
    
    # 生成报告内容
    report = f"""# MNQ Renko + SAR 策略回测报告

**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 📊 策略概述

本策略结合以下三个技术分析方法：
1. **Renko砖型图** - 过滤市场噪音，识别趋势方向
2. **K线形态识别** - 识别反转和延续形态（锤子线、吞没形态等）
3. **Parabolic SAR** - 动态跟踪止损

### 入场逻辑
- Renko趋势确认（连续{params.get('min_renko_bricks', 2)}个同向砖块）
- SAR方向与Renko趋势一致
- K线形态确认（可选）

### 出场逻辑
- SAR反转触发止损
- 价格触及SAR止损线

---

## 💹 最优参数设置

| 参数 | 数值 | 说明 |
|------|------|------|
| 砖块大小 | {params.get('renko_brick_size', 10.0)} 点 | Renko砖块大小 |
| SAR初始AF | {params.get('sar_af_start', 0.02)} | 加速因子初始值 |
| SAR步进AF | {params.get('sar_af_step', 0.02)} | 加速因子步进值 |
| SAR最大AF | {params.get('sar_af_max', 0.2)} | 加速因子最大值 |
| 确认砖块数 | {params.get('min_renko_bricks', 2)} | 趋势确认所需砖块数 |
| K线形态过滤 | {'启用' if params.get('use_pattern_filter', True) else '禁用'} | 是否使用K线形态过滤 |

---

## 💰 回测结果摘要

### 资金情况

| 指标 | 数值 |
|------|------|
| 初始资金 | ${stats['initial_capital']:,.2f} |
| 最终余额 | ${stats['final_balance']:,.2f} |
| 总盈亏 | ${stats['total_return']:+,.2f} |
| **总收益率** | **{stats['total_return_pct']:+.2%}** |
| 最大权益 | ${stats.get('max_equity', 0):,.2f} |
| **最大回撤** | **{stats['max_drawdown']:.2%}** |
| 总手续费 | ${stats.get('total_commission', 0):,.2f} |

### 交易统计

| 指标 | 数值 |
|------|------|
| 总交易次数 | {stats['total_trades']} |
| 盈利次数 | {stats['winning_trades']} |
| 亏损次数 | {stats['losing_trades']} |
| **胜率** | **{stats['win_rate']:.2%}** |
| 平均盈利 | ${stats['avg_win']:+.2f} |
| 平均亏损 | ${stats['avg_loss']:+.2f} |
| **盈亏比** | **{stats['profit_factor']:.2f}** |
| 期望值 | ${stats.get('expectancy', 0):+.2f} |
| 最大连续盈利 | {stats.get('max_consecutive_wins', 0)} 笔 |
| 最大连续亏损 | {stats.get('max_consecutive_losses', 0)} 笔 |

---

## 📈 交易表现分析

### 按出场原因统计
"""
    
    # 按出场原因统计
    if trades:
        exit_reasons = {}
        for trade in trades:
            reason = trade.exit_reason
            if reason not in exit_reasons:
                exit_reasons[reason] = {'count': 0, 'pnl': 0}
            exit_reasons[reason]['count'] += 1
            exit_reasons[reason]['pnl'] += trade.pnl
        
        report += "\n| 出场原因 | 次数 | 总盈亏 | 平均盈亏 |\n"
        report += "|----------|------|--------|----------|\n"
        for reason, data in exit_reasons.items():
            avg_pnl = data['pnl'] / data['count'] if data['count'] > 0 else 0
            report += f"| {reason} | {data['count']} | ${data['pnl']:+.2f} | ${avg_pnl:+.2f} |\n"
    
    # 添加K线形态统计
    if trades:
        patterns_stats = {}
        for trade in trades:
            for pattern in trade.patterns_detected:
                if pattern not in patterns_stats:
                    patterns_stats[pattern] = {'count': 0, 'pnl': 0, 'wins': 0}
                patterns_stats[pattern]['count'] += 1
                patterns_stats[pattern]['pnl'] += trade.pnl
                if trade.pnl > 0:
                    patterns_stats[pattern]['wins'] += 1
        
        if patterns_stats:
            report += "\n### 按K线形态统计\n\n"
            report += "| K线形态 | 出现次数 | 胜率 | 总盈亏 |\n"
            report += "|---------|----------|------|--------|\n"
            for pattern, data in sorted(patterns_stats.items(), key=lambda x: x[1]['count'], reverse=True):
                win_rate = data['wins'] / data['count'] if data['count'] > 0 else 0
                report += f"| {pattern} | {data['count']} | {win_rate:.1%} | ${data['pnl']:+.2f} |\n"
    
    report += f"""

---

## 📝 最近交易记录

最近10笔交易:

| # | 方向 | 入场时间 | 入场价 | 出场时间 | 出场价 | 盈亏 | 出场原因 |
|---|------|----------|--------|----------|--------|------|----------|
"""
    
    # 添加最近10笔交易
    if trades:
        for trade in trades[-10:]:
            direction = "做多 🟢" if trade.direction == 1 else "做空 🔴"
            entry_time = trade.entry_time.strftime("%m-%d %H:%M") if isinstance(trade.entry_time, datetime) else str(trade.entry_time)[:16]
            exit_time = trade.exit_time.strftime("%m-%d %H:%M") if isinstance(trade.exit_time, datetime) else str(trade.exit_time)[:16]
            report += f"| {trade.trade_id} | {direction} | {entry_time} | {trade.entry_price:.2f} | {exit_time} | {trade.exit_price:.2f} | ${trade.pnl:+.2f} | {trade.exit_reason} |\n"
    
    report += f"""

---

## 🎯 交易建议

### 策略优势
- ✅ Renko过滤有效减少噪音交易
- ✅ SAR止损提供动态保护
- ✅ K线形态增加入场确认

### 注意事项
- ⚠️ 此回测使用QQQ ETF作为MNQ代理数据
- ⚠️ 实盘交易时需考虑实际滑点和延迟
- ⚠️ 建议在不同市场环境下进行更多测试

### 推荐设置
- **最佳砖块大小**: {params.get('renko_brick_size', 10.0)} 点
- **SAR参数**: AF初始={params.get('sar_af_start', 0.02)}, 步进={params.get('sar_af_step', 0.02)}, 最大={params.get('sar_af_max', 0.2)}
- **建议交易时段**: 美股开盘时段 (9:30-11:00 ET) 和收盘前 (15:00-16:00 ET)

---

## 📊 数据说明

- **数据来源**: Yahoo Finance (QQQ ETF × 45 作为MNQ代理)
- **数据周期**: 5分钟K线
- **回测期间**: {df.index[0].strftime('%Y-%m-%d')} 至 {df.index[-1].strftime('%Y-%m-%d')}
- **K线数量**: {len(df)} 条

---

*报告生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""
    
    # 保存报告
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    logger.info(f"交易报告已保存: {report_file}")
    
    return str(report_file)


def generate_equity_chart(
    df: pd.DataFrame,
    trades: List,
    output_dir: Path
) -> str:
    """
    生成权益曲线图
    
    Args:
        df: 原始数据
        trades: 交易记录列表
        output_dir: 输出目录
        
    Returns:
        图表文件路径
    """
    if not trades:
        logger.warning("无交易记录，无法生成图表")
        return ""
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建权益曲线
    equity_data = []
    balance = 10000.0
    
    for trade in trades:
        equity_data.append({
            'time': trade.exit_time,
            'balance': balance + trade.pnl,
            'pnl': trade.pnl
        })
        balance += trade.pnl
    
    equity_df = pd.DataFrame(equity_data)
    
    # 创建图表
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [2, 1]})
    
    # 上图：权益曲线 + MNQ价格
    ax1 = axes[0]
    ax1_twin = ax1.twinx()
    
    # 绘制权益曲线
    ax1.plot(equity_df['time'], equity_df['balance'], 'b-', linewidth=2, label='Account Equity')
    ax1.axhline(y=10000, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
    ax1.fill_between(equity_df['time'], 10000, equity_df['balance'], 
                     where=equity_df['balance'] >= 10000, alpha=0.3, color='green')
    ax1.fill_between(equity_df['time'], 10000, equity_df['balance'], 
                     where=equity_df['balance'] < 10000, alpha=0.3, color='red')
    
    # 绘制MNQ价格
    ax1_twin.plot(df.index, df['close'], 'gray', alpha=0.5, linewidth=1, label='MNQ Price')
    
    ax1.set_xlabel('Time')
    ax1.set_ylabel('Account Equity ($)', color='blue')
    ax1_twin.set_ylabel('MNQ Price', color='gray')
    ax1.set_title('MNQ Renko+SAR Strategy - Equity Curve', fontsize=14)
    ax1.legend(loc='upper left')
    ax1_twin.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # 下图：单笔盈亏
    ax2 = axes[1]
    colors = ['green' if pnl > 0 else 'red' for pnl in equity_df['pnl']]
    ax2.bar(range(len(equity_df)), equity_df['pnl'], color=colors, alpha=0.7)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax2.set_xlabel('Trade Number')
    ax2.set_ylabel('P&L ($)')
    ax2.set_title('Individual Trade P&L', fontsize=12)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # 保存图表
    chart_file = output_dir / f"MNQ_Equity_Chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(chart_file, dpi=150, bbox_inches='tight')
    plt.close()
    
    logger.info(f"权益曲线图已保存: {chart_file}")
    
    return str(chart_file)


def main():
    """主函数"""
    logger.info("="*60)
    logger.info("🚀 MNQ Renko + SAR 策略回测系统")
    logger.info("="*60)
    
    # 设置输出目录
    output_dir = Path("data/backtest_results")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 下载数据
    logger.info("\n【步骤1】下载MNQ数据")
    df = download_mnq_data(period="60d", interval="5m")
    
    if df.empty:
        logger.error("数据下载失败，退出")
        return
    
    # 2. 参数优化
    logger.info("\n【步骤2】参数优化")
    
    # 定义参数网格 (缩减版以加快速度)
    param_grid = {
        'renko_brick_size': [8.0, 10.0, 15.0],
        'sar_af_start': [0.02, 0.025],
        'sar_af_step': [0.02, 0.025],
        'sar_af_max': [0.2],
        'min_renko_bricks': [2],
        'use_pattern_filter': [True, False]
    }
    
    # 运行优化
    best_stats, results_df = optimize_parameters(df, param_grid, metric='total_return_pct')
    
    if best_stats is None:
        logger.error("参数优化失败，使用默认参数")
        # 使用默认参数回测
        default_params = {
            'initial_capital': 10000.0,
            'commission_per_contract': 2.0,
            'tick_value': 0.50,
            'tick_size': 0.25,
            'contracts_per_trade': 1,
            'sar_af_start': 0.02,
            'sar_af_step': 0.02,
            'sar_af_max': 0.2,
            'renko_brick_size': 10.0,
            'max_daily_loss': 300.0,
            'use_pattern_filter': True,
            'min_renko_bricks': 2
        }
        best_stats = run_single_backtest(df, default_params)
    
    # 保存优化结果
    results_file = output_dir / f"optimization_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    results_df.to_csv(results_file, index=False)
    logger.info(f"优化结果已保存: {results_file}")
    
    # 3. 生成报告
    logger.info("\n【步骤3】生成交易报告")
    report_file = generate_trading_report(df, best_stats, output_dir)
    
    # 4. 生成图表
    logger.info("\n【步骤4】生成权益曲线图")
    trades = best_stats.get('trades', [])
    if trades:
        chart_file = generate_equity_chart(df, trades, output_dir)
    
    # 5. 打印最优参数结果
    logger.info("\n" + "="*60)
    logger.info("📊 最优参数回测结果")
    logger.info("="*60)
    
    print(f"\n💰 资金情况:")
    print(f"  初始资金: ${best_stats['initial_capital']:,.2f}")
    print(f"  最终余额: ${best_stats['final_balance']:,.2f}")
    print(f"  总盈亏: ${best_stats['total_return']:+,.2f}")
    print(f"  总收益率: {best_stats['total_return_pct']:+.2%}")
    print(f"  最大回撤: {best_stats['max_drawdown']:.2%}")
    
    print(f"\n📈 交易统计:")
    print(f"  总交易次数: {best_stats['total_trades']}")
    print(f"  胜率: {best_stats['win_rate']:.2%}")
    print(f"  盈亏比: {best_stats['profit_factor']:.2f}")
    
    print(f"\n🎯 最优参数:")
    params = best_stats.get('params', {})
    print(f"  砖块大小: {params.get('renko_brick_size', 10.0)} 点")
    print(f"  SAR AF: 初始={params.get('sar_af_start', 0.02)}, "
          f"步进={params.get('sar_af_step', 0.02)}, "
          f"最大={params.get('sar_af_max', 0.2)}")
    print(f"  确认砖块: {params.get('min_renko_bricks', 2)}")
    print(f"  K线形态: {'启用' if params.get('use_pattern_filter', True) else '禁用'}")
    
    # 6. 显示Top 10参数组合
    logger.info("\n【Top 10 参数组合】")
    print("\n" + "="*80)
    print("TOP 10 参数组合 (按收益率排序)")
    print("="*80)
    
    top_10 = results_df.head(10)
    for i, row in top_10.iterrows():
        print(f"\n#{row['combo_id']}: 收益率={row['total_return_pct']:.2%}, "
              f"胜率={row['win_rate']:.2%}, 回撤={row['max_drawdown']:.2%}, "
              f"交易数={row['total_trades']:.0f}")
        print(f"   参数: brick={row['renko_brick_size']}, "
              f"SAR=({row['sar_af_start']}/{row['sar_af_step']}/{row['sar_af_max']}), "
              f"bricks={row['min_renko_bricks']}, pattern={row['use_pattern_filter']}")
    
    print("\n" + "="*80)
    print(f"📄 详细报告: {report_file}")
    print(f"📊 优化结果: {results_file}")
    print("="*80)
    
    logger.info("\n✅ 回测完成!")


if __name__ == "__main__":
    main()
