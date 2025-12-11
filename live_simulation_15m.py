"""
Live Simulation System (15m)
- 采集币安主网实时BTC价格（15分钟K线）
- 动态计算砖型图
- 使用默认策略进行本地模拟交易
- 记录交易和净值变化
"""

import time
import pandas as pd
from loguru import logger
from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy
from utils.kline_agg import aggregate_klines
from datetime import datetime

# ====== 配置参数 ======
SYMBOL = 'BTCUSDT'
TARGET_INTERVAL = '15m'
RENKO_METHOD = 'atr'
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
INITIAL_CAPITAL = 10000.0
MIN_KLINE_PATH = 'data/processed/min_klines.csv'

if __name__ == "__main__":
    logger.info("启动15分钟周期实时模拟交易系统（基于1分钟K线聚合）...")
    # 1. 加载本地1分钟K线
    try:
        df_1m = pd.read_csv(MIN_KLINE_PATH, parse_dates=['timestamp'])
        logger.info(f"已加载1分钟K线: {len(df_1m)} 条")
    except Exception:
        logger.error(f"未找到1分钟K线数据，请先运行采集器生成 {MIN_KLINE_PATH}")
        exit(1)

    # 2. 聚合为15分钟K线
    df = aggregate_klines(df_1m, target_interval=TARGET_INTERVAL)

    # 3. 初始化策略
    renko_df = pd.DataFrame()
    class LiveRenkoTrader:
        def __init__(self, strategy):
            self.strategy = strategy
        def process_new_brick(self, brick):
            current_price = brick['brick_close']
            timestamp = brick['timestamp']
            trend = None
            if hasattr(self.strategy, 'detect_trend_reversal'):
                trend = self.strategy.detect_trend_reversal(pd.DataFrame([brick]), 0)
            if trend is not None:
                if not self.strategy.position.is_empty and self.strategy.position.direction != trend:
                    self.strategy.close_position(current_price, timestamp)
                    self.strategy.open_position(trend, current_price, timestamp)
                elif self.strategy.position.is_empty:
                    self.strategy.open_position(trend, current_price, timestamp)
            self.strategy.update_equity(current_price)
        def get_stats(self):
            return self.strategy.calculate_statistics()

    strategy = RenkoReversalStrategy(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=0.0004,
        slippage_rate=0.0001
    )
    trader = LiveRenkoTrader(strategy)
    trade_log = []
    # 4. 主循环：每次聚合最新K线，模拟交易
    try:
        last_len = 0
        while True:
            # 动态加载最新1分钟K线
            df_1m = pd.read_csv(MIN_KLINE_PATH, parse_dates=['timestamp'])
            df = aggregate_klines(df_1m, target_interval=TARGET_INTERVAL)
            if len(df) == last_len:
                time.sleep(10)
                continue
            last_len = len(df)
            # 只保留最近1000根K线
            if len(df) > 1000:
                df = df.iloc[-1000:]
            renko_builder = RenkoBuilder(method=RENKO_METHOD, atr_period=ATR_PERIOD, atr_multiplier=ATR_MULTIPLIER)
            renko_df = renko_builder.build(df)
            if not renko_df.empty:
                latest_brick = renko_df.iloc[-1]
                trader.process_new_brick(latest_brick)
                stats = trader.get_stats()
                trade_log.append({
                    'timestamp': datetime.now(),
                    'equity': stats['final_balance'],
                    'total_trades': stats['total_trades']
                })
                # ===== 实时监控窗口输出 =====
                print("\n" + "="*60)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Real-Time Monitor (15m)")
                win_rate = stats.get('win_rate', 0)
                print(f"Equity: ${stats['final_balance']:,.2f} | Trades: {stats['total_trades']} | Win Rate: {win_rate*100:.2f}%")
                print(f"Current Position: {'LONG' if strategy.position.is_long else 'SHORT' if strategy.position.is_short else 'NONE'} | Size: {strategy.position.quantity:.6f}")
                print("-"*60)
                print("Recent Trades:")
                trades = stats.get('trades', [])
                if not hasattr(strategy, '_last_trade_count'):
                    strategy._last_trade_count = 0
                new_trade_count = len(trades)
                if new_trade_count > strategy._last_trade_count:
                    print('\a', end='')
                strategy._last_trade_count = new_trade_count
                if trades:
                    for t in trades[-5:]:
                        print(f"#{t.trade_id} | {'LONG' if t.direction==1 else 'SHORT'} | Entry: {t.entry_price:.2f} @ {t.entry_time} | Exit: {t.exit_price:.2f} @ {t.exit_time} | PnL: {t.pnl:+.2f} | Balance: {t.balance_after:.2f}")
                else:
                    print("No trades yet.")
                print("="*60)
            # 采样频率与目标周期一致
            if TARGET_INTERVAL.endswith('m'):
                sleep_sec = int(TARGET_INTERVAL[:-1]) * 60
            elif TARGET_INTERVAL.endswith('h'):
                sleep_sec = int(TARGET_INTERVAL[:-1]) * 3600
            else:
                sleep_sec = 60
            time.sleep(sleep_sec)
    except KeyboardInterrupt:
        logger.info("模拟交易系统已停止。保存结果...")
        pd.DataFrame(trade_log).to_csv('data/processed/live_simulation_equity_15m.csv', index=False)
        logger.info("净值曲线已保存。")