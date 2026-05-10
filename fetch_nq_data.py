"""
纳斯达克期货历史数据获取器
使用 yfinance 下载 NQ=F 连续主力合约价格数据（供 MNQ 策略使用）

合约规格（MNQ — Micro NQ E-mini）：
  - 1 点 = $2
  - 最小跳动：0.25 点 = $0.50 / 张
  - 最大持仓：30 张 MNQ（= 30 × 1 点 = $60/点）
  - 注：NQ=F 与 MNQ=F 价格相同，差异仅在合约倍数（×20 vs ×2）

可用周期（yfinance 限制）：
  - 1m : 最近 7 天
  - 5m : 最近 60 天
  - 15m: 最近 60 天
  - 1h : 最近 730 天
  - 1d : 历史完整
"""

import yfinance as yf
import pandas as pd
from pathlib import Path
from loguru import logger
from datetime import datetime, timedelta


# ========== 配置 ==========
TICKER = 'NQ=F'          # 纳斯达克期货连续合约
SAVE_PATH = Path('data/raw')

# 要下载的周期和对应天数（受 yfinance 限制）
INTERVALS = {
    '1m':  7,    # 最多7天
    '5m':  60,   # 最多60天
    '15m': 60,   # 最多60天
    '1h':  365,  # 最多730天，取1年
    '1d':  365 * 3,  # 3年日线
}


def fetch_nq_data(interval: str = '5m', days: int = 60) -> pd.DataFrame:
    """
    获取 NQ 期货数据

    Args:
        interval: K线周期，如 '1m', '5m', '15m', '1h', '1d'
        days: 回溯天数

    Returns:
        标准化的 OHLCV DataFrame
    """
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    logger.info(f"下载 {TICKER} {interval} 数据: {start_dt.date()} → {end_dt.date()}")

    try:
        ticker_obj = yf.Ticker(TICKER)
        df = ticker_obj.history(
            start=start_dt.strftime('%Y-%m-%d'),
            end=end_dt.strftime('%Y-%m-%d'),
            interval=interval,
            auto_adjust=True,
            prepost=False,  # 仅 RTH（美股常规交易时段）
        )

        if df.empty:
            logger.warning(f"未获取到 {TICKER} {interval} 数据")
            return pd.DataFrame()

        # 统一列名
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]

        # 时间戳列名兼容
        if 'datetime' in df.columns:
            df.rename(columns={'datetime': 'timestamp'}, inplace=True)
        elif 'date' in df.columns:
            df.rename(columns={'date': 'timestamp'}, inplace=True)

        # 确保 timestamp 为 datetime 类型（去掉时区）
        df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)

        # 保留标准列
        keep_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df = df[[c for c in keep_cols if c in df.columns]].copy()

        # 去除无效行
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        df = df.reset_index(drop=True)

        logger.info(f"✓ 获取 {len(df):,} 条 {interval} K线")
        logger.info(f"  时间: {df['timestamp'].min()} → {df['timestamp'].max()}")
        logger.info(f"  价格: {df['close'].min():.2f} - {df['close'].max():.2f}")

        return df

    except Exception as e:
        logger.error(f"下载失败: {e}")
        return pd.DataFrame()


def save_nq_data(df: pd.DataFrame, interval: str) -> Path:
    """保存数据到 data/raw/"""
    SAVE_PATH.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime('%Y%m%d')
    filename = f"NQ_{interval}_{date_str}.csv"
    filepath = SAVE_PATH / filename

    df.to_csv(filepath, index=False)
    logger.info(f"已保存: {filepath} ({len(df):,} 行)")
    return filepath


def load_nq_data(interval: str = '5m') -> pd.DataFrame:
    """
    从 data/raw/ 加载最新的 NQ 数据文件

    Args:
        interval: K线周期

    Returns:
        DataFrame，若无文件则返回空 DataFrame
    """
    candidates = sorted(SAVE_PATH.glob(f"NQ_{interval}_*.csv"))
    if not candidates:
        logger.warning(f"未找到 NQ {interval} 数据文件，请先运行: python fetch_nq_data.py")
        return pd.DataFrame()

    latest = candidates[-1]
    logger.info(f"加载: {latest.name}")
    df = pd.read_csv(latest)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    logger.info(f"  行数: {len(df):,} | 时间: {df['timestamp'].min()} → {df['timestamp'].max()}")
    return df


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("📈 纳斯达克期货（NQ=F）数据下载器")
    logger.info("=" * 60)

    saved_files = {}

    for interval, days in INTERVALS.items():
        logger.info(f"\n--- 下载 {interval} ({days}天) ---")
        df = fetch_nq_data(interval=interval, days=days)
        if not df.empty:
            path = save_nq_data(df, interval=interval)
            saved_files[interval] = path

    logger.info("\n" + "=" * 60)
    logger.info("✅ 数据下载完成")
    for interval, path in saved_files.items():
        logger.info(f"  {interval}: {path}")
    logger.info("=" * 60)
    logger.info("\n下一步: 运行 nq_backtest.py 进行回测")
