"""
采集币安1分钟K线数据，保存为本地CSV，供后续聚合和策略使用。
"""
import time
import pandas as pd
import requests
from datetime import datetime
from loguru import logger

BINANCE_URL = 'https://api.binance.com/api/v3/klines'
SYMBOL = 'BTCUSDT'
INTERVAL = '1m'
SAVE_PATH = 'data/processed/min_klines.csv'


def fetch_latest_kline(symbol=SYMBOL, interval=INTERVAL):
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': 1
    }
    resp = requests.get(BINANCE_URL, params=params)
    data = resp.json()
    if not data:
        return None
    k = data[0]
    return {
        'timestamp': pd.to_datetime(k[0], unit='ms'),
        'open': float(k[1]),
        'high': float(k[2]),
        'low': float(k[3]),
        'close': float(k[4]),
        'volume': float(k[5])
    }

def main():
    logger.info("启动1分钟K线采集器...")
    # 尝试加载已有数据，避免重复
    try:
        df = pd.read_csv(SAVE_PATH, parse_dates=['timestamp'])
        logger.info(f"已加载历史K线: {len(df)} 条")
    except Exception:
        df = pd.DataFrame()
    try:
        while True:
            kline = fetch_latest_kline()
            if kline is None:
                logger.warning("未获取到最新K线，重试...")
                time.sleep(5)
                continue
            # 避免重复采集
            if not df.empty and kline['timestamp'] <= df.iloc[-1]['timestamp']:
                logger.info("K线未更新，等待下一分钟...")
                time.sleep(10)
                continue
            df = pd.concat([df, pd.DataFrame([kline])], ignore_index=True)
            df.to_csv(SAVE_PATH, index=False)
            logger.info(f"采集到新K线: {kline['timestamp']} 收盘价: {kline['close']}")
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("采集器已停止。K线已保存。")

if __name__ == "__main__":
    main()
