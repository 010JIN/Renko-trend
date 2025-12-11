"""
使用真实数据构建砖型图
演示三种砖块大小计算方法
"""

import pandas as pd
import sys
from pathlib import Path
from loguru import logger

# 添加项目路径
sys.path.append(str(Path(__file__).parent))

from core.renko_builder import RenkoBuilder
from core.trend_filter import TrendFilter

# ==================== 砖型图配置参数 ====================
# 
# 三种砖块大小计算方法：
#
# 1. 固定法 (fixed)：固定点数作为砖块大小
#    - 适合：价格波动相对稳定的市场
#    - 参数：brick_size (例如：100 表示每个砖块100美元)
#
# 2. ATR法 (atr)：根据平均真实波幅动态调整【推荐】
#    - 适合：大多数情况，自动适应市场波动
#    - 参数：atr_period (周期，默认14), atr_multiplier (倍数，默认2.0)
#
# 3. 百分比法 (percentage)：价格百分比作为砖块大小
#    - 适合：不同价格级别的资产对比
#    - 参数：percentage (例如：0.001 表示0.1%)
#
# =========================================================

import yaml

# 统一从 config.yaml 读取砖型图参数
def get_renko_config(config_path='config/config.yaml'):
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config.get('renko', {})


def load_real_data(symbol: str = 'BTC_USDT', date: str = '20251211') -> pd.DataFrame:
    """
    加载真实数据
    
    Args:
        symbol: 交易对符号
        date: 日期字符串
    """
    data_dir = Path('data/raw')
    
    # 优先使用parquet格式（更快）
    parquet_file = data_dir / f"{symbol}_5m_{date}.parquet"
    csv_file = data_dir / f"{symbol}_5m_{date}.csv"
    
    if parquet_file.exists():
        logger.info(f"加载数据: {parquet_file.name}")
        df = pd.read_parquet(parquet_file)
    elif csv_file.exists():
        logger.info(f"加载数据: {csv_file.name}")
        df = pd.read_csv(csv_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    else:
        raise FileNotFoundError(f"未找到数据文件: {parquet_file} 或 {csv_file}")
    
    logger.info(f"数据加载完成: {len(df):,} 条记录")
    logger.info(f"时间范围: {df['timestamp'].min()} 到 {df['timestamp'].max()}")
    logger.info(f"价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")
    
    return df


def build_renko_chart(df: pd.DataFrame, config_path: str = 'config/config.yaml') -> pd.DataFrame:
    """
    构建砖型图，参数从配置文件读取
    Args:
        df: OHLC数据
        config_path: 配置文件路径
    """
    renko_cfg = get_renko_config(config_path)
    logger.info("\n" + "="*60)
    logger.info("开始构建砖型图")
    logger.info(f"配置: {renko_cfg}")
    logger.info("="*60)
    builder = RenkoBuilder(
        method=renko_cfg.get('method', 'atr'),
        atr_period=renko_cfg.get('atr_period', 14),
        atr_multiplier=renko_cfg.get('atr_multiplier', 2.0),
        brick_size=renko_cfg.get('brick_size'),
        percentage=renko_cfg.get('percentage', 0.005),
        log_base=renko_cfg.get('log_base', 10.0),
        use_wicks=renko_cfg.get('use_wicks', False)
    )
    renko_df = builder.build(df)
    logger.info("\n砖型图统计:")
    logger.info(f"  原始K线数: {len(df):,}")
    logger.info(f"  砖块数量: {len(renko_df):,}")
    logger.info(f"  压缩比: {len(df)/len(renko_df):.2f}:1")
    logger.info(f"  上涨砖块: {(renko_df['direction'] == 1).sum()}")
    logger.info(f"  下跌砖块: {(renko_df['direction'] == -1).sum()}")
    reversals = builder.get_brick_reversals(renko_df)
    logger.info(f"  趋势反转次数: {len(reversals)}")
    return renko_df


def analyze_trend(renko_df: pd.DataFrame):
    """趋势分析"""
    logger.info("\n" + "="*60)
    logger.info("趋势分析")
    logger.info("="*60)
    
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
    
    return signal


def save_renko_data(renko_df: pd.DataFrame, symbol: str = 'BTC_USDT'):
    """保存砖型图数据"""
    save_dir = Path('data/processed')
    save_dir.mkdir(parents=True, exist_ok=True)
    
    from datetime import datetime
    date_str = datetime.now().strftime('%Y%m%d')
    
    # 保存CSV
    csv_file = save_dir / f"{symbol}_renko_{date_str}.csv"
    renko_df.to_csv(csv_file, index=False)
    logger.info(f"\n保存砖型图数据: {csv_file}")
    
    # 保存Parquet
    parquet_file = csv_file.with_suffix('.parquet')
    renko_df.to_parquet(parquet_file, index=False)
    logger.info(f"保存砖型图数据: {parquet_file}")


def compare_methods(df: pd.DataFrame):
    """对比三种方法"""
    logger.info("\n" + "="*60)
    logger.info("对比三种砖块大小计算方法")
    logger.info("="*60)
    
    configs = {
        'Fixed (固定100美元)': {'method': 'fixed', 'brick_size': 100},
        'ATR (动态调整)': {'method': 'atr', 'atr_period': 14, 'atr_multiplier': 2.0},
        'Percentage (0.1%)': {'method': 'percentage', 'percentage': 0.001},
    }
    
    results = {}
    
    for name, config in configs.items():
        logger.info(f"\n{name}:")
        builder = RenkoBuilder(**config)
        renko_df = builder.build(df)
        
        results[name] = renko_df
        
        logger.info(f"  砖块数量: {len(renko_df):,}")
        logger.info(f"  平均砖块大小: {renko_df['brick_size'].mean():.2f}")
        logger.info(f"  压缩比: {len(df)/len(renko_df):.2f}:1")
        
        reversals = builder.get_brick_reversals(renko_df)
        logger.info(f"  反转次数: {len(reversals)}")
    
    return results


def main():
    """主函数"""
    try:
        logger.info("🚀 使用真实数据构建砖型图")
        logger.info("="*60)
        
        # 1. 加载真实数据
        df_btc = load_real_data(symbol='BTC_USDT', date='20251211')
        
        # 2. 构建砖型图（使用配置的方法）
        renko_cfg = get_renko_config()
        logger.info(f"\n当前使用配置: {renko_cfg}")
        renko_df = build_renko_chart(df_btc)
        
        # 3. 趋势分析
        signal = analyze_trend(renko_df)
        
        # 4. 保存砖型图数据
        save_renko_data(renko_df, symbol='BTC_USDT')
        
        # 5. 显示砖型图样本
        logger.info("\n" + "="*60)
        logger.info("砖型图数据预览 (最新10个砖块):")
        logger.info("="*60)
        print(renko_df[['brick_num', 'direction', 'brick_open', 'brick_close', 
                        'brick_size', 'timestamp']].tail(10).to_string(index=False))
        
        # 6. 可选：对比三种方法
        logger.info("\n是否要对比三种方法？这将花费一些时间...")
        # results = compare_methods(df_btc)
        
        logger.info("\n✅ 砖型图构建完成！")
        
        logger.info("\n" + "="*60)
        logger.info("💡 提示：修改砖块大小的位置")
        logger.info("="*60)
        logger.info("请在 config/config.yaml 文件中修改 renko 配置：")
        logger.info("")
        logger.info("方法1 - 固定大小法:")
        logger.info("  renko:")
        logger.info("      'method': 'fixed',")
        logger.info("      'brick_size': 350,  # 修改这里：每个砖块的固定大小")
        logger.info("  }")
        logger.info("")
        logger.info("方法2 - ATR动态法（推荐）:")
        logger.info("  renko:")
        logger.info("      'method': 'atr',")
        logger.info("      'atr_period': 14,      # ATR计算周期")
        logger.info("      'atr_multiplier': 2.0, # 修改这里：ATR倍数(1.0-3.0)")
        logger.info("  }")
        logger.info("")
        logger.info("方法3 - 百分比法:")
        logger.info("  renko:")
        logger.info("      'method': 'percentage',")
        logger.info("      'percentage': 0.001,  # 修改这里：0.001=0.1%")
        logger.info("  }")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
