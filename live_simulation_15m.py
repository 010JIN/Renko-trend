"""
Live Simulation System (15m)
- 采集币安主网实时BTC价格（直接获取15分钟K线）
- 动态计算砖型图
- 使用默认策略进行本地模拟交易
- 记录交易和净值变化
"""
import time
import pandas as pd
from loguru import logger
from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy
from datetime import datetime
import yaml
import requests

# ====== 配置参数 ======
with open('config/config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
data_cfg = config.get('data', {})
SYMBOL = data_cfg.get('symbol', 'BTCUSDT')
INTERVAL = '15m'  # 固定使用15分钟周期
RENKO_METHOD = config.get('renko', {}).get('method', 'atr')
ATR_PERIOD = config.get('renko', {}).get('atr_period', 14)
ATR_MULTIPLIER = config.get('renko', {}).get('atr_multiplier', 2.0)
INITIAL_CAPITAL = config.get('strategy', {}).get('initial_capital', 10000.0)

BINANCE_URL = 'https://api.binance.com/api/v3/klines'

def fetch_klines(symbol=SYMBOL, interval=INTERVAL, limit=500):
    """获取历史K线数据"""
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    try:
        resp = requests.get(BINANCE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # 检查是否返回错误信息
        if isinstance(data, dict):
            if 'code' in data:
                logger.error(f"API错误: {data.get('msg', 'Unknown error')}")
                return pd.DataFrame()
        
        if not data or not isinstance(data, list):
            logger.error(f"API返回数据格式错误: {data}")
            return pd.DataFrame()
        
        klines = []
        for k in data:
            if not isinstance(k, list) or len(k) < 6:
                logger.warning(f"跳过无效K线数据: {k}")
                continue
            klines.append({
                'timestamp': pd.to_datetime(int(k[0]), unit='ms'),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5])
            })
        return pd.DataFrame(klines)
    except Exception as e:
        logger.error(f"获取K线数据失败: {e}")
        return pd.DataFrame()

def fetch_latest_kline(symbol=SYMBOL, interval=INTERVAL):
    """实时采集最新的一条K线"""
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': 1
    }
    try:
        resp = requests.get(BINANCE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # 检查是否返回错误信息
        if isinstance(data, dict):
            if 'code' in data:
                logger.error(f"API错误: {data.get('msg', 'Unknown error')}")
                return None
        
        if not data or not isinstance(data, list) or len(data) == 0:
            logger.error(f"API返回数据格式错误: {data}")
            return None
        
        k = data[0]
        if not isinstance(k, list) or len(k) < 6:
            logger.warning(f"无效K线数据: {k}")
            return None
            
        return {
            'timestamp': pd.to_datetime(int(k[0]), unit='ms'),
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4]),
            'volume': float(k[5])
        }
    except Exception as e:
        logger.error(f"获取最新K线失败: {e}")
        return None


