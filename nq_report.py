"""
NQ 期货策略回测报告生成器

生成内容：
1. 回测总览报告（Markdown + CSV）
2. 最优参数详细分析
3. 模拟交易报告模板（含 Profimr 达成评估）
4. 每日 P&L 分布图（可选）
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from loguru import logger

sys.path.append(str(Path(__file__).parent))

OUTPUT_DIR = Path('batch_results')
REPORT_DIR = Path('data/processed')

# Profimr 参数
INITIAL_CAPITAL = 50_000.0
PROFIT_TARGET   = 3_000.0
MAX_DAILY_LOSS  = 2_000.0
WITHDRAWAL_DAYS = 5
WITHDRAWAL_DAILY = 200.0


# ============================================================
# 报告生成函数
# ============================================================

def generate_report(df_results: pd.DataFrame, output_dir: Path = None) -> None:
    """
    生成完整的回测分析报告

    Args:
        df_results: nq_backtest.py 输出的全量结果 DataFrame
        output_dir: 报告输出目录（默认 batch_results/）
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)

    logger.info("\n" + "=" * 70)
    logger.info("📋 生成 NQ 回测报告")
    logger.info("=" * 70)

    # 1. 全量结果排名
    df_sorted = df_results.sort_values('composite_score', ascending=False).reset_index(drop=True)

    # 2. 按周期分类 Top5
    per_interval_top = {}
    for interval in df_sorted['interval'].unique():
        top = df_sorted[df_sorted['interval'] == interval].head(5)
        per_interval_top[interval] = top

    # 3. 日内频率符合条件的筛选（3-10 笔/日）
    df_inrange = df_sorted[df_sorted['in_trade_freq_range']].copy()

    # 4. Profimr 挑战通过的组合
    df_eval_pass = df_sorted[df_sorted['profimr_eval_pass']].copy()
    df_withdrawal_pass = df_sorted[df_sorted['profimr_withdrawal_pass']].copy()

    # ---- 生成 Markdown 报告 ----
    md_path = output_dir / 'nq_backtest_report.md'
    with open(md_path, 'w', encoding='utf-8') as f:
        _write_markdown_report(
            f, df_sorted, per_interval_top, df_inrange, df_eval_pass, df_withdrawal_pass
        )
    logger.info(f"Markdown 报告: {md_path}")

    # ---- 保存筛选结果 CSV ----
    if not df_inrange.empty:
        df_inrange.to_csv(output_dir / 'nq_inrange_results.csv', index=False)
    if not df_eval_pass.empty:
        df_eval_pass.to_csv(output_dir / 'nq_profimr_eval_pass.csv', index=False)

    # ---- 打印控制台摘要 ----
    _print_console_summary(df_sorted, df_inrange, df_eval_pass)

    # ---- 生成模拟交易报告模板 ----
    sim_path = output_dir / 'nq_simulation_report.md'
    _write_simulation_report(sim_path, df_sorted)
    logger.info(f"模拟交易报告模板: {sim_path}")

    # ---- 尝试画图 ----
    try:
        _plot_top_equity_curves(df_sorted.head(5), output_dir)
    except Exception as e:
        logger.warning(f"图表生成跳过: {e}")

    logger.info("\n✅ 报告生成完成")


