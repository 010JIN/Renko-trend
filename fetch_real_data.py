"""
简化版数据采集器 - 使用公开API
带重试机制和多数据源支持
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
import time
import json

# ==================== 配置参数 ====================
# 交易对配置
SYMBOLS = ['BTCUSDT', 'ETHUSDT']  # 支持的币种

# 时间周期配置
INTERVAL = '5m'  # 支持: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M

# 数据范围配置
DAYS_BACK = 365  # 回溯天数（1年）
START_DATE = None  # 可指定开始日期，格式: '2024-01-01'，None则使用DAYS_BACK
END_DATE = None    # 可指定结束日期，格式: '2024-12-31'，None则使用当前时间

# 数据保存路径
SAVE_PATH = 'data/raw'

# API配置
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY = 2  # 重试延迟（秒）
REQUEST_DELAY = 1  # 请求间隔（秒）
# ==================================================


def fetch_binance_klines(
    symbol: str = 'BTCUSDT',
    interval: str = '5m',
    start_time: int = None,
    end_time: int = None,
    limit: int = 1000
):
    """
    从币安公开API获取K线数据（无需API密钥）

    Args:
        symbol: 交易对
        interval: 时间间隔
        start_time: 开始时间戳（毫秒）
        end_time: 结束时间戳（毫秒）
        limit: 单次请求数据条数（最大1000）
    """
    url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    
    if start_time:
        params['startTime'] = start_time
    if end_time:
        params['endTime'] = end_time

    try:
        logger.info(f"从币安获取 {symbol} 数据...")
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        # 转换为DataFrame
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        # 数据类型转换
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['datetime'] = df['timestamp']

        # 添加元数据
        df['symbol'] = symbol.replace('USDT', '/USDT')
        df['exchange'] = 'binance'
        df['timeframe'] = interval

        # 只保留需要的列
        df = df[['timestamp', 'datetime', 'open', 'high', 'low', 'close',
                'volume', 'symbol', 'exchange', 'timeframe']]

        logger.info(f"✓ 成功获取 {len(df)} 条数据")
        return df

    except requests.exceptions.RequestException as e:
        logger.error(f"✗ 请求失败: {e}")
        return None


def fetch_with_retry(fetch_func, max_retries=3, delay=2):
    """带重试机制的数据获取"""
    for attempt in range(max_retries):
        try:
            result = fetch_func()
            if result is not None:
                return result
        except Exception as e:
            logger.warning(f"尝试 {attempt + 1}/{max_retries} 失败: {e}")

        if attempt < max_retries - 1:
            logger.info(f"等待 {delay} 秒后重试...")
            time.sleep(delay)

    return None


def collect_historical_data(
    symbol: str,
    interval: str,
    days_back: int = None,
    start_date: str = None,
    end_date: str = None
) -> pd.DataFrame:
    """
    采集历史数据（支持大批量数据）

    Args:
        symbol: 交易对
        interval: 时间周期
        days_back: 回溯天数（与start_date二选一）
        start_date: 开始日期字符串 '2024-01-01'
        end_date: 结束日期字符串 '2024-12-31'
    """
    # 计算时间范围
    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        end_dt = datetime.now()
    
    if start_date:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    elif days_back:
        start_dt = end_dt - timedelta(days=days_back)
    else:
        raise ValueError("必须指定 days_back 或 start_date")
    
    logger.info(f"采集 {symbol} 从 {start_dt.date()} 到 {end_dt.date()} 的数据")
    
    # 转换为时间戳（毫秒）
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    
    # 计算时间间隔（毫秒）
    interval_ms = {
        '1m': 60 * 1000,
        '3m': 3 * 60 * 1000,
        '5m': 5 * 60 * 1000,
        '15m': 15 * 60 * 1000,
        '30m': 30 * 60 * 1000,
        '1h': 60 * 60 * 1000,
        '2h': 2 * 60 * 60 * 1000,
        '4h': 4 * 60 * 60 * 1000,
        '6h': 6 * 60 * 60 * 1000,
        '12h': 12 * 60 * 60 * 1000,
        '1d': 24 * 60 * 60 * 1000,
    }.get(interval, 5 * 60 * 1000)
    
    all_data = []
    current_start = start_ms
    batch_count = 0
    
    while current_start < end_ms:
        batch_count += 1
        
        # 获取一批数据（最多1000条）
        df = fetch_with_retry(
            lambda: fetch_binance_klines(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_ms,
                limit=1000
            ),
            max_retries=MAX_RETRIES,
            delay=RETRY_DELAY
        )
        
        if df is None or len(df) == 0:
            logger.warning(f"批次 {batch_count} 无数据，停止采集")
            break
        
        all_data.append(df)
        logger.info(f"  批次 {batch_count}: 获取 {len(df)} 条，"
                   f"时间: {df['datetime'].min()} 到 {df['datetime'].max()}")
        
        # 更新起始时间（最后一条数据的时间 + 1个interval）
        last_timestamp = int(df['timestamp'].iloc[-1].timestamp() * 1000)
        current_start = last_timestamp + interval_ms
        
        # 如果获取的数据少于1000条，说明已到最新数据
        if len(df) < 1000:
            break
        
        # 避免API限流
        time.sleep(REQUEST_DELAY)
    
    if not all_data:
        logger.error(f"未能获取 {symbol} 的任何数据")
        return None
    
    # 合并所有数据
    final_df = pd.concat(all_data, ignore_index=True)
    
    # 去重（基于时间戳）
    final_df = final_df.drop_duplicates(subset=['timestamp'], keep='first')
    final_df = final_df.sort_values('timestamp').reset_index(drop=True)
    
    logger.info(f"✓ {symbol} 总计获取 {len(final_df):,} 条数据")
    return final_df


def collect_data(symbols=None, interval=None, days_back=None, start_date=None, end_date=None):
    """
    采集多个交易对的数据

    Args:
        symbols: 交易对列表（默认使用全局SYMBOLS）
        interval: 时间间隔（默认使用全局INTERVAL）
        days_back: 回溯天数（默认使用全局DAYS_BACK）
        start_date: 开始日期（默认使用全局START_DATE）
        end_date: 结束日期（默认使用全局END_DATE）
    """
    # 使用全局配置作为默认值
    symbols = symbols or SYMBOLS
    interval = interval or INTERVAL
    days_back = days_back if days_back is not None else DAYS_BACK
    start_date = start_date or START_DATE
    end_date = end_date or END_DATE
    
    logger.info("="*60)
    logger.info("开始采集真实市场数据")
    logger.info(f"交易对: {symbols}")
    logger.info(f"周期: {interval}")
    if start_date:
        logger.info(f"时间范围: {start_date} 到 {end_date or '现在'}")
    else:
        logger.info(f"时间范围: 最近 {days_back} 天")
    logger.info("="*60)

    results = {}

    for symbol in symbols:
        logger.info(f"\n处理 {symbol}...")

        # 采集历史数据
        df = collect_historical_data(
            symbol=symbol,
            interval=interval,
            days_back=days_back,
            start_date=start_date,
            end_date=end_date
        )

        if df is not None and len(df) > 0:
            results[df['symbol'].iloc[0]] = df

            # 显示统计
            logger.info(f"  数据量: {len(df):,} 条")
            logger.info(f"  时间范围: {df['datetime'].min()} 到 {df['datetime'].max()}")
            logger.info(f"  价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")
            logger.info(f"  最新价格: ${df['close'].iloc[-1]:,.2f}")
        else:
            logger.error(f"  ✗ {symbol} 数据获取失败")

        # 避免API限流
        time.sleep(REQUEST_DELAY)

    logger.info(f"\n{'='*60}")
    logger.info(f"采集完成！成功: {len(results)}/{len(symbols)}")
    logger.info("="*60)

    return results


def save_data(data: dict, save_path: str = 'data/raw'):
    """保存数据"""
    save_dir = Path(save_path)
    save_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"\n保存数据到: {save_path}")

    for symbol, df in data.items():
        symbol_clean = symbol.replace('/', '_')
        date_str = datetime.now().strftime('%Y%m%d')

        # CSV
        csv_file = save_dir / f"{symbol_clean}_{df['timeframe'].iloc[0]}_{date_str}.csv"
        df.to_csv(csv_file, index=False)
        logger.info(f"  ✓ {csv_file.name}")

        # Parquet
        parquet_file = csv_file.with_suffix('.parquet')
        df.to_parquet(parquet_file, index=False)
        logger.info(f"  ✓ {parquet_file.name}")


if __name__ == "__main__":
    import sys

    try:
        # 显示配置
        logger.info("\n" + "="*60)
        logger.info("📊 数据采集配置")
        logger.info("="*60)
        logger.info(f"币种: {', '.join(SYMBOLS)}")
        logger.info(f"周期: {INTERVAL}")
        logger.info(f"时间范围: 最近 {DAYS_BACK} 天")
        logger.info(f"保存路径: {SAVE_PATH}")
        logger.info("="*60 + "\n")
        
        # 采集数据（使用全局配置）
        data = collect_data()

        if not data:
            logger.error("❌ 所有数据采集失败")
            sys.exit(1)

        # 保存数据
        save_data(data, save_path=SAVE_PATH)

        # 预览
        logger.info("\n" + "="*60)
        logger.info("数据预览 (最新5条):")
        logger.info("="*60)

        for symbol, df in data.items():
            logger.info(f"\n{symbol}:")
            print(df[['datetime', 'open', 'high', 'low', 'close', 'volume']].tail().to_string(index=False))

        logger.info("\n✅ 真实数据采集完成！")

    except KeyboardInterrupt:
        logger.warning("\n⚠️ 用户中断")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
