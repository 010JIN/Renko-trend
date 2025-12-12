"""
自动批量采集BTC/ETH 1m/5m/15m K线数据，覆盖2024和2025两个年度区间。
每个数据集自动保存为 parquet/csv 文件，便于批量回测。
"""
from fetch_real_data import collect_data, save_data
from loguru import logger

SYMBOLS = ['BTCUSDT', 'ETHUSDT']
INTERVALS = ['1m', '5m', '15m']
PERIODS = [
    ('2024-01-01', '2024-12-31'),
    ('2025-01-01', '2025-12-01')
]

SAVE_PATH = 'data/raw'

def main():
    for interval in INTERVALS:
        for start_date, end_date in PERIODS:
            logger.info(f"\n==== 采集 {SYMBOLS} {interval} {start_date}~{end_date} ====")
            data = collect_data(
                symbols=SYMBOLS,
                interval=interval,
                start_date=start_date,
                end_date=end_date
            )
            if data:
                save_data(data, save_path=SAVE_PATH)
            else:
                logger.warning(f"未采集到 {interval} {start_date}~{end_date} 数据")

if __name__ == "__main__":
    main()
