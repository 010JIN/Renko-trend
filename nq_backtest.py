"""
纳斯达克期货（MNQ）砖型图策略回测
针对 Profimr 50K 账户挑战参数优化

账户规则：
  - 初始资金: $50,000
  - EOD 最大回撤: $2,000（相对当日开盘余额）
  - 挑战号盈利目标: $3,000 总盈利
  - 出金号: 连续5个盈利日，每日 ≥ $200

MNQ（Micro NQ E-mini）合约规格：
  - 1 点 = $2
  - 最小跳动: 0.25 点 = $0.50
  - 最大持仓: 30 张 MNQ
  - 30 张 × 1 点 = $60 / 点（最大风险敞口）
  - 典型日内风险：10 点止损 × 30 张 = $600

目标：
  - 日内 3-10 笔交易
  - 找到最优砖块大小 & 周期组合
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger
from datetime import datetime, time as dtime
from itertools import product

sys.path.append(str(Path(__file__).parent))

from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy
from fetch_nq_data import fetch_nq_data, save_nq_data, load_nq_data

# ============================================================
# Profimr 账户参数
# ============================================================
INITIAL_CAPITAL  = 50_000.0   # 50K 账户
CONTRACT_MULT    = 2.0         # MNQ (Micro E-mini NQ): $2 per point（NQ E-mini 为 $20/点）
MAX_CONTRACTS    = 30          # 最大 30 张 MNQ
MAX_DAILY_LOSS   = 2_000.0    # EOD 回撤限额 $2000
PROFIT_TARGET    = 3_000.0    # 挑战号盈利目标 $3000
WITHDRAWAL_MIN_DAYS   = 5     # 出金号：连续盈利天数
WITHDRAWAL_MIN_DAILY  = 200.0 # 出金号：每日最低盈利 $200

# 交易时段（美东时间 UTC-5/UTC-4，Globex 日盘）
# 9:30 ET = 14:30 UTC（冬令时），9:30 ET = 13:30 UTC（夏令时）
# 使用 UTC 13:30-20:00 覆盖 RTH（Regular Trading Hours）
SESSION_START_UTC = 13   # 9:30 ET ≈ 13:30 UTC（夏令时）
SESSION_END_UTC   = 20   # 4:00 PM ET ≈ 20:00 UTC

# ============================================================
# 参数扫描空间
# ============================================================
INTERVALS = ['5m', '15m', '1h']   # 数据周期

PARAM_GRID = {
    # 固定砖块法（NQ 点数）
    'fixed': [10, 15, 20, 25, 30, 40, 50, 75, 100],
    # ATR 法：(period, multiplier)
    'atr':   [(14, 0.5), (14, 0.75), (14, 1.0), (14, 1.5), (14, 2.0),
              (7, 0.5),  (7, 1.0),   (7, 1.5)],
    # 百分比法
    'percentage': [0.001, 0.0015, 0.002, 0.0025, 0.003],
}

OUTPUT_DIR = Path('batch_results')


# ============================================================
# 辅助函数
# ============================================================

def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """只保留 RTH（9:30-16:00 ET ≈ 13:30-20:00 UTC）的 K 线"""
    if 'timestamp' not in df.columns:
        return df
    ts = pd.to_datetime(df['timestamp'])
    mask = (ts.dt.hour >= SESSION_START_UTC) & (ts.dt.hour < SESSION_END_UTC)
    return df[mask].reset_index(drop=True)


def run_single_backtest(
    df: pd.DataFrame,
    method: str,
    param,
    interval: str,
    filter_session: bool = True,
) -> dict:
    """
    运行单次回测

    Args:
        df: OHLCV 数据（含 timestamp 列）
        method: 砖块计算方法
        param: 方法参数
        interval: K 线周期标签
        filter_session: 是否过滤 RTH 时段

    Returns:
        统计字典
    """
    data = filter_rth(df) if filter_session else df

    if len(data) < 50:
        return None

    # 构建砖型图
    if method == 'atr':
        atr_period, atr_mult = param
        builder = RenkoBuilder(method='atr', atr_period=atr_period, atr_multiplier=atr_mult)
        param_label = f"atr{atr_period}x{atr_mult}"
    elif method == 'fixed':
        builder = RenkoBuilder(method='fixed', brick_size=float(param))
        param_label = f"fixed{param}"
    elif method == 'percentage':
        builder = RenkoBuilder(method='percentage', percentage=param)
        param_label = f"pct{param}"
    else:
        return None

    try:
        renko_df = builder.build(data)
    except Exception as e:
        logger.warning(f"砖型图构建失败 ({method} {param}): {e}")
        return None

    if len(renko_df) < 4:
        return None

    # 运行策略
    strategy = RenkoReversalStrategy(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=0.0,          # MNQ 佣金约 $0.35-0.50/张/单边，这里忽略
        slippage_rate=0.0,            # 滑点对应 0.25 点 tick，由 contract_mult 反映
        contract_multiplier=CONTRACT_MULT,
        max_contracts=MAX_CONTRACTS,
        max_daily_loss=MAX_DAILY_LOSS,
        session_start_hour=SESSION_START_UTC,
        session_end_hour=SESSION_END_UTC,
    )

    try:
        stats = strategy.run_backtest(renko_df)
    except Exception as e:
        logger.warning(f"回测失败 ({method} {param}): {e}")
        return None

    if stats['total_trades'] == 0:
        return None

    # 每日统计
    daily_pnl = stats.get('daily_pnl', {})
    daily_trades = stats.get('daily_trades', {})

    days_total = len(daily_pnl)
    days_profit = sum(1 for v in daily_pnl.values() if v > 0)
    days_loss   = sum(1 for v in daily_pnl.values() if v < 0)
    days_over_200 = sum(1 for v in daily_pnl.values() if v >= WITHDRAWAL_MIN_DAILY)

    avg_daily_pnl    = np.mean(list(daily_pnl.values())) if daily_pnl else 0
    max_daily_loss_actual = min(list(daily_pnl.values())) if daily_pnl else 0
    avg_daily_trades = np.mean(list(daily_trades.values())) if daily_trades else 0

    # 检查 Profimr 挑战达成条件
    profit_target_hit = (stats['total_return'] >= PROFIT_TARGET)
    # 日均回撤 < $2000（用最大单日亏损估计）
    daily_loss_ok = (abs(max_daily_loss_actual) <= MAX_DAILY_LOSS)
    # 出金号：连续5日盈利 ≥ $200
    withdrawal_days_ok = (days_over_200 >= WITHDRAWAL_MIN_DAYS)

    # 日内交易次数适合度（目标 3-10 笔/日）
    in_range = (3 <= avg_daily_trades <= 10)
    trade_freq_score = max(0, 1 - abs(avg_daily_trades - 6.5) / 6.5)

    result = {
        'interval': interval,
        'method': method,
        'param': str(param),
        'param_label': param_label,
        # 资金表现
        'final_balance': round(stats['final_balance'], 2),
        'total_return': round(stats['total_return'], 2),
        'total_return_pct': round(stats['total_return_pct'] * 100, 2),
        'max_drawdown_pct': round(stats['max_drawdown'] * 100, 2),
        # 交易统计
        'total_trades': stats['total_trades'],
        'win_rate': round(stats['win_rate'] * 100, 2),
        'profit_factor': round(stats['profit_factor'], 3),
        'avg_win': round(stats['avg_win'], 2),
        'avg_loss': round(stats['avg_loss'], 2),
        # 日内交易频率
        'avg_daily_trades': round(avg_daily_trades, 1),
        'in_trade_freq_range': in_range,
        'trade_freq_score': round(trade_freq_score, 3),
        # 每日 P&L
        'days_total': days_total,
        'days_profit': days_profit,
        'days_loss': days_loss,
        'days_over_200': days_over_200,
        'avg_daily_pnl': round(avg_daily_pnl, 2),
        'max_daily_loss': round(max_daily_loss_actual, 2),
        # Profimr 条件评估
        'profit_target_hit': profit_target_hit,
        'daily_loss_ok': daily_loss_ok,
        'withdrawal_days_ok': withdrawal_days_ok,
        'profimr_eval_pass': (profit_target_hit and daily_loss_ok),
        'profimr_withdrawal_pass': withdrawal_days_ok,
        # 综合评分（越高越好）
        'composite_score': _composite_score(stats, avg_daily_trades, days_over_200),
    }

    return result


def _composite_score(stats: dict, avg_daily_trades: float, days_over_200: int) -> float:
    """
    综合评分（0-100）

    加权考虑：
    - 收益率（30%）
    - 最大回撤（25%）- 越小越好
    - 胜率（15%）
    - 盈亏比（15%）
    - 日内交易频率适合度（15%）
    """
    # 收益率得分（目标 $3000/$50000 = 6%，超额加分）
    ret_pct = stats['total_return_pct']
    ret_score = min(ret_pct * 10, 30)   # 3% return = 30分

    # 回撤得分（越小越好，超过4% = 0分）
    dd_pct = stats['max_drawdown'] * 100
    dd_score = max(0, 25 - dd_pct * 6)

    # 胜率得分（50%=7.5，60%=15）
    wr_score = min(stats['win_rate'] * 25, 15)

    # 盈亏比得分（1.5=11.25，2.0=15）
    pf = min(stats['profit_factor'], 3.0)
    pf_score = min(pf * 5, 15)

    # 日内频率得分（目标 3-10 笔）
    freq_score = max(0, 15 - abs(avg_daily_trades - 6.5) * 3)

    return round(ret_score + dd_score + wr_score + pf_score + freq_score, 2)


# ============================================================
# 主流程
# ============================================================

def run_nq_backtest(intervals=None, auto_download=True):
    """
    运行 NQ 参数扫描回测

    Args:
        intervals: 要测试的周期列表，默认为 INTERVALS
        auto_download: 若本地无数据则自动下载
    """
    intervals = intervals or INTERVALS
    OUTPUT_DIR.mkdir(exist_ok=True)

    all_results = []

    for interval in intervals:
        logger.info(f"\n{'='*60}")
        logger.info(f"周期: {interval}")
        logger.info(f"{'='*60}")

        # 加载数据
        df = load_nq_data(interval=interval)
        if df.empty and auto_download:
            logger.info(f"本地无数据，尝试下载 {interval}...")
            days_map = {'1m': 7, '5m': 60, '15m': 60, '1h': 365, '1d': 365 * 3}
            days = days_map.get(interval, 60)
            df = fetch_nq_data(interval=interval, days=days)
            if not df.empty:
                save_nq_data(df, interval=interval)

        if df.empty:
            logger.warning(f"跳过 {interval}：无数据")
            continue

        logger.info(f"数据: {len(df):,} 条 | {df['timestamp'].min()} → {df['timestamp'].max()}")

        # 参数扫描
        for method, params in PARAM_GRID.items():
            for param in params:
                result = run_single_backtest(df, method=method, param=param, interval=interval)
                if result:
                    all_results.append(result)
                    logger.info(
                        f"  {method:<12} param={str(param):<12} "
                        f"trades={result['total_trades']:>4} "
                        f"avg_daily={result['avg_daily_trades']:>4.1f} "
                        f"ret={result['total_return_pct']:>+7.2f}% "
                        f"dd={result['max_drawdown_pct']:>5.2f}% "
                        f"score={result['composite_score']:>5.1f}"
                    )

    if not all_results:
        logger.error("没有有效的回测结果")
        return pd.DataFrame()

    df_result = pd.DataFrame(all_results)
    df_result = df_result.sort_values('composite_score', ascending=False)

    # 保存全部结果
    out_csv = OUTPUT_DIR / 'nq_backtest_all.csv'
    df_result.to_csv(out_csv, index=False)
    logger.info(f"\n全部结果已保存: {out_csv}")

    return df_result


if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info("🚀 NQ 期货砖型图策略回测 (Profimr 50K 账户)")
    logger.info("=" * 70)

    df_results = run_nq_backtest(auto_download=True)

    if df_results.empty:
        logger.error("回测无结果，请先下载 NQ 数据: python fetch_nq_data.py")
        sys.exit(1)

    # 导入报告生成器（如果存在）
    try:
        from nq_report import generate_report
        generate_report(df_results)
    except ImportError:
        # 没有报告模块时，直接打印 Top 20
        logger.info("\n" + "=" * 70)
        logger.info("📊 Top 20 参数组合（按综合评分）")
        logger.info("=" * 70)
        top20 = df_results.head(20)
        print(top20[[
            'interval', 'method', 'param_label',
            'avg_daily_trades', 'total_return', 'total_return_pct',
            'max_drawdown_pct', 'win_rate', 'profit_factor',
            'days_over_200', 'profimr_eval_pass', 'composite_score'
        ]].to_string(index=False))