def _write_markdown_report(f, df_all, per_interval, df_inrange, df_eval, df_withdraw):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    f.write(f"# NQ 期货砖型图策略回测报告\n\n")
    f.write(f"> 生成时间: {now}  \n")
    f.write(f"> 账户: Profimr 50K | 目标: $3,000 盈利 | EOD 回撤限制: $2,000\n\n")

    f.write("---\n\n")
    f.write("## 一、账户规则说明\n\n")
    f.write("| 项目 | 数值 |\n|---|---|\n")
    f.write(f"| 账户规模 | ${INITIAL_CAPITAL:,.0f} |\n")
    f.write(f"| 合约品种 | MNQ（Micro NQ E-mini） |\n")
    f.write(f"| MNQ 合约倍数 | $2 / 点 |\n")
    f.write(f"| 最小跳动 | 0.25 点 = $0.50 / 张 |\n")
    f.write(f"| 最大持仓 | 30 张 MNQ |\n")
    f.write(f"| 最大点位风险 | 30 张 × 1 点 = $60 / 点 |\n")
    f.write(f"| EOD 最大回撤 | ${MAX_DAILY_LOSS:,.0f} |\n")
    f.write(f"| 挑战号盈利目标 | ${PROFIT_TARGET:,.0f} |\n")
    f.write(f"| 出金号条件 | {WITHDRAWAL_DAYS} 个盈利日，每日 ≥ ${WITHDRAWAL_DAILY:.0f} |\n\n")

    f.write("---\n\n")
    f.write("## 二、全局 Top 20 参数组合（按综合评分）\n\n")
    f.write(_df_to_md(df_all.head(20)[[
        'interval', 'method', 'param_label',
        'avg_daily_trades', 'total_return', 'total_return_pct',
        'max_drawdown_pct', 'win_rate', 'profit_factor',
        'days_over_200', 'profimr_eval_pass', 'composite_score'
    ]].rename(columns={
        'interval': '周期', 'method': '方法', 'param_label': '参数',
        'avg_daily_trades': '日均交易', 'total_return': '总盈亏($)',
        'total_return_pct': '收益率(%)', 'max_drawdown_pct': '最大回撤(%)',
        'win_rate': '胜率(%)', 'profit_factor': '盈亏比',
        'days_over_200': '≥$200盈利日数', 'profimr_eval_pass': '挑战达成',
        'composite_score': '综合评分'
    })))
    f.write("\n\n")

    f.write("---\n\n")
    f.write("## 三、按周期最优参数\n\n")
    for interval, top_df in per_interval.items():
        f.write(f"### {interval} 周期 Top 5\n\n")
        f.write(_df_to_md(top_df[[
            'method', 'param_label', 'avg_daily_trades', 'total_return',
            'total_return_pct', 'max_drawdown_pct', 'win_rate', 'profit_factor',
            'days_profit', 'days_loss', 'days_over_200', 'composite_score'
        ]]))
        f.write("\n\n")

    f.write("---\n\n")
    f.write("## 四、日内 3-10 笔交易筛选结果\n\n")
    if not df_inrange.empty:
        f.write(f"共 **{len(df_inrange)}** 个参数组合满足日均 3-10 笔交易。\n\n")
        f.write(_df_to_md(df_inrange.head(15)[[
            'interval', 'method', 'param_label',
            'avg_daily_trades', 'total_return', 'max_drawdown_pct',
            'win_rate', 'profit_factor', 'composite_score'
        ]]))
    else:
        f.write("*没有参数组合满足日均 3-10 笔交易条件，建议调小砖块大小。*\n")
    f.write("\n\n")

    f.write("---\n\n")
    f.write("## 五、Profimr 挑战达成情况\n\n")
    f.write("### 5.1 挑战号（盈利 $3,000 且日回撤 < $2,000）\n\n")
    if not df_eval.empty:
        f.write(f"✅ **{len(df_eval)}** 个参数组合满足挑战号条件。\n\n")
        f.write(_df_to_md(df_eval.head(10)[[
            'interval', 'method', 'param_label',
            'avg_daily_trades', 'total_return', 'max_drawdown_pct',
            'win_rate', 'composite_score'
        ]]))
    else:
        f.write("❌ 当前数据周期内，无参数满足挑战号全部条件。\n")
        f.write("**建议**：延长回测周期 / 降低砖块大小 / 使用 5m 而非 1h 数据。\n")
    f.write("\n\n")

    f.write("### 5.2 出金号（连续 5 日盈利 ≥ $200）\n\n")
    if not df_withdraw.empty:
        f.write(f"✅ **{len(df_withdraw)}** 个参数满足出金号条件。\n\n")
        f.write(_df_to_md(df_withdraw.head(10)[[
            'interval', 'method', 'param_label',
            'avg_daily_trades', 'total_return', 'days_over_200',
            'avg_daily_pnl', 'composite_score'
        ]]))
    else:
        f.write("❌ 当前数据内，无参数满足 5 日连续 ≥$200 条件。\n")
    f.write("\n\n")

    f.write("---\n\n")
    f.write("## 六、推荐参数组合\n\n")
    _write_recommendation(f, df_all, df_inrange, df_eval)

    f.write("---\n\n")
    f.write("## 七、综合评分说明\n\n")
    f.write("综合评分 = 收益率分（30） + 回撤分（25） + 胜率分（15） + 盈亏比分（15） + 日频率分（15）\n\n")
    f.write("- **收益率分**：年化收益越高得分越高，上限 30 分\n")
    f.write("- **回撤分**：最大回撤越小得分越高，超过 4% 为 0 分\n")
    f.write("- **胜率分**：胜率 60% = 15 分\n")
    f.write("- **盈亏比分**：盈亏比 ≥ 3.0 = 15 分\n")
    f.write("- **日频率分**：日均 6-7 笔最高，偏离越远得分越低\n\n")

    f.write("---\n\n")
    f.write("> **风险提示**：回测结果不代表实盘表现。滑点、流动性、平台差异可能导致实际结果偏差。\n")
    f.write("> 建议在 Profimr 模拟账户中运行 5-10 个交易日后再切换实盘。\n")


