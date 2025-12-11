"""
快速开始示例
演示如何使用砖型图趋势过滤系统
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).parent))

from core.renko_builder import RenkoBuilder
from core.trend_filter import TrendFilter
from loguru import logger


def generate_sample_data(days: int = 30) -> pd.DataFrame:
    """
    生成示例数据（模拟价格数据）

    Args:
        days: 天数

    Returns:
        OHLC数据
    """
    logger.info(f"生成 {days} 天的示例数据...")

    # 生成时间序列
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    timestamps = pd.date_range(start=start_time, end=end_time, freq='5T')

    # 生成价格数据（带趋势的随机游走）
    np.random.seed(42)
    n = len(timestamps)

    # 基础价格
    base_price = 50000

    # 生成趋势
    trend = np.linspace(0, 5000, n)  # 上涨趋势

    # 添加噪音
    noise = np.random.normal(0, 200, n).cumsum()

    # 收盘价
    close = base_price + trend + noise

    # 生成OHLC
    high = close + np.abs(np.random.normal(0, 50, n))
    low = close - np.abs(np.random.normal(0, 50, n))
    open_price = close + np.random.normal(0, 30, n)

    # 成交量
    volume = np.random.uniform(100, 1000, n)

    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    })

    logger.info(f"生成了 {len(df)} 条数据记录")
    return df


def example_basic_usage():
    """示例1: 基础使用"""
    logger.info("\n" + "="*60)
    logger.info("示例 1: 基础使用")
    logger.info("="*60)

    # 1. 生成示例数据
    df = generate_sample_data(days=7)

    # 2. 创建砖型图构建器（ATR方法）
    builder = RenkoBuilder(
        method='atr',
        atr_period=14,
        atr_multiplier=2.0
    )

    # 3. 构建砖型图
    renko_df = builder.build(df)

    logger.info(f"\n原始K线数量: {len(df)}")
    logger.info(f"砖块数量: {len(renko_df)}")
    logger.info(f"\n前5个砖块:")
    print(renko_df.head())

    # 4. 获取反转点
    reversals = builder.get_brick_reversals(renko_df)
    logger.info(f"\n反转次数: {len(reversals)}")

    return renko_df


def example_trend_analysis(renko_df: pd.DataFrame):
    """示例2: 趋势分析"""
    logger.info("\n" + "="*60)
    logger.info("示例 2: 趋势分析")
    logger.info("="*60)

    # 创建趋势过滤器
    trend_filter = TrendFilter(
        min_bricks=3,
        strength_threshold=0.6,
        confidence_threshold=0.7
    )

    # 分析当前趋势
    signal = trend_filter.analyze(renko_df)

    direction_text = {1: '上涨 🟢', -1: '下跌 🔴', 0: '震荡 ⚪'}
    logger.info(f"\n当前趋势:")
    logger.info(f"  方向: {direction_text[signal.direction]}")
    logger.info(f"  强度: {signal.strength:.2%}")
    logger.info(f"  可信度: {signal.confidence:.2%}")
    logger.info(f"  连续砖块数: {signal.brick_count}")
    logger.info(f"  距离反转: {signal.reversal_distance} 个砖块")

    return signal


def example_support_resistance(renko_df: pd.DataFrame):
    """示例3: 支撑阻力位识别"""
    logger.info("\n" + "="*60)
    logger.info("示例 3: 支撑阻力位识别")
    logger.info("="*60)

    trend_filter = TrendFilter()

    # 识别支撑和阻力位
    support, resistance = trend_filter.identify_support_resistance(
        renko_df,
        lookback=50
    )

    logger.info(f"\n识别的支撑位 (前5个):")
    for i, level in enumerate(support[:5], 1):
        logger.info(f"  {i}. {level:.2f}")

    logger.info(f"\n识别的阻力位 (前5个):")
    for i, level in enumerate(resistance[:5], 1):
        logger.info(f"  {i}. {level:.2f}")

    # 检查突破
    breakout = trend_filter.check_breakout(renko_df, support, resistance)

    if breakout['breakout']:
        logger.info(f"\n⚡ 检测到突破!")
        logger.info(f"  类型: {breakout['type']}")
        logger.info(f"  位置: {breakout['level']:.2f}")
        logger.info(f"  方向: {breakout['direction']}")
    else:
        logger.info(f"\n未检测到突破")

    return support, resistance


def example_different_methods():
    """示例4: 不同砖块大小计算方法对比"""
    logger.info("\n" + "="*60)
    logger.info("示例 4: 不同砖块大小方法对比")
    logger.info("="*60)

    # 生成数据
    df = generate_sample_data(days=7)

    methods = [
        ('fixed', {'brick_size': 100}),
        ('atr', {'atr_period': 14, 'atr_multiplier': 2.0}),
        ('percentage', {'percentage': 0.002})
    ]

    results = {}

    for method, params in methods:
        builder = RenkoBuilder(method=method, **params)
        renko_df = builder.build(df)
        results[method] = renko_df

        logger.info(f"\n{method.upper()} 方法:")
        logger.info(f"  砖块数量: {len(renko_df)}")
        logger.info(f"  平均砖块大小: {renko_df['brick_size'].mean():.2f}")

        # 反转次数
        reversals = builder.get_brick_reversals(renko_df)
        logger.info(f"  反转次数: {len(reversals)}")

    return results


def example_trend_strength():
    """示例5: 趋势强度计算"""
    logger.info("\n" + "="*60)
    logger.info("示例 5: 趋势强度分析")
    logger.info("="*60)

    # 生成数据
    df = generate_sample_data(days=14)

    # 构建砖型图
    builder = RenkoBuilder(method='atr')
    renko_df = builder.build(df)

    # 计算趋势强度
    renko_df['trend_strength'] = builder.calculate_trend_strength(renko_df, window=10)

    logger.info(f"\n最近10个砖块的趋势强度:")
    recent = renko_df[['brick_num', 'direction', 'brick_close', 'trend_strength']].tail(10)
    print(recent.to_string())

    # 找出最强趋势点
    max_strength_idx = renko_df['trend_strength'].idxmax()
    max_strength_brick = renko_df.loc[max_strength_idx]

    logger.info(f"\n最强趋势点:")
    logger.info(f"  砖块编号: {max_strength_brick['brick_num']}")
    logger.info(f"  趋势强度: {max_strength_brick['trend_strength']:.2%}")
    logger.info(f"  价格: {max_strength_brick['brick_close']:.2f}")


def main():
    """主函数 - 运行所有示例"""
    logger.info("🚀 砖型图趋势过滤系统 - 快速开始示例")
    logger.info("="*60)

    try:
        # 示例1: 基础使用
        renko_df = example_basic_usage()

        # 示例2: 趋势分析
        signal = example_trend_analysis(renko_df)

        # 示例3: 支撑阻力位
        support, resistance = example_support_resistance(renko_df)

        # 示例4: 不同方法对比
        results = example_different_methods()

        # 示例5: 趋势强度
        example_trend_strength()

        logger.info("\n" + "="*60)
        logger.info("✅ 所有示例运行完成!")
        logger.info("="*60)

    except Exception as e:
        logger.error(f"运行出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
