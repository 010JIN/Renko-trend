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
MARGIN_PER_CONTRACT = 1_000.0 # MNQ 日内保证金约 $500-1500/张，取 $1000
MAX_DAILY_LOSS   = 2_000.0    # EOD 回撤限额 $2000
PROFIT_TARGET    = 3_000.0    # 挑战号盈利目标 $3000
WITHDRAWAL_MIN_DAYS   = 5     # 出金号：连续盈利天数
WITHDRAWAL_MIN_DAILY  = 200.0 # 出金号：每日最低盈利 $200

# 交易时段（中国标准时间 CST = UTC+8）
# 06:10 CST → 22:10 UTC（前一日）；凌晨 04:00 CST → 20:00 UTC（跨午夜会话）
# CME Globex MNQ 周一至周五交易
SESSION_START_UTC_HOUR = 22   # 06:10 CST = 22:10 UTC
SESSION_START_UTC_MIN  = 10
SESSION_END_UTC_HOUR   = 20   # 04:00 CST = 20:00 UTC
SESSION_END_UTC_MIN    = 0
SESSION_WEEKDAYS_ONLY  = True  # 仅周一至周五

# ============================================================
# 参数扫描空间
# ============================================================
INTERVALS = ['5m', '15m', '1h']   # 数据周期

PARAM_GRID = {
    # 固定砖块法（NQ 点数）— MNQ 价格在 17000-22000，合理砖块 5-100 点
    'fixed': [5, 10, 15, 20, 25, 30, 40, 50, 75, 100],
    # ATR 法：(period, multiplier)
    'atr':   [(14, 0.5), (14, 0.75), (14, 1.0), (14, 1.5), (14, 2.0),
              (7, 0.5),  (7, 0.75),  (7, 1.0),  (7, 1.5)],
    # 百分比法
    'percentage': [0.001, 0.0015, 0.002, 0.0025, 0.003],
}

# 反转确认砖块数（1=每根砖即触发，2=连续2根同向，3=保守型）
REVERSAL_COUNTS = [1, 2, 3]

OUTPUT_DIR = Path('batch_results')


# ============================================================
# 辅助函数
# ============================================================

def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """只保留交易时段（周一至周五 06:10-04:00 CST ≈ 22:10-20:00 UTC，跨午夜）的 K 线"""
    if 'timestamp' not in df.columns:
        return df
    ts = pd.to_datetime(df['timestamp'])

    # 工作日过滤（0=周一 … 4=周五；5=周六, 6=周日）
    weekday_mask = ts.dt.weekday < 5

    # 时间过滤（分钟精度，跨午夜：22:10 UTC → 20:00 UTC）
    minutes  = ts.dt.hour * 60 + ts.dt.minute
    start_m  = SESSION_START_UTC_HOUR * 60 + SESSION_START_UTC_MIN
    end_m    = SESSION_END_UTC_HOUR   * 60 + SESSION_END_UTC_MIN
    # 跨午夜：start_m > end_m → 在时段内当 time >= start 或 time < end
    time_mask = (minutes >= start_m) | (minutes < end_m)

    return df[weekday_mask & time_mask].reset_index(drop=True)


def run_single_backtest(
    df: pd.DataFrame,
    method: str,
    param,
    interval: str,
    reversal_count: int = 2,
    filter_session: bool = True,
) -> dict:
    """
    运行单次回测

    Args:
        df: OHLCV 数据（含 timestamp 列）
        method: 砖块计算方法
        param: 方法参数
        interval: K 线周期标签
        reversal_count: 确立趋势所需的连续同向砖块数（1/2/3）
        filter_session: 是否过滤 RTH 时段

    Returns:
        统计字典，None 表示无效
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

    if len(renko_df) < reversal_count + 2:
        return None

    # 运行策略（MNQ 使用保证金定仓）
    strategy = RenkoReversalStrategy(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=0.0,                 # MNQ 佣金约 $0.35-0.50/张/单边，这里忽略
        slippage_rate=0.0,                   # 滑点对应 0.25 点 tick = $0.50/张
        contract_multiplier=CONTRACT_MULT,
        max_contracts=MAX_CONTRACTS,
        margin_per_contract=MARGIN_PER_CONTRACT,
        max_daily_loss=MAX_DAILY_LOSS,
        session_start_hour=SESSION_START_UTC_HOUR,
        session_start_minute=SESSION_START_UTC_MIN,
        session_end_hour=SESSION_END_UTC_HOUR,
        session_end_minute=SESSION_END_UTC_MIN,
        session_weekdays_only=SESSION_WEEKDAYS_ONLY,
        reversal_count=reversal_count,
    )

    try:
        stats = strategy.run_backtest(renko_df)
    except Exception as e:
        logger.warning(f"回测失败 ({method} {param} rc={reversal_count}): {e}")
        return None

    if stats['total_trades'] == 0:
        return None

    # 每日统计
    daily_pnl    = stats.get('daily_pnl', {})
    daily_trades = stats.get('daily_trades', {})

    days_total    = len(daily_pnl)
    days_profit   = sum(1 for v in daily_pnl.values() if v > 0)
    days_loss     = sum(1 for v in daily_pnl.values() if v < 0)
    days_over_200 = sum(1 for v in daily_pnl.values() if v >= WITHDRAWAL_MIN_DAILY)

    avg_daily_pnl         = np.mean(list(daily_pnl.values())) if daily_pnl else 0
    max_daily_loss_actual = min(list(daily_pnl.values())) if daily_pnl else 0
    avg_daily_trades      = np.mean(list(daily_trades.values())) if daily_trades else 0

    # Profimr 条件评估
    profit_target_hit  = (stats['total_return'] >= PROFIT_TARGET)
    daily_loss_ok      = (abs(max_daily_loss_actual) <= MAX_DAILY_LOSS)
    withdrawal_days_ok = (days_over_200 >= WITHDRAWAL_MIN_DAYS)

    in_range         = (3 <= avg_daily_trades <= 10)
    trade_freq_score = max(0, 1 - abs(avg_daily_trades - 6.5) / 6.5)

    result = {
        'interval': interval,
        'reversal_count': reversal_count,
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

def run_nq_backtest(intervals=None, reversal_counts=None, auto_download=True):
    """
    运行 MNQ 参数扫描回测（包含砖块大小 × 反转确认数）

    Args:
        intervals: 要测试的周期列表，默认为 INTERVALS
        reversal_counts: 反转确认砖块数列表，默认为 REVERSAL_COUNTS
        auto_download: 若本地无数据则自动下载
    """
    intervals      = intervals      or INTERVALS
    reversal_counts = reversal_counts or REVERSAL_COUNTS
    OUTPUT_DIR.mkdir(exist_ok=True)

    all_results = []
    total_combos = len(intervals) * sum(len(v) for v in PARAM_GRID.values()) * len(reversal_counts)
    logger.info(f"总参数组合数: {total_combos}")

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

        # 三维参数扫描：砖块方法 × 砖块参数 × 反转确认数
        for rc in reversal_counts:
            for method, params in PARAM_GRID.items():
                for param in params:
                    result = run_single_backtest(
                        df, method=method, param=param,
                        interval=interval, reversal_count=rc
                    )
                    if result:
                        all_results.append(result)
                        logger.info(
                            f"  rc={rc} {method:<12} param={str(param):<12} "
                            f"trades={result['total_trades']:>4} "
                            f"daily={result['avg_daily_trades']:>4.1f} "
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
