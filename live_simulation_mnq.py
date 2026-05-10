"""
MNQ 期货砖型图实时模拟交易系统 (Profimr 50K 账户)

数据源：yfinance  NQ=F（纳斯达克期货连续合约，与 MNQ=F 同价）

流程：
  1. 启动时通过 yfinance 预加载 WARMUP_BARS 根历史K线
  2. 从历史砖块中提取最近 reversal_count 个方向，写入策略方向记忆
     → 避免错过第一笔交易信号
  3. 进入主循环：每个 K 线周期末重新拉取最新数据，识别新砖块后推送给策略

合约规格（MNQ — Micro NQ E-mini）：
  - 1 点 = $2
  - 最小跳动：0.25 点 = $0.50 / 张
  - 最大持仓：30 张

Profimr 50K 账户挑战规则：
  - 初始资金：$50,000
  - 每日最大亏损：$2,000（相对当日开盘余额）
  - 挑战号盈利目标：$3,000 总盈利
  - 出金号：连续 5 个盈利日，每日 ≥ $200

交易时段（CME Globex，UTC）：
  周一–周五  22:10 → 20:00（跨午夜）
  = 北京时间 06:10 → 04:00（次日）
"""

import sys
import time
import pandas as pd
from pathlib import Path
from loguru import logger
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent))

try:
    import yfinance as yf
except ImportError:
    logger.error("请先安装 yfinance：pip install yfinance")
    sys.exit(1)

from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy

# ============================================================
# 账户 / 合约参数（Profimr 50K MNQ）
# ============================================================
TICKER               = 'NQ=F'
INITIAL_CAPITAL      = 50_000.0
CONTRACT_MULT        = 2.0          # MNQ: $2 / 点
MAX_CONTRACTS        = 30
MARGIN_PER_CONTRACT  = 1_000.0      # MNQ 日内保证金约 $500–1500，取 $1000
MAX_DAILY_LOSS       = 2_000.0      # 每日最大回撤 $2000

# 交易时段（UTC）：周一–周五 22:10 → 20:00（跨午夜 = 北京时间 06:10 → 04:00）
SESSION_START_HOUR   = 22
SESSION_START_MINUTE = 10
SESSION_END_HOUR     = 20
SESSION_END_MINUTE   = 0

# ============================================================
# 砖型图 / 策略参数（可按需修改）
# ============================================================
INTERVAL         = '5m'   # '5m' 或 '15m'（yfinance 支持范围内）
RENKO_METHOD     = 'atr'  # 'atr' 或 'fixed'
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 1.0    # ATR 法倍数
FIXED_BRICK_SIZE = 20.0   # 固定法：NQ 点数（对应 MNQ = $40/砖）
REVERSAL_COUNT   = 2      # 趋势确认所需连续同向砖块数
WARMUP_BARS      = 100    # 启动时预加载的历史K线根数


# ============================================================
# yfinance 数据获取
# ============================================================

def _yf_interval_to_period(interval: str) -> str:
    """根据 K 线周期选择 yfinance period 参数（覆盖 WARMUP_BARS 所需历史）"""
    # WARMUP_BARS * interval → 需要多少天历史
    units = {'m': 1 / 1440, 'h': 1 / 24, 'd': 1}
    num = int(''.join(filter(str.isdigit, interval)))
    unit = ''.join(filter(str.isalpha, interval))
    days_needed = WARMUP_BARS * num * units.get(unit, 1 / 1440)
    # 向上取整，最少 2 天，最多 7 天（yfinance 1m 限制），60 天（5m/15m 限制）
    days = max(2, int(days_needed) + 1)
    if unit == 'm' and num == 1:
        return f"{min(days, 7)}d"
    if unit == 'm':
        return f"{min(days, 60)}d"
    if unit == 'h':
        return f"{min(days, 730)}d"
    return "60d"


