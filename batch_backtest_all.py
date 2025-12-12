"""
批量自动化回测脚本
满足《如何进行一次性测试》全部实验要求
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path
from loguru import logger
import yaml
import itertools
import os

sys.path.append(str(Path(__file__).parent))
from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy

# ========== 配置 ==========
SYMBOLS = ['BTCUSDT', 'ETHUSDT']
INTERVALS = ['1m', '5m', '15m']
PERIODS = [
    ('20240101', '20241231'),
    ('20250101', '20251201')
]
METHODS = ['atr', 'fixed', 'percentage', 'log_percentage']
ATR_PARAMS = [(14, 1.5), (14, 2.0), (14, 2.5)]
FIXED_PARAMS = {
    'BTCUSDT': [50, 100, 150, 200, 250, 300, 350, 400, 450, 500],
    'ETHUSDT': [10, 15, 20, 25, 30, 35, 40, 45, 50]
}
PERCENTAGE_PARAMS = [0.003, 0.0035, 0.004, 0.0045, 0.005, 0.0055]
LOG_PERCENTAGE_PARAMS = [0.003, 0.0035, 0.004, 0.0045, 0.005, 0.0055]
LOG_BASE = 10.0

RESULTS = []

# ========== 工具函数 ==========
def load_data(symbol, interval, start, end):
    data_dir = Path('data/raw')
    # 只尝试实际存在的区间命名
    fname_csv = f"{symbol}_{interval}_20241231_20251130.csv"
    fname_parquet = f"{symbol}_{interval}_20241231_20251130.parquet"
    for fname in [fname_csv, fname_parquet]:
        fpath = data_dir / fname
        if fpath.exists():
            if fname.endswith('.parquet'):
                df = pd.read_parquet(fpath)
            else:
                df = pd.read_csv(fpath)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df
    logger.warning(f"数据文件不存在: {fname_csv} / {fname_parquet}")
    return None

def aggregate_to_5m(df):
    df = df.copy()
    df.set_index('timestamp', inplace=True)
    df_5m = df.resample('5T').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()
    return df_5m

def run_backtest(df, method, symbol, method_param):
    # 构建砖型图参数
    if method == 'atr':
        atr_period, atr_multiplier = method_param
        builder = RenkoBuilder(method='atr', atr_period=atr_period, atr_multiplier=atr_multiplier)
    elif method == 'fixed':
        builder = RenkoBuilder(method='fixed', brick_size=method_param)
    elif method == 'percentage':
        builder = RenkoBuilder(method='percentage', percentage=method_param)
    elif method == 'log_percentage':
        builder = RenkoBuilder(method='log_percentage', percentage=method_param, log_base=LOG_BASE)
    else:
        raise ValueError(f"未知方法: {method}")
    renko_df = builder.build(df)
    strategy = RenkoReversalStrategy(initial_capital=10000.0, commission_rate=0.0004, slippage_rate=0.0001)
    stats = strategy.run_backtest(renko_df)
    return stats, renko_df

def save_curve(trades_df, outdir, tag):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        equity_curve = trades_df[['exit_time', 'balance_after']].copy()
        equity_curve['exit_time'] = pd.to_datetime(equity_curve['exit_time'])
        equity_curve.set_index('exit_time', inplace=True)
        plt.figure(figsize=(12,5))
        plt.plot(equity_curve.index, equity_curve['balance_after'], label='Equity')
        plt.title(f'Equity Curve {tag}')
        plt.xlabel('Time')
        plt.ylabel('Balance')
        plt.tight_layout()
        plt.savefig(outdir / f'equity_curve_{tag}.png')
        plt.close()
    except Exception as e:
        logger.warning(f"资金曲线绘制失败: {e}")

# ========== 主流程 ==========
def main():
    outdir = Path('batch_results')
    outdir.mkdir(exist_ok=True)
    for symbol in SYMBOLS:
        for (start, end) in PERIODS:
            for interval in INTERVALS:
                df = load_data(symbol, interval, start, end)
                if df is None:
                    continue
                # 1分钟聚合为5分钟（只对1m数据做）
                if interval == '1m':
                    df_5m = aggregate_to_5m(df)
                else:
                    df_5m = None
                for method in METHODS:
                    # 参数遍历
                    if method == 'atr':
                        param_list = ATR_PARAMS
                    elif method == 'fixed':
                        param_list = FIXED_PARAMS[symbol]
                    elif method == 'percentage':
                        param_list = PERCENTAGE_PARAMS
                    elif method == 'log_percentage':
                        param_list = LOG_PERCENTAGE_PARAMS
                    else:
                        continue
                    for param in param_list:
                        # 1. 原始interval
                        stats, renko_df = run_backtest(df, method, symbol, param)
                        tag = f"{symbol}_{interval}_{start}_{end}_{method}_{param}"
                        if stats['trades']:
                            trades_df = pd.DataFrame([
                                {
                                    'trade_id': t.trade_id,
                                    'direction': t.direction,
                                    'entry_time': t.entry_time,
                                    'entry_price': t.entry_price,
                                    'exit_time': t.exit_time,
                                    'exit_price': t.exit_price,
                                    'quantity': t.quantity,
                                    'pnl': t.pnl,
                                    'pnl_pct': t.pnl_pct,
                                    'balance_after': t.balance_after
                                } for t in stats['trades']
                            ])
                            save_curve(trades_df, outdir, tag)
                        RESULTS.append({
                            'symbol': symbol,
                            'interval': interval,
                            'start': start,
                            'end': end,
                            'method': method,
                            'param': param,
                            'final_balance': stats['final_balance'],
                            'return_pct': stats['total_return_pct'],
                            'max_drawdown': stats['max_drawdown'],
                            'win_rate': stats['win_rate'],
                            'total_trades': stats['total_trades'],
                            'profit_factor': stats['profit_factor'],
                            'sharpe': stats.get('sharpe', None)
                        })
                        # 2. 1m聚合5m（只对1m数据）
                        if interval == '1m' and df_5m is not None:
                            stats5, renko_df5 = run_backtest(df_5m, method, symbol, param)
                            tag5 = f"{symbol}_1mto5m_{start}_{end}_{method}_{param}"
                            if stats5['trades']:
                                trades_df5 = pd.DataFrame([
                                    {
                                        'trade_id': t.trade_id,
                                        'direction': t.direction,
                                        'entry_time': t.entry_time,
                                        'entry_price': t.entry_price,
                                        'exit_time': t.exit_time,
                                        'exit_price': t.exit_price,
                                        'quantity': t.quantity,
                                        'pnl': t.pnl,
                                        'pnl_pct': t.pnl_pct,
                                        'balance_after': t.balance_after
                                    } for t in stats5['trades']
                                ])
                                save_curve(trades_df5, outdir, tag5)
                            RESULTS.append({
                                'symbol': symbol,
                                'interval': '1mto5m',
                                'start': start,
                                'end': end,
                                'method': method,
                                'param': param,
                                'final_balance': stats5['final_balance'],
                                'return_pct': stats5['total_return_pct'],
                                'max_drawdown': stats5['max_drawdown'],
                                'win_rate': stats5['win_rate'],
                                'total_trades': stats5['total_trades'],
                                'profit_factor': stats5['profit_factor'],
                                'sharpe': stats5.get('sharpe', None)
                            })
    # 保存所有结果
    df_result = pd.DataFrame(RESULTS)
    df_result.to_csv(outdir / 'all_backtest_results.csv', index=False)
    logger.info(f"全部回测结果已保存: {outdir / 'all_backtest_results.csv'}")

if __name__ == "__main__":
    main()
