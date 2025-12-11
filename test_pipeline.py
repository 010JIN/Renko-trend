"""
端到端测试：数据采集 → 砖型图构建 → 趋势分析
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from core.data_collector import DataCollector
from core.renko_builder import RenkoBuilder
from core.trend_filter import TrendFilter
from loguru import logger
import pandas as pd


def test_full_pipeline():
    """测试完整流程"""

    logger.info("="*60)
    logger.info("🚀 砖型图趋势过滤系统 - 完整测试")
    logger.info("="*60)

    # ==================== 第一步：数据采集 ====================
    logger.info("\n📡 第一步：采集交易所数据")
    logger.info("-"*60)

    collector = DataCollector(
        primary_exchange='binance',
        backup_exchange='okx'
    )

    symbols = ['BTC/USDT', 'ETH/USDT']
    data = collector.collect_historical_data(
        symbols=symbols,
        timeframe='5m',
        days=7,  # 先测试7天数据
        save_path='data/raw'
    )

    if not data:
        logger.error("❌ 数据采集失败")
        return

    logger.info(f"✅ 成功采集 {len(data)} 个交易对的数据")

    # ==================== 第二步：构建砖型图 ====================
    logger.info("\n🧱 第二步：构建砖型图")
    logger.info("-"*60)

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

        # 保存砖型图数据
        output_dir = Path('data/processed')
        output_dir.mkdir(parents=True, exist_ok=True)

        symbol_clean = symbol.replace('/', '_')
        renko_file = output_dir / f"{symbol_clean}_renko.csv"
        renko_df.to_csv(renko_file, index=False)

        # 统计信息
        logger.info(f"  原始K线: {len(df)} 条")
        logger.info(f"  砖块数量: {len(renko_df)} 个")
        compression_ratio = len(df) / len(renko_df)
        logger.info(f"  压缩比: {compression_ratio:.2f}x")
        logger.info(f"  砖块大小: {renko_df['brick_size'].iloc[0]:.2f}")

        # 反转统计
        reversals = builder.get_brick_reversals(renko_df)
        logger.info(f"  反转次数: {len(reversals)}")

        # 方向统计
        up_bricks = (renko_df['direction'] == 1).sum()
        down_bricks = (renko_df['direction'] == -1).sum()
        logger.info(f"  上涨砖块: {up_bricks} ({up_bricks/len(renko_df)*100:.1f}%)")
        logger.info(f"  下跌砖块: {down_bricks} ({down_bricks/len(renko_df)*100:.1f}%)")

    logger.info(f"\n✅ 砖型图构建完成")

    # ==================== 第三步：趋势分析 ====================
    logger.info("\n📈 第三步：趋势分析")
    logger.info("-"*60)

    trend_filter = TrendFilter(
        min_bricks=3,
        strength_threshold=0.6,
        confidence_threshold=0.7
    )

    for symbol, renko_df in renko_data.items():
        logger.info(f"\n分析 {symbol}...")

        # 趋势分析
        signal = trend_filter.analyze(renko_df)

        # 支撑阻力
        support, resistance = trend_filter.identify_support_resistance(renko_df)

        # 突破检测
        breakout = trend_filter.check_breakout(renko_df, support, resistance)

        # 显示结果
        direction_emoji = {1: '🟢', -1: '🔴', 0: '⚪'}
        direction_text = {1: '上涨', -1: '下跌', 0: '震荡'}

        logger.info(f"\n  {direction_emoji[signal.direction]} 趋势方向: {direction_text[signal.direction]}")
        logger.info(f"  💪 趋势强度: {signal.strength:.2%}")
        logger.info(f"  ✓ 可信度: {signal.confidence:.2%}")
        logger.info(f"  📊 连续砖块: {signal.brick_count} 个")
        logger.info(f"  ⏱️ 距反转: {signal.reversal_distance} 个砖块")

        if support:
            logger.info(f"\n  🛡️ 支撑位 (前3个):")
            for i, level in enumerate(support[:3], 1):
                logger.info(f"     {i}. ${level:,.2f}")

        if resistance:
            logger.info(f"\n  🚧 阻力位 (前3个):")
            for i, level in enumerate(resistance[:3], 1):
                logger.info(f"     {i}. ${level:,.2f}")

        if breakout['breakout']:
            logger.info(f"\n  ⚡ 突破警报!")
            logger.info(f"     类型: {breakout['type']}")
            logger.info(f"     位置: ${breakout['level']:,.2f}")
            logger.info(f"     方向: {breakout['direction']}")

        # 保存分析报告
        report_file = output_dir / f"{symbol.replace('/', '_')}_analysis.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"砖型图趋势分析报告\n")
            f.write(f"{'='*60}\n")
            f.write(f"交易对: {symbol}\n")
            f.write(f"数据来源: {data[symbol]['exchange'].iloc[0].upper()}\n")
            f.write(f"分析时间: {pd.Timestamp.now()}\n\n")

            f.write(f"趋势信号:\n")
            f.write(f"  方向: {direction_text[signal.direction]}\n")
            f.write(f"  强度: {signal.strength:.2%}\n")
            f.write(f"  可信度: {signal.confidence:.2%}\n")
            f.write(f"  连续砖块数: {signal.brick_count}\n\n")

            if support:
                f.write(f"支撑位: {', '.join([f'${s:,.2f}' for s in support[:5]])}\n")
            if resistance:
                f.write(f"阻力位: {', '.join([f'${r:,.2f}' for r in resistance[:5]])}\n")

    # ==================== 总结 ====================
    logger.info("\n" + "="*60)
    logger.info("✅ 完整测试通过！")
    logger.info("="*60)

    logger.info("\n📁 生成的文件:")
    logger.info("  原始数据: data/raw/")
    logger.info("  砖型图数据: data/processed/*_renko.csv")
    logger.info("  分析报告: data/processed/*_analysis.txt")

    logger.info("\n🎯 下一步:")
    logger.info("  1. 查看生成的分析报告")
    logger.info("  2. 调整 config/config.yaml 中的参数")
    logger.info("  3. 运行回测验证策略")


if __name__ == "__main__":
    try:
        test_full_pipeline()
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️ 测试中断")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
