"""
数据采集测试脚本
采集BTC和ETH的合约数据
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from core.data_collector import DataCollector
from loguru import logger


def main():
    """主函数"""
    logger.info("="*60)
    logger.info("砖型图系统 - 数据采集")
    logger.info("="*60)

    # 1. 初始化数据采集器
    logger.info("\n初始化数据采集器...")
    collector = DataCollector(
        primary_exchange='binance',   # 主：币安合约
        backup_exchange='okx',         # 备：OKX合约
        testnet=False                  # 使用实盘数据
    )

    # 显示交易所状态
    info = collector.get_exchange_info()
    logger.info(f"主交易所: {info['primary_exchange']} ({info['primary_status']})")
    logger.info(f"备用交易所: {info['backup_exchange']} ({info['backup_status']})")

    # 2. 定义采集参数
    symbols = ['BTC/USDT', 'ETH/USDT']
    timeframe = '5m'
    days = 30

    logger.info(f"\n采集配置:")
    logger.info(f"  交易对: {', '.join(symbols)}")
    logger.info(f"  时间周期: {timeframe}")
    logger.info(f"  回溯天数: {days}")

    # 3. 采集数据
    logger.info(f"\n开始采集数据...")
    logger.info("="*60)

    data = collector.collect_historical_data(
        symbols=symbols,
        timeframe=timeframe,
        days=days,
        save_path='data/raw'
    )

    # 4. 数据统计
    logger.info("\n" + "="*60)
    logger.info("采集完成！数据统计:")
    logger.info("="*60)

    for symbol, df in data.items():
        logger.info(f"\n📊 {symbol}")
        logger.info(f"  ├─ 数据量: {len(df):,} 条")
        logger.info(f"  ├─ 时间跨度: {(df['datetime'].max() - df['datetime'].min()).days} 天")
        logger.info(f"  ├─ 开始时间: {df['datetime'].min()}")
        logger.info(f"  ├─ 结束时间: {df['datetime'].max()}")
        logger.info(f"  ├─ 价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")
        logger.info(f"  ├─ 最新价格: ${df['close'].iloc[-1]:,.2f}")
        logger.info(f"  └─ 数据来源: {df['exchange'].iloc[0].upper()}")

    # 5. 显示最新数据
    logger.info("\n" + "="*60)
    logger.info("最新数据预览:")
    logger.info("="*60)

    for symbol, df in data.items():
        logger.info(f"\n{symbol} - 最新5条:")
        print(df[['datetime', 'open', 'high', 'low', 'close', 'volume']].tail().to_string(index=False))

    # 6. 保存路径提示
    logger.info("\n" + "="*60)
    logger.info("数据文件保存位置:")
    logger.info("="*60)
    save_path = Path('data/raw')
    for file in sorted(save_path.glob('*.csv')):
        size_mb = file.stat().st_size / 1024 / 1024
        logger.info(f"  📁 {file.name} ({size_mb:.2f} MB)")

    logger.info("\n✅ 数据采集完成！可以开始构建砖型图了。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️ 用户中断")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
