"""
测试对数百分比方法（log_percentage）
演示如何使用新的砖块大小计算方法
"""

import pandas as pd
import sys
from pathlib import Path
from loguru import logger

sys.path.append(str(Path(__file__).parent))

from core.renko_builder import RenkoBuilder


def load_data():
    """加载真实数据"""
    data_file = Path('data/raw/BTC_USDT_5m_20251211.parquet')
    
    if not data_file.exists():
        logger.error(f"数据文件不存在: {data_file}")
        logger.info("请先运行: python fetch_real_data.py")
        sys.exit(1)
    
    df = pd.read_parquet(data_file)
    logger.info(f"加载数据: {len(df):,} 条记录")
    logger.info(f"价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")
    
    return df


def compare_all_methods(df: pd.DataFrame):
    """对比所有四种方法"""
    logger.info("\n" + "="*70)
    logger.info("对比四种砖块大小计算方法")
    logger.info("="*70)
    
    configs = [
        {
            'name': 'Fixed (固定100美元)',
            'config': {'method': 'fixed', 'brick_size': 100}
        },
        {
            'name': 'ATR (动态调整)',
            'config': {'method': 'atr', 'atr_period': 14, 'atr_multiplier': 2.0}
        },
        {
            'name': 'Percentage (0.1%)',
            'config': {'method': 'percentage', 'percentage': 0.001}
        },
        {
            'name': 'Log Percentage (对数0.1%)',
            'config': {'method': 'log_percentage', 'percentage': 0.001, 'log_base': 10.0}
        },
    ]
    
    results = {}
    
    for item in configs:
        name = item['name']
        config = item['config']
        
        logger.info(f"\n【{name}】")
        logger.info(f"配置: {config}")
        
        builder = RenkoBuilder(**config)
        renko_df = builder.build(df)
        
        results[name] = renko_df
        
        # 统计信息
        logger.info(f"  ├─ 砖块数量: {len(renko_df):,}")
        logger.info(f"  ├─ 平均砖块大小: {renko_df['brick_size'].mean():.4f}")
        logger.info(f"  ├─ 砖块大小范围: {renko_df['brick_size'].min():.4f} - {renko_df['brick_size'].max():.4f}")
        logger.info(f"  ├─ 压缩比: {len(df)/len(renko_df):.2f}:1")
        logger.info(f"  ├─ 上涨砖块: {(renko_df['direction'] == 1).sum()}")
        logger.info(f"  ├─ 下跌砖块: {(renko_df['direction'] == -1).sum()}")
        
        reversals = builder.get_brick_reversals(renko_df)
        logger.info(f"  └─ 反转次数: {len(reversals)}")
    
    return results


def explain_log_percentage():
    """解释对数百分比方法"""
    logger.info("\n" + "="*70)
    logger.info("💡 对数百分比方法 (log_percentage) 说明")
    logger.info("="*70)
    
    logger.info("""
📊 计算公式：
   brick_size = percentage × log(price) / log(base)

🎯 适用场景：
   1. 长期走势分析（跨度数月或数年）
   2. 价格区间跨度大（如从几千到十几万）
   3. 需要在不同价格级别保持相对一致的敏感度

📈 优势：
   - 低价位时砖块较小，捕捉细节波动
   - 高价位时砖块较大，过滤噪音
   - 对数尺度更符合价格的相对变化特性
   
⚙️ 参数调整：
   - percentage: 控制整体砖块大小（0.0001 - 0.01）
   - log_base: 对数底数，通常使用 10 或 e(自然对数)
     * log_base = 10: 标准对数
     * log_base = 2.718: 自然对数（np.e）
     * 底数越小，对价格变化越敏感

🔄 与普通百分比法对比：
   - percentage: 砖块大小 ∝ 价格（线性关系）
   - log_percentage: 砖块大小 ∝ log(价格)（对数关系）

示例：BTC价格从 $10,000 到 $100,000
   - percentage(0.1%): 
     * $10,000 → 砖块 $10
     * $100,000 → 砖块 $100
   - log_percentage(0.1%): 
     * $10,000 → 砖块 ~0.4
     * $100,000 → 砖块 ~0.5
     * 在不同价格级别保持相对一致的敏感度
    """)
    
    logger.info("="*70)


def main():
    """主函数"""
    try:
        logger.info("🚀 测试对数百分比砖型图方法")
        
        # 1. 加载数据
        df = load_data()
        
        # 2. 解释方法
        explain_log_percentage()
        
        # 3. 对比所有方法
        results = compare_all_methods(df)
        
        # 4. 使用建议
        logger.info("\n" + "="*70)
        logger.info("📝 使用建议")
        logger.info("="*70)
        logger.info("""
1. 短期交易（几天到几周）：
   → 推荐 ATR 方法（自动适应当前波动）

2. 中期趋势（几周到几月）：
   → 推荐 Percentage 方法（固定百分比）

3. 长期分析（几月到几年）：
   → 推荐 Log Percentage 方法（对数百分比）

4. 固定目标（特定点位突破）：
   → 推荐 Fixed 方法（固定金额）
        """)
        
        logger.info("\n✅ 测试完成！")
        logger.info("\n💡 在 core/renko_builder.py 中可以修改 log_percentage 的实现")
        logger.info("   在 config/config.yaml 中可以配置参数")
        
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
