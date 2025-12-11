"""
使用已采集的真实数据进行砖型图测试
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import pandas as pd
from core.renko_builder import RenkoBuilder
from core.trend_filter import TrendFilter
from loguru import logger


def load_data(data_path='data/raw'):
    """加载已采集的数据"""
    logger.info("="*60)
    logger.info("加载真实市场数据")
    logger.info("="*60)

    data_dir = Path(data_path)
    data = {}

    # 查找最新的数据文件
    for symbol in ['BTC_USDT', 'ETH_USDT']:
        parquet_files = list(data_dir.glob(f"{symbol}_*m_*.parquet"))

        if parquet_files:
            # 使用最新的文件
            latest_file = sorted(parquet_files)[-1]
            df = pd.read_parquet(latest_file)

            symbol_name = df['symbol'].iloc[0]
            data[symbol_name] = df

            logger.info(f"\n✓ 加载 {symbol_name}")
            logger.info(f"  文件: {latest_file.name}")
            logger.info(f"  数据量: {len(df):,} 条")
            logger.info(f"  时间范围: {df['datetime'].min()} 到 {df['datetime'].max()}")
            logger.info(f"  价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")

    return data


def build_renko(data: dict):
    """构建砖型图"""
    logger.info("\n" + "="*60)
    logger.info("🧱 构建砖型图")
    logger.info("="*60)

    builder = RenkoBuilder(
        method='atr',
        atr_period=14,
        atr_multiplier=2.0
    )

    renko_data = {}

    for symbol, df in data.items():
        logger.info(f"\n处理 {symbol}...")

        # 构建砖型图
        renko_df = builder.build(df)
        renko_data[symbol] = renko_df

        # 保存
        output_dir = Path('data/processed')
        output_dir.mkdir(parents=True, exist_ok=True)

        symbol_clean = symbol.replace('/', '_')
        renko_file = output_dir / f"{symbol_clean}_renko.csv"
        renko_df.to_csv(renko_file, index=False)

        # 统计
        logger.info(f"  原始K线: {len(df):,} 条")
        logger.info(f"  砖块数量: {len(renko_df):,} 个")
        logger.info(f"  压缩比: {len(df)/len(renko_df):.2f}x")
        logger.info(f"  砖块大小: ${renko_df['brick_size'].iloc[0]:,.2f}")

        # 反转统计
        reversals = builder.get_brick_reversals(renko_df)
        logger.info(f"  反转次数: {len(reversals)}")

        # 方向统计
        up_bricks = (renko_df['direction'] == 1).sum()
        down_bricks = (renko_df['direction'] == -1).sum()
        logger.info(f"  上涨砖块: {up_bricks} ({up_bricks/len(renko_df)*100:.1f}%)")
        logger.info(f"  下跌砖块: {down_bricks} ({down_bricks/len(renko_df)*100:.1f}%)")
        logger.info(f"  已保存: {renko_file}")

    return renko_data


def analyze_trend(renko_data: dict):
    """趋势分析"""
    logger.info("\n" + "="*60)
    logger.info("📈 趋势分析")
    logger.info("="*60)

    trend_filter = TrendFilter(
        min_bricks=3,
        strength_threshold=0.6,
        confidence_threshold=0.7,
        use_volume_filter=True
    )

    output_dir = Path('data/processed')

    for symbol, renko_df in renko_data.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"分析 {symbol}")
        logger.info(f"{'='*60}")

        # 趋势分析
        signal = trend_filter.analyze(renko_df)

        # 支撑阻力
        support, resistance = trend_filter.identify_support_resistance(renko_df)

        # 突破检测
        breakout = trend_filter.check_breakout(renko_df, support, resistance)

        # 显示结果
        direction_emoji = {1: '🟢 上涨', -1: '🔴 下跌', 0: '⚪ 震荡'}

        logger.info(f"\n📊 当前趋势:")
        logger.info(f"  方向: {direction_emoji[signal.direction]}")
        logger.info(f"  强度: {signal.strength:.2%}")
        logger.info(f"  可信度: {signal.confidence:.2%}")
        logger.info(f"  连续砖块: {signal.brick_count} 个")
        logger.info(f"  距离反转: {signal.reversal_distance} 个砖块")

        if support:
            logger.info(f"\n🛡️  支撑位 (前3个):")
            for i, level in enumerate(support[:3], 1):
                logger.info(f"     {i}. ${level:,.2f}")

        if resistance:
            logger.info(f"\n🚧 阻力位 (前3个):")
            for i, level in enumerate(resistance[:3], 1):
                logger.info(f"     {i}. ${level:,.2f}")

        if breakout['breakout']:
            logger.info(f"\n⚡ 突破警报!")
            logger.info(f"   类型: {breakout['type']}")
            logger.info(f"   位置: ${breakout['level']:,.2f}")
            logger.info(f"   方向: {breakout['direction']}")

        # 保存报告
        report_file = output_dir / f"{symbol.replace('/', '_')}_analysis.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"砖型图趋势分析报告\n")
            f.write(f"{'='*60}\n")
            f.write(f"交易对: {symbol}\n")
            f.write(f"分析时间: {pd.Timestamp.now()}\n")
            f.write(f"数据来源: Binance (真实数据)\n\n")

            f.write(f"趋势信号:\n")
            f.write(f"  方向: {direction_emoji[signal.direction]}\n")
            f.write(f"  强度: {signal.strength:.2%}\n")
            f.write(f"  可信度: {signal.confidence:.2%}\n")
            f.write(f"  连续砖块数: {signal.brick_count}\n")
            f.write(f"  距离反转: {signal.reversal_distance} 个砖块\n\n")

            if support:
                f.write(f"支撑位: {', '.join([f'${s:,.2f}' for s in support[:5]])}\n")
            if resistance:
                f.write(f"阻力位: {', '.join([f'${r:,.2f}' for r in resistance[:5]])}\n")

            if breakout['breakout']:
                f.write(f"\n突破警报:\n")
                f.write(f"  类型: {breakout['type']}\n")
                f.write(f"  位置: ${breakout['level']:,.2f}\n")
                f.write(f"  方向: {breakout['direction']}\n")

        logger.info(f"\n📄 报告已保存: {report_file}")


def main():
    """主函数"""
    logger.info("🚀 砖型图趋势过滤系统 - 真实数据测试")

    try:
        # 1. 加载数据
        data = load_data()

        if not data:
            logger.error("❌ 未找到数据文件，请先运行: python fetch_real_data.py")
            return

        # 2. 构建砖型图
        renko_data = build_renko(data)

        # 3. 趋势分析
        analyze_trend(renko_data)

        # 总结
        logger.info("\n" + "="*60)
        logger.info("✅ 测试完成！")
        logger.info("="*60)

        logger.info("\n📁 生成的文件:")
        logger.info("  📊 砖型图数据: data/processed/*_renko.csv")
        logger.info("  📄 分析报告: data/processed/*_analysis.txt")

        logger.info("\n🎯 查看结果:")
        logger.info("  cat data/processed/BTC_USDT_analysis.txt")
        logger.info("  cat data/processed/ETH_USDT_analysis.txt")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n⚠️ 测试中断")
        sys.exit(0)