def _write_recommendation(f, df_all, df_inrange, df_eval):
    """写出推荐参数"""
    f.write("### 综合推荐（优先顺序）\n\n")

    candidates = []

    # 优先：满足 Profimr 挑战 + 日频率合适
    if not df_eval.empty and not df_inrange.empty:
        combo = df_eval[df_eval['in_trade_freq_range']].head(3)
        for _, row in combo.iterrows():
            candidates.append((row, "挑战达成 + 频率适合"))

    # 其次：频率适合 + 高评分
    if not df_inrange.empty:
        for _, row in df_inrange.head(3).iterrows():
            if not any(c[0]['param_label'] == row['param_label'] for c in candidates):
                candidates.append((row, "频率适合"))

    # 最后：最高评分
    for _, row in df_all.head(3).iterrows():
        if not any(c[0]['param_label'] == row['param_label'] for c in candidates):
            candidates.append((row, "综合评分最高"))

    if not candidates:
        f.write("*数据不足，无法给出推荐。请先下载更多数据。*\n\n")
        return

    for i, (row, reason) in enumerate(candidates[:5], 1):
        f.write(f"**推荐 {i}**（{reason}）\n\n")
        f.write(f"| 项目 | 值 |\n|---|---|\n")
        f.write(f"| 周期 | {row['interval']} |\n")
        f.write(f"| 方法 | {row['method']} |\n")
        f.write(f"| 参数 | {row['param_label']} |\n")
        f.write(f"| 日均交易次数 | {row['avg_daily_trades']:.1f} 笔 |\n")
        f.write(f"| 总盈亏 | ${row['total_return']:+,.2f} |\n")
        f.write(f"| 收益率 | {row['total_return_pct']:+.2f}% |\n")
        f.write(f"| 最大回撤 | {row['max_drawdown_pct']:.2f}% |\n")
        f.write(f"| 胜率 | {row['win_rate']:.1f}% |\n")
        f.write(f"| 盈亏比 | {row['profit_factor']:.2f} |\n")
        f.write(f"| ≥$200盈利日 | {row['days_over_200']} 天 |\n")
        f.write(f"| 综合评分 | {row['composite_score']:.1f} |\n\n")


