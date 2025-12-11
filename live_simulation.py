"""
Live Simulation System
- 采集币安主网实时BTC价格（直接获取目标周期K线）
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
INTERVAL = data_cfg.get('interval', '5m')  # 直接使用目标周期
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
    logger.info("启动实时模拟交易系统（实时采集模式）...")
    
    # 1. 初始化策略类
    class LiveRenkoTrader:
        def __init__(self, strategy):
            self.strategy = strategy
            
        def process_new_brick(self, brick):
            """处理新砖块，判断是否需要交易"""
            current_price = brick['brick_close']
            timestamp = brick['timestamp']
            
            # 检测趋势反转
            trend = None
            if hasattr(self.strategy, 'detect_trend_reversal'):
                trend = self.strategy.detect_trend_reversal(pd.DataFrame([brick]), 0)
            
            if trend is not None:
                # 如果有仓位且方向不同，先平仓再开仓
                if not self.strategy.position.is_empty and self.strategy.position.direction != trend:
                    self.strategy.close_position(current_price, timestamp)
                    self.strategy.open_position(trend, current_price, timestamp)
                # 如果空仓，直接开仓
                elif self.strategy.position.is_empty:
                    self.strategy.open_position(trend, current_price, timestamp)
            
            # 更新净值
            self.strategy.update_equity(current_price)
        
        def get_stats(self):
            """获取策略统计信息"""
            return self.strategy.calculate_statistics()

    # 2. 初始化策略
    strategy = RenkoReversalStrategy(
        initial_capital=INITIAL_CAPITAL,
        commission_rate=0.0004,
        slippage_rate=0.0001
    )
    trader = LiveRenkoTrader(strategy)
    trade_log = []
    
    # 3. 获取初始历史K线数据
    logger.info(f"正在获取初始K线数据（{INTERVAL}周期）...")
    df = fetch_klines(symbol=SYMBOL, interval=INTERVAL, limit=500)
    if df.empty:
        logger.error("无法获取初始K线数据，退出系统")
        exit(1)
    logger.info(f"已获取 {len(df)} 条K线数据")
    
    # 4. 计算睡眠时间（根据周期）
    if INTERVAL.endswith('m'):
        sleep_sec = int(INTERVAL[:-1]) * 60
    elif INTERVAL.endswith('h'):
        sleep_sec = int(INTERVAL[:-1]) * 3600
    elif INTERVAL.endswith('d'):
        sleep_sec = int(INTERVAL[:-1]) * 86400
    else:
        sleep_sec = 60  # 默认1分钟
    
    logger.info(f"开始实时模拟交易，采样周期：{INTERVAL}（每{sleep_sec}秒刷新）")
    
    # 5. 主循环：实时采集并处理
    try:
        last_brick_count = 0
        last_timestamp = None
        
        while True:
            # 实时采集最新K线
            new_kline = fetch_latest_kline(symbol=SYMBOL, interval=INTERVAL)
            
            if new_kline is None:
                logger.warning("获取最新K线失败，等待重试...")
                time.sleep(10)
                continue
            
            # 检查是否是新K线（避免重复处理）
            if last_timestamp is not None and new_kline['timestamp'] <= last_timestamp:
                logger.debug(f"K线未更新，等待下一周期... (当前: {new_kline['timestamp']})")
                time.sleep(sleep_sec // 2)  # 等待半个周期再检查
                continue
            
            # 更新数据集
            last_timestamp = new_kline['timestamp']
            df = pd.concat([df, pd.DataFrame([new_kline])], ignore_index=True)
            
            # 保持数据集大小（最多1000条）
            if len(df) > 1000:
                df = df.iloc[-1000:].reset_index(drop=True)
            
            logger.info(f"采集到新K线: {new_kline['timestamp']} | Close: {new_kline['close']:.2f}")
            
            # 构建砖型图
            renko_builder = RenkoBuilder(
                method=RENKO_METHOD,
                atr_period=ATR_PERIOD,
                atr_multiplier=ATR_MULTIPLIER
            )
            renko_df = renko_builder.build(df)
            
            # 如果有新砖块生成
            if not renko_df.empty and len(renko_df) > last_brick_count:
                latest_brick = renko_df.iloc[-1]
                trader.process_new_brick(latest_brick)
                last_brick_count = len(renko_df)
                
                # 记录净值
                stats = trader.get_stats()
                trade_log.append({
                    'timestamp': datetime.now(),
                    'equity': stats['final_balance'],
                    'total_trades': stats['total_trades']
                })
                
                # ===== 实时监控窗口输出 =====
                print("\n" + "="*60)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Real-Time Monitor")
                win_rate = stats.get('win_rate', 0)
                print(f"Equity: ${stats['final_balance']:,.2f} | Trades: {stats['total_trades']} | Win Rate: {win_rate*100:.2f}%")
                print(f"Current Position: {'LONG' if strategy.position.is_long else 'SHORT' if strategy.position.is_short else 'NONE'} | Size: {strategy.position.quantity:.6f}")
                print(f"Bricks Count: {len(renko_df)} | Latest Price: {new_kline['close']:.2f}")
                print("-"*60)
                print("Recent Trades:")
                trades = stats.get('trades', [])
                
                # 检测是否有新交易（触发提示音）
                if not hasattr(strategy, '_last_trade_count'):
                    strategy._last_trade_count = 0
                new_trade_count = len(trades)
                if new_trade_count > strategy._last_trade_count:
                    print('\a', end='')  # 提示音
                strategy._last_trade_count = new_trade_count
                
                if trades:
                    for t in trades[-5:]:  # 显示最近5笔交易
                        direction_str = 'LONG' if t.direction == 1 else 'SHORT'
                        print(f"#{t.trade_id} | {direction_str} | Entry: {t.entry_price:.2f} @ {t.entry_time} | Exit: {t.exit_price:.2f} @ {t.exit_time} | PnL: {t.pnl:+.2f} | Balance: {t.balance_after:.2f}")
                else:
                    print("No trades yet.")
                print("="*60)
            
            # 等待下一个周期
            time.sleep(sleep_sec)
            
    except KeyboardInterrupt:
        logger.info("模拟交易系统已停止。保存结果...")
        
        # 保存净值曲线
        if trade_log:
            pd.DataFrame(trade_log).to_csv('data/processed/live_simulation_equity.csv', index=False)
            logger.info("净值曲线已保存到 data/processed/live_simulation_equity.csv")
        
        # 保存交易明细
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
            trades_df.to_csv('data/processed/live_simulation_trades.csv', index=False)
            logger.info("全部历史交易明细已保存到 data/processed/live_simulation_trades.csv")
        else:
            logger.info("无历史交易可保存。")
        
        logger.info("系统退出完成。")
