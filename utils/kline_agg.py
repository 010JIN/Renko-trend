"""
K线聚合工具：将1分钟K线聚合为任意周期（如5m、15m、30m等），严格对齐真实市场时间。
"""
import pandas as pd
import numpy as np
from loguru import logger

def aggregate_klines(df_1m: pd.DataFrame, target_interval: str = '5m') -> pd.DataFrame:
    """
    将1分钟K线聚合为目标周期K线。
    支持5m、15m、30m、1h等，严格对齐市场时间。
    Args:
        df_1m: 包含1分钟K线的DataFrame，需有timestamp、open、high、low、close、volume列
        target_interval: 目标周期字符串，如'5m', '15m', '30m', '1h'
    Returns:
        聚合后的K线DataFrame
    """
    df = df_1m.copy()
    df = df.sort_values('timestamp')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # 设置时间为index
    df.set_index('timestamp', inplace=True)
    # 计算聚合周期
    rule = target_interval
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    df_agg = df.resample(rule, label='right', closed='right').agg(agg_dict)
    df_agg = df_agg.dropna().reset_index()
    logger.info(f"已聚合为{target_interval}周期K线，共{len(df_agg)}根")
    return df_agg

if __name__ == "__main__":
    # 示例：将本地1分钟K线聚合为5分钟K线
    df_1m = pd.read_csv('data/processed/min_klines.csv', parse_dates=['timestamp'])
    df_5m = aggregate_klines(df_1m, target_interval='5m')
    df_5m.to_csv('data/processed/agg_klines_5m.csv', index=False)
    logger.info("5分钟K线已保存到 data/processed/agg_klines_5m.csv")