def _write_simulation_report(path: Path, df_sorted: pd.DataFrame) -> None:
    """生成模拟交易报告模板"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    best = df_sorted.iloc[0] if not df_sorted.empty else None

    with open(path, 'w', encoding='utf-8') as f:
        f.write(f"# NQ 期货砖型图策略 - 模拟交易报告\n\n")
        f.write(f"> 生成时间: {now}\n\n")
        f.write("---\n\n")

        f.write("## 一、策略概述\n\n")
        f.write("| 项目 | 说明 |\n|---|---|\n")
        f.write("| 标的 | MNQ（Micro NQ E-mini，纳斯达克期货） |\n")
        f.write("| 合约规格 | 1 点 = $2，最小跳动 0.25 点 = $0.50/张 |\n")
        f.write("| 账户类型 | Profimr 50K 挑战账户 |\n")
        f.write("| 初始资金 | $50,000 |\n")
        f.write("| 最大持仓 | 30 张 MNQ（30 张 × 1 点 = $60）|\n")
        f.write("| 策略类型 | 砖型图反转策略（2连续同向砖块确立趋势） |\n")
        f.write("| 交易时段 | RTH 9:30-16:00 ET |\n\n")

        f.write("## 二、推荐参数（来自回测最优）\n\n")
        if best is not None:
            f.write("| 参数 | 值 |\n|---|---|\n")
            f.write(f"| 数据周期 | {best['interval']} |\n")
            f.write(f"| 砖块方法 | {best['method']} |\n")
            f.write(f"| 参数值 | {best['param_label']} |\n")
            f.write(f"| 预期日均交易 | {best['avg_daily_trades']:.1f} 笔 |\n\n")
        else:
            f.write("*请先运行 nq_backtest.py 获得数据*\n\n")

        f.write("## 三、Profimr 挑战达成标准\n\n")
        f.write("### 3.1 挑战号\n\n")
        f.write("| 条件 | 要求 | 达成方式 |\n|---|---|---|\n")
        f.write("| 盈利目标 | 总盈利 ≥ $3,000 | 每日稳定盈利 $150-300 |\n")
        f.write("| EOD 回撤 | 单日不超 $2,000 | 触达止损后当日停止交易 |\n")
        f.write("| 最大回撤 | $2,000（相对当日开盘） | 策略内置日亏损限制 |\n\n")
        f.write("**参考路径**（假设日均盈利 $200）：\n")
        f.write("- $3,000 / $200 = 15 个盈利日\n")
        f.write("- 建议留有 20-25 个交易日的宽裕度\n\n")

        f.write("### 3.2 出金号\n\n")
        f.write("| 条件 | 要求 |\n|---|---|\n")
        f.write("| 盈利天数 | 连续 5 日 |\n")
        f.write(f"| 每日盈利 | ≥ ${WITHDRAWAL_DAILY:.0f} |\n")
        f.write("| EOD 回撤 | 同上 $2,000 |\n\n")

        f.write("## 四、日交易计划\n\n")
        f.write("| 时段 | 操作 |\n|---|---|\n")
        f.write("| 09:00-09:30 | 盘前准备：查看隔夜走势、重要支撑阻力位 |\n")
        f.write("| 09:30-10:30 | 主要时段：捕捉开盘方向突破，跟随砖块信号 |\n")
        f.write("| 10:30-12:00 | 次要时段：趋势延续或震荡减仓 |\n")
        f.write("| 12:00-13:00 | 午休规避：流动性下降，停止开新仓 |\n")
        f.write("| 13:00-15:30 | 下午时段：等待新趋势确立 |\n")
        f.write("| 15:30-16:00 | 收盘前平仓：EOD 前确保持仓归零 |\n\n")

        f.write("## 五、风险管理规则\n\n")
        f.write("1. **每日亏损触发停止**：当日浮亏超过 $1,500 停止开新仓，浮亏 $2,000 强平所有仓位\n")
        f.write("2. **单笔止损**：每笔交易砖块级别止损，等于 1 个砖块大小（自动），30 张合约放大约 $60/点\n")
        f.write("3. **最大仓位**：不超过 30 张 MNQ，建议初期用 5-10 张试仓，盈利稳定后再加至 30 张\n")
        f.write("4. **交易次数上限**：每日不超过 15 笔，若已盈利 $300+ 可提前收工\n")
        f.write("5. **关键时段回避**：FOMC、非农、CPI 发布前后 30 分钟停止交易\n\n")

        f.write("## 六、模拟交易记录表（每日填写）\n\n")
        f.write("| 日期 | 开盘余额 | 收盘余额 | 当日盈亏 | 交易次数 | 最大回撤 | 挑战条件 |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i in range(10):
            f.write(f"| Day {i+1} | | | | | | |\n")
        f.write("\n")

        f.write("## 七、实盘 vs 模拟差异注意事项\n\n")
        f.write("| 项目 | 模拟 | 实盘影响 |\n|---|---|---|\n")
        f.write("| 滑点 | 忽略 | 每笔约 0.25 点/张 = $0.50/张，30 张 × 10 笔 = $150/日 |\n")
        f.write("| 手续费 | 忽略 | 约 $0.35-0.50/张/单边，30 张往返约 $21-30/笔 |\n")
        f.write("| 成交速度 | 即时 | 快速市场可能滑点加大 |\n")
        f.write("| 流动性 | 完美 | 大单可能影响成交 |\n\n")
        f.write("> **调整建议**：实盘预期收益应下调 10-15%（手续费+滑点）\n\n")

        f.write("---\n\n")
        f.write("> **免责声明**：本报告仅供参考，不构成投资建议。期货交易有风险，请量力而行。\n")


def _df_to_md(df: pd.DataFrame) -> str:
    """DataFrame 转 Markdown 表格"""
    lines = []
    headers = list(df.columns)
    lines.append('| ' + ' | '.join(str(h) for h in headers) + ' |')
    lines.append('|' + '|'.join(['---'] * len(headers)) + '|')
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(f"{v:.2f}" if not np.isnan(v) else 'N/A')
            elif isinstance(v, bool):
                cells.append("✅" if v else "❌")
            else:
                cells.append(str(v))
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def _print_console_summary(df_all, df_inrange, df_eval):
    """打印控制台摘要"""
    logger.info("\n" + "=" * 70)
    logger.info("📊 回测摘要")
    logger.info("=" * 70)
    logger.info(f"总参数组合测试: {len(df_all)}")
    logger.info(f"日内 3-10 笔交易符合: {len(df_inrange)}")
    logger.info(f"Profimr 挑战达成: {len(df_eval)}")

    if not df_all.empty:
        best = df_all.iloc[0]
        logger.info(f"\n🏆 综合评分最高:")
        logger.info(f"   周期={best['interval']} | 方法={best['method']} | 参数={best['param_label']}")
        logger.info(f"   日均交易={best['avg_daily_trades']:.1f} | 收益={best['total_return_pct']:+.2f}%")
        logger.info(f"   最大回撤={best['max_drawdown_pct']:.2f}% | 胜率={best['win_rate']:.1f}%")
        logger.info(f"   评分={best['composite_score']:.1f}")

    if not df_inrange.empty:
        best_inrange = df_inrange.iloc[0]
        logger.info(f"\n✅ 频率最优（3-10笔/日）:")
        logger.info(f"   周期={best_inrange['interval']} | 方法={best_inrange['method']} | 参数={best_inrange['param_label']}")
        logger.info(f"   日均交易={best_inrange['avg_daily_trades']:.1f} | 收益={best_inrange['total_return_pct']:+.2f}%")


def _plot_top_equity_curves(df_top, output_dir):
    """为 Top 参数绘制模拟权益曲线"""
    import matplotlib.pyplot as plt
    from fetch_nq_data import load_nq_data
    from core.renko_builder import RenkoBuilder
    from strategies.renko_reversal_strategy import RenkoReversalStrategy
    from nq_backtest import (
        INITIAL_CAPITAL, CONTRACT_MULT, MAX_CONTRACTS, MAX_DAILY_LOSS,
        SESSION_START_UTC, SESSION_END_UTC, filter_rth
    )

    fig, axes = plt.subplots(len(df_top), 1, figsize=(14, 5 * len(df_top)))
    if len(df_top) == 1:
        axes = [axes]

    for ax, (_, row) in zip(axes, df_top.iterrows()):
        interval = row['interval']
        method = row['method']
        param_label = row['param_label']
        param = row['param']

        df = load_nq_data(interval=interval)
        if df.empty:
            continue
        data = filter_rth(df)

        # 重建参数
        if method == 'atr':
            vals = eval(param)
            builder = RenkoBuilder(method='atr', atr_period=vals[0], atr_multiplier=vals[1])
        elif method == 'fixed':
            builder = RenkoBuilder(method='fixed', brick_size=float(param))
        elif method == 'percentage':
            builder = RenkoBuilder(method='percentage', percentage=float(param))
        else:
            continue

        try:
            renko_df = builder.build(data)
            strategy = RenkoReversalStrategy(
                initial_capital=INITIAL_CAPITAL,
                commission_rate=0.0,
                slippage_rate=0.0,
                contract_multiplier=CONTRACT_MULT,   # MNQ: $2/点
                max_contracts=MAX_CONTRACTS,          # 最大 30 张
                max_daily_loss=MAX_DAILY_LOSS,
                session_start_hour=SESSION_START_UTC,
                session_end_hour=SESSION_END_UTC,
            )
            stats = strategy.run_backtest(renko_df)

            if stats['trades']:
                times = [t.exit_time for t in stats['trades']]
                balances = [t.balance_after for t in stats['trades']]
                ax.plot(times, balances, label=f'{interval} {param_label}', color='steelblue', linewidth=1.5)
                ax.axhline(y=INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
                ax.axhline(y=INITIAL_CAPITAL + 3000, color='green', linestyle=':', alpha=0.7, label='Target +$3,000')
                ax.axhline(y=INITIAL_CAPITAL - 2000, color='red', linestyle=':', alpha=0.7, label='Max Drawdown')
                ax.set_title(f'{interval} | {param_label} | Ret:{row["total_return_pct"]:+.2f}% | DD:{row["max_drawdown_pct"]:.2f}%')
                ax.set_ylabel('Balance ($)')
                ax.legend(loc='upper left', fontsize=8)
                ax.grid(alpha=0.3)
        except Exception:
            continue

    plt.tight_layout()
    out_path = output_dir / 'nq_top_equity_curves.png'
    plt.savefig(out_path, dpi=120)
    plt.close()
    logger.info(f"权益曲线图: {out_path}")


# ============================================================
# 独立运行（从已保存的 CSV 结果生成报告）
# ============================================================

if __name__ == '__main__':
    csv_path = OUTPUT_DIR / 'nq_backtest_all.csv'
    if not csv_path.exists():
        logger.error(f"未找到回测结果文件: {csv_path}")
        logger.error("请先运行: python nq_backtest.py")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    generate_report(df)