def fetch_nq_bars(interval: str = INTERVAL, limit: int = WARMUP_BARS) -> pd.DataFrame:
    """
    通过 yfinance 获取 NQ=F 历史K线，返回最新 limit 根（标准 OHLCV DataFrame）。
    时间戳为 UTC datetime（无时区，便于直接比较）。
    """
    period = _yf_interval_to_period(interval)
    logger.info(f"获取 {TICKER} {interval} 数据 (period={period}) ...")
    try:
        ticker = yf.Ticker(TICKER)
        df = ticker.history(period=period, interval=interval, auto_adjust=True, prepost=False)
        if df.empty:
            logger.warning(f"yfinance 返回空数据（{TICKER} {interval}）")
            return pd.DataFrame()

        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]

        # 统一时间戳列名并去时区
        for col in ('datetime', 'date'):
            if col in df.columns:
                df.rename(columns={col: 'timestamp'}, inplace=True)
                break
        df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)

        keep = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df = df[[c for c in keep if c in df.columns]].dropna(subset=['open', 'close'])
        df = df.reset_index(drop=True)

        # 只保留最近 limit 根
        if len(df) > limit:
            df = df.iloc[-limit:].reset_index(drop=True)

        logger.info(f"  ✓ {len(df)} 根 K 线 | {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
        return df
    except Exception as e:
        logger.error(f"yfinance 获取数据失败: {e}")
        return pd.DataFrame()


def fetch_nq_latest(interval: str = INTERVAL, look_back: int = 5) -> pd.DataFrame:
    """
    获取最近 look_back 根 K 线（用于主循环检测新K线）。
    """
    return fetch_nq_bars(interval=interval, limit=look_back)


# ============================================================
# 辅助：根据周期字符串计算轮询睡眠秒数
# ============================================================

def _interval_to_seconds(interval: str) -> int:
    num = int(''.join(filter(str.isdigit, interval)))
    unit = ''.join(filter(str.isalpha, interval))
    return num * {'m': 60, 'h': 3600, 'd': 86400}.get(unit, 60)


# ============================================================
# 主程序
# ============================================================

def main():
    logger.info("=" * 65)
    logger.info("📈  MNQ 实时模拟交易系统 — Profimr 50K 账户")
    logger.info("=" * 65)
    logger.info(f"  合约：{TICKER}  周期：{INTERVAL}  方法：{RENKO_METHOD}")
    logger.info(f"  初始资金：${INITIAL_CAPITAL:,.0f}  每日限损：${MAX_DAILY_LOSS:,.0f}")
    logger.info(f"  交易时段（UTC）：{SESSION_START_HOUR:02d}:{SESSION_START_MINUTE:02d}"
                f" → {SESSION_END_HOUR:02d}:{SESSION_END_MINUTE:02d}  仅周一–周五")
    logger.info("=" * 65)

    # ----------------------------------------------------------
    # 1. 初始化砖型图构建器
    # ----------------------------------------------------------
    if RENKO_METHOD == 'atr':
        builder = RenkoBuilder(method='atr', atr_period=ATR_PERIOD, atr_multiplier=ATR_MULTIPLIER)
        logger.info(f"砖型图：ATR({ATR_PERIOD}) × {ATR_MULTIPLIER}")
    else:
        builder = RenkoBuilder(method='fixed', brick_size=FIXED_BRICK_SIZE)
        logger.info(f"砖型图：固定 {FIXED_BRICK_SIZE} 点")

    # ----------------------------------------------------------
    # 2. 初始化策略（MNQ 参数 + 时段过滤）
    # ----------------------------------------------------------
    strategy = RenkoReversalStrategy(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=0.0,              # MNQ 按张计算，此处忽略（约 $0.35–0.50 / 张 / 单边）
        slippage_rate=0.0,                # MNQ 最小跳 0.25 点 = $0.50 / 张，此处忽略
        contract_multiplier=CONTRACT_MULT,
        max_contracts=MAX_CONTRACTS,
        margin_per_contract=MARGIN_PER_CONTRACT,
        max_daily_loss=MAX_DAILY_LOSS,
        session_start_hour=SESSION_START_HOUR,
        session_start_minute=SESSION_START_MINUTE,
        session_end_hour=SESSION_END_HOUR,
        session_end_minute=SESSION_END_MINUTE,
        session_weekdays_only=True,
        reversal_count=REVERSAL_COUNT,
    )

    # ----------------------------------------------------------
    # 3. 预加载历史K线 → 预热砖型图 → 写入方向记忆
    # ----------------------------------------------------------
    logger.info(f"预加载 {WARMUP_BARS} 根历史K线用于预热砖型图...")
    df_hist = fetch_nq_bars(interval=INTERVAL, limit=WARMUP_BARS)
    if df_hist.empty:
        logger.error("无法获取历史数据，退出。请检查网络或 yfinance 安装。")
        sys.exit(1)

    renko_df = builder.build(df_hist)
    last_brick_count = len(renko_df)

    if last_brick_count == 0:
        logger.warning("历史数据不足以生成砖块，策略将在首个信号出现后才开始运作。")
    else:
        # 用最近 reversal_count 个砖块的方向预热策略，避免错过第一笔信号
        seed_bricks = renko_df.iloc[-min(REVERSAL_COUNT, last_brick_count):]
        strategy._recent_directions = [int(b['direction']) for _, b in seed_bricks.iterrows()]
        logger.info(f"✓ 砖型图预热完成：{last_brick_count} 根砖块 | "
                    f"最近方向记忆：{strategy._recent_directions}")

    # 记录最新已知K线时间戳（用于去重）
    last_kline_ts = df_hist['timestamp'].iloc[-1]
    # 主循环数据缓冲
    df_buffer = df_hist.copy()

    sleep_sec = _interval_to_seconds(INTERVAL)
    logger.info(f"进入主循环，每 {sleep_sec} 秒轮询一次（{INTERVAL} 周期）")
    logger.info("按 Ctrl+C 停止并保存结果。")

    trade_log = []

    # ----------------------------------------------------------
    # 4. 主循环
    # ----------------------------------------------------------
    try:
        while True:
            time.sleep(sleep_sec)

            latest = fetch_nq_latest(interval=INTERVAL, look_back=5)
            if latest.empty:
                logger.warning("获取最新K线失败，等待重试...")
                continue

            # 过滤出真正新的K线
            new_bars = latest[latest['timestamp'] > last_kline_ts]
            if new_bars.empty:
                logger.debug(f"无新K线（最新时间戳：{last_kline_ts}）")
                continue

            # 追加到缓冲（保留最近 1000 根）
            df_buffer = pd.concat([df_buffer, new_bars], ignore_index=True)
            df_buffer = df_buffer.drop_duplicates('timestamp').sort_values('timestamp')
            if len(df_buffer) > 1000:
                df_buffer = df_buffer.iloc[-1000:].reset_index(drop=True)

            last_kline_ts = df_buffer['timestamp'].iloc[-1]

            # 重建砖型图
            renko_df = builder.build(df_buffer)

            # 处理新砖块
            if len(renko_df) > last_brick_count:
                new_bricks = renko_df.iloc[last_brick_count:]
                for _, brick in new_bricks.iterrows():
                    signal = strategy.on_brick(brick)
                    sym = "🟢" if brick['direction'] == 1 else "🔴"
                    sig_text = {"open": "开仓", "reverse": "反转", "hold": "持有"}.get(signal, signal)
                    logger.info(
                        f"{sym} 新砖块 | {brick['timestamp']} | "
                        f"收盘价: {brick['brick_close']:.2f} 点 | 信号: {sig_text}"
                    )

                last_brick_count = len(renko_df)

                # 统计快照
                stats = strategy.calculate_statistics()
                trade_log.append({
                    'timestamp': datetime.utcnow(),
                    'equity': strategy.equity,
                    'balance': strategy.balance,
                    'total_trades': stats['total_trades'],
                })

                # ---- 实时监控输出 ----
                pos = strategy.position
                pos_str = ('LONG' if pos.is_long else 'SHORT' if pos.is_short else 'NONE')
                unrealized = 0.0
                if not pos.is_empty and not renko_df.empty:
                    last_close = renko_df['brick_close'].iloc[-1]
                    unrealized = (last_close - pos.entry_price) * pos.direction * pos.quantity * CONTRACT_MULT
                win_rate = stats.get('win_rate', 0.0)

                print("\n" + "=" * 65)
                print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC]  MNQ 实时模拟")
                print(f"  余额: ${strategy.balance:,.2f}  |  "
                      f"浮动盈亏: ${unrealized:+,.2f}  |  "
                      f"总权益: ${strategy.equity:,.2f}")
                print(f"  持仓: {pos_str}  张数: {int(pos.quantity)}  "
                      f"开仓价: {pos.entry_price:.2f}")
                print(f"  总交易: {stats['total_trades']}  胜率: {win_rate*100:.1f}%  "
                      f"最大回撤: ${stats.get('max_drawdown', 0):.2f}")
                trades = stats.get('trades', [])
                if trades:
                    print("  最近 5 笔交易：")
                    for t in trades[-5:]:
                        d = 'LONG' if t.direction == 1 else 'SHORT'
                        print(f"    #{t.trade_id} {d} "
                              f"入:{t.entry_price:.2f} 出:{t.exit_price:.2f} "
                              f"PnL:${t.pnl:+,.2f}  余额:${t.balance_after:,.2f}")
                print("=" * 65)

    except KeyboardInterrupt:
        logger.info("\n模拟交易系统已停止，正在保存结果...")

        out_dir = Path('data/processed')
        out_dir.mkdir(parents=True, exist_ok=True)

        if trade_log:
            pd.DataFrame(trade_log).to_csv(
                out_dir / 'mnq_simulation_equity.csv', index=False)
            logger.info("净值曲线 → data/processed/mnq_simulation_equity.csv")

        if strategy.trades:
            trades_df = pd.DataFrame([
                {
                    'trade_id':      t.trade_id,
                    'direction':     'LONG' if t.direction == 1 else 'SHORT',
                    'entry_time':    t.entry_time,
                    'entry_price':   t.entry_price,
                    'exit_time':     t.exit_time,
                    'exit_price':    t.exit_price,
                    'contracts':     int(t.quantity),
                    'pnl':           t.pnl,
                    'pnl_pct':       t.pnl_pct,
                    'balance_before': t.balance_before,
                    'balance_after':  t.balance_after,
                } for t in strategy.trades
            ])
            trades_df.to_csv(out_dir / 'mnq_simulation_trades.csv', index=False)
            logger.info(f"交易记录 ({len(strategy.trades)} 笔) → "
                        "data/processed/mnq_simulation_trades.csv")

        final_stats = strategy.calculate_statistics()
        logger.info("=" * 65)
        logger.info("📊 最终统计")
        logger.info(f"  初始资金：${INITIAL_CAPITAL:,.2f}")
        logger.info(f"  最终余额：${strategy.balance:,.2f}")
        logger.info(f"  总盈亏：${strategy.balance - INITIAL_CAPITAL:+,.2f}")
        logger.info(f"  总交易：{final_stats['total_trades']}")
        logger.info(f"  胜率：{final_stats.get('win_rate', 0)*100:.1f}%")
        logger.info(f"  最大回撤：${final_stats.get('max_drawdown', 0):.2f}")
        logger.info("=" * 65)


if __name__ == '__main__':
    main()