if __name__ == "__main__":
    logger.info("启动实时模拟交易系统（15分钟周期，实时采集模式）...")

    # 1. 初始化策略
    strategy = RenkoReversalStrategy(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=0.0004,
        slippage_rate=0.0001
    )
    trade_log = []

    # 2. 获取初始历史K线数据
    logger.info(f"正在获取初始K线数据（{INTERVAL}周期）...")
    df = fetch_klines(symbol=SYMBOL, interval=INTERVAL, limit=500)
    if df.empty:
        logger.error("无法获取初始K线数据，退出系统")
        exit(1)
    logger.info(f"已获取 {len(df)} 条K线数据")

    # 3. 用历史数据预热策略状态
    renko_builder = RenkoBuilder(
        method=RENKO_METHOD,
        atr_period=ATR_PERIOD,
        atr_multiplier=ATR_MULTIPLIER
    )
    renko_df = renko_builder.build(df)
    last_brick_count = len(renko_df)

    if len(renko_df) >= 2:
        strategy._recent_directions = [
            int(renko_df.iloc[-2]['direction']),
            int(renko_df.iloc[-1]['direction'])
        ]
        logger.info(f"策略已用历史砖块预热，最近方向: {strategy._recent_directions}")

    # 4. 睡眠时间（15分钟 = 900秒）
    sleep_sec = 900

    logger.info(f"开始实时模拟交易，采样周期：{INTERVAL}（每{sleep_sec}秒刷新）")

    # 5. 主循环
    try:
        last_timestamp = None

        while True:
            new_kline = fetch_latest_kline(symbol=SYMBOL, interval=INTERVAL)

            if new_kline is None:
                logger.warning("获取最新K线失败，等待重试...")
                time.sleep(30)
                continue

            if last_timestamp is not None and new_kline['timestamp'] <= last_timestamp:
                logger.debug(f"K线未更新，等待下一周期... (当前: {new_kline['timestamp']})")
                time.sleep(sleep_sec // 2)
                continue

            last_timestamp = new_kline['timestamp']
            df = pd.concat([df, pd.DataFrame([new_kline])], ignore_index=True)

            if len(df) > 1000:
                df = df.iloc[-1000:].reset_index(drop=True)

            logger.info(f"采集到新K线: {new_kline['timestamp']} | Close: {new_kline['close']:.2f}")

            renko_builder_new = RenkoBuilder(
                method=RENKO_METHOD,
                atr_period=ATR_PERIOD,
                atr_multiplier=ATR_MULTIPLIER
            )
            renko_df = renko_builder_new.build(df)

            # 处理新砖块（逐块推送给 on_brick）
            if not renko_df.empty and len(renko_df) > last_brick_count:
                new_bricks = renko_df.iloc[last_brick_count:]
                for _, brick in new_bricks.iterrows():
                    signal = strategy.on_brick(brick)
                    direction_symbol = "🟢" if brick['direction'] == 1 else "🔴"
                    signal_text = {"open": "开仓", "reverse": "反转", "hold": "持有"}.get(signal, signal)
                    logger.info(f"{direction_symbol} 新砖块 | 价格: {brick['brick_close']:.2f} | 信号: {signal_text}")

                last_brick_count = len(renko_df)

                stats = strategy.calculate_statistics()
                trade_log.append({
                    'timestamp': datetime.now(),
                    'equity': strategy.equity,
                    'balance': strategy.balance,
                    'total_trades': stats['total_trades']
                })

                print("\n" + "="*60)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Real-Time Monitor (15m)")
                win_rate = stats.get('win_rate', 0)
                print(f"Equity: ${strategy.equity:,.2f} | Balance: ${strategy.balance:,.2f} | Trades: {stats['total_trades']} | Win Rate: {win_rate*100:.2f}%")
                print(f"Position: {'LONG' if strategy.position.is_long else 'SHORT' if strategy.position.is_short else 'NONE'} | Size: {strategy.position.quantity:.4f}")
                print(f"Bricks: {len(renko_df)} | Latest Close: {new_kline['close']:.2f}")
                print("-"*60)
                trades = stats.get('trades', [])
                if trades:
                    print("Recent Trades (last 5):")
                    for t in trades[-5:]:
                        direction_str = 'LONG' if t.direction == 1 else 'SHORT'
                        print(f"  #{t.trade_id} {direction_str} | In:{t.entry_price:.2f} Out:{t.exit_price:.2f} | PnL:{t.pnl:+.2f} | Bal:{t.balance_after:.2f}")
                else:
                    print("No trades yet.")
                print("="*60)

            time.sleep(sleep_sec)

    except KeyboardInterrupt:
        logger.info("模拟交易系统已停止。保存结果...")

        if trade_log:
            pd.DataFrame(trade_log).to_csv('data/processed/live_simulation_equity_15m.csv', index=False)
            logger.info("净值曲线已保存到 data/processed/live_simulation_equity_15m.csv")

        trades = strategy.trades if hasattr(strategy, 'trades') else []
        if trades:
            trades_df = pd.DataFrame([
                {
                    'trade_id': t.trade_id,
                    'direction': 'LONG' if t.direction == 1 else 'SHORT',
                    'entry_time': t.entry_time,
                    'entry_price': t.entry_price,
                    'exit_time': t.exit_time,
                    'exit_price': t.exit_price,
                    'quantity': t.quantity,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                    'balance_before': t.balance_before,
                    'balance_after': t.balance_after
                } for t in trades
            ])
            trades_df.to_csv('data/processed/live_simulation_trades_15m.csv', index=False)
            logger.info("交易记录已保存到 data/processed/live_simulation_trades_15m.csv")
        else:
            logger.info("无历史交易可保存。")

        logger.info("系统退出完成。")