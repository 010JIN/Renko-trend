"""
多账户实时模拟交易系统
支持每个账户自定义交易品种、采集周期、交易计算周期、砖块构建方式
"""
import threading
import time
import yaml
from pathlib import Path
from loguru import logger
from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy
import pandas as pd
import requests

# ========== 配置结构示例 ==========
# accounts = [
#   {
#     'name': 'account1',
#     'symbol': 'BTCUSDT',
#     'fetch_interval': '1m',
#     'calc_interval': '5m',
#     'renko_method': 'atr',
#     'renko_params': {'atr_period': 14, 'atr_multiplier': 2.0},
#     'initial_capital': 10000.0
#   },
#   ...
# ]

# ========== 实时K线采集 ==========
def fetch_latest_kline(symbol, interval, limit=100):
    url = 'https://api.binance.com/api/v3/klines'
    params = {'symbol': symbol, 'interval': interval, 'limit': limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"采集K线失败: {e}")
        return None

# ========== 账户线程 ==========
def account_worker(account_cfg):
    name = account_cfg['name']
    symbol = account_cfg['symbol']
    fetch_interval = account_cfg['fetch_interval']
    calc_interval = account_cfg['calc_interval']
    renko_method = account_cfg['renko_method']
    renko_params = account_cfg.get('renko_params', {})
    initial_capital = account_cfg.get('initial_capital', 10000.0)
    logger.info(f"[{name}] 启动，品种: {symbol}，采集: {fetch_interval}，计算: {calc_interval}，方法: {renko_method}")
    kline_buffer = []
    last_calc_time = None
    while True:
        # 采集最新K线
        df = fetch_latest_kline(symbol, fetch_interval, limit=100)
        if df is None or df.empty:
            logger.warning(f"[{name}] 采集K线失败，等待10秒后重试...")
            time.sleep(10)
            continue
        kline_buffer.extend(df.to_dict('records'))
        # 聚合到计算周期
        df_all = pd.DataFrame(kline_buffer)
        df_all = df_all.drop_duplicates('timestamp').sort_values('timestamp')
        df_all.set_index('timestamp', inplace=True)
        df_agg = df_all.resample(calc_interval).agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna().reset_index()
        # 只保留最近N根
        if len(df_agg) > 200:
            df_agg = df_agg.iloc[-200:]
        # 构建砖型图
        builder = RenkoBuilder(method=renko_method, **renko_params)
        renko_df = builder.build(df_agg)
        # 执行策略
        strategy = RenkoReversalStrategy(initial_capital=initial_capital)
        stats = strategy.run_backtest(renko_df)

        # ======= 美化实时显示 =======
        latest_price = df_agg['close'].iloc[-1] if not df_agg.empty else None
        pos = strategy.position
        trades = strategy.trades[-5:] if len(strategy.trades) >= 1 else []
        print("\n" + "="*70)
        print(f"账户: {name} | 品种: {symbol} | 当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"当前价格: {latest_price:.2f}" if latest_price is not None else "当前价格: N/A")
        # 当前持仓
        if pos.is_empty:
            print("当前持仓: NONE")
        else:
            direction = 'LONG' if pos.direction == 1 else 'SHORT'
            print(f"当前持仓: {direction} | 数量: {pos.quantity:.6f} | 开仓价: {pos.entry_price:.2f} | 开仓时间: {pos.entry_time}")
        # 最近5条完整持仓记录
        print("最近5笔平仓记录:")
        if trades:
            print(f"{'#':<3} {'方向':<6} {'开仓价':>10} {'平仓价':>10} {'数量':>10} {'盈亏':>10} {'开仓时间':>19} {'平仓时间':>19}")
            for t in trades[-5:]:
                direction = 'LONG' if t.direction == 1 else 'SHORT'
                print(f"{t.trade_id:<3} {direction:<6} {t.entry_price:>10.2f} {t.exit_price:>10.2f} {t.quantity:>10.6f} {t.pnl:>10.2f} {str(t.entry_time)[0:19]:>19} {str(t.exit_time)[0:19]:>19}")
        else:
            print("无平仓记录")
        print(f"余额: {stats['final_balance']:.2f} | 总收益率: {stats['total_return_pct']*100:.2f}% | 总交易数: {stats['total_trades']}")
        print("="*70)

        # 等待下一个采集周期
        time.sleep(60)  # 每分钟采集一次，可根据fetch_interval动态调整

# ========== 主入口 ==========
def main():
    # 读取多账户配置
    config_path = Path('multi_account_config.yaml')
    if not config_path.exists():
        logger.error('请先创建 multi_account_config.yaml 配置文件！')
        return
    with open(config_path, 'r', encoding='utf-8') as f:
        accounts = yaml.safe_load(f)['accounts']
    threads = []
    for acc in accounts:
        t = threading.Thread(target=account_worker, args=(acc,), daemon=True)
        t.start()
        threads.append(t)
    logger.info(f"已启动 {len(threads)} 个账户线程。按Ctrl+C退出。")
    try:
        while True:
            # 检查线程存活，自动重启已退出线程
            for i, t in enumerate(threads):
                if not t.is_alive():
                    logger.warning(f"账户线程 {accounts[i]['name']} 意外退出，正在重启...")
                    new_t = threading.Thread(target=account_worker, args=(accounts[i],), daemon=True)
                    new_t.start()
                    threads[i] = new_t
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("用户中断，退出所有账户模拟。")
    except Exception as e:
        logger.error(f"主循环异常: {e}")
        while True:
            time.sleep(60)

if __name__ == "__main__":
    main()
