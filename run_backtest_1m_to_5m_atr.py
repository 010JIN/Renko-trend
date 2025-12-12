"""
运行砖型图反转策略回测（1分钟K线聚合为5分钟K线，ATR砖块）
"""

import pandas as pd
import sys
from pathlib import Path
from loguru import logger
import yaml

sys.path.append(str(Path(__file__).parent))

from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy


def load_and_aggregate_data(symbol: str = 'BTCUSDT', start_date: str = '20241212', end_date: str = '20251212') -> pd.DataFrame:
    """
    加载1分钟K线数据（不聚合，直接返回1分钟K线）
    """
    data_dir = Path('data/raw')
    # 自动查找最新的1m csv文件
    candidates = list(data_dir.glob(f"{symbol}_1m_*.csv"))
    if not candidates:
        logger.error(f"未找到 {symbol} 1m 数据集 (csv)！请先运行: python fetch_real_data.py")
        sys.exit(1)
    csv_file = sorted(candidates)[-1]
    df = pd.read_csv(csv_file)
    logger.info(f"加载数据: {len(df):,} 条1分钟K线")
    logger.info(f"时间范围: {df['timestamp'].min()} 至 {df['timestamp'].max()}")
    logger.info(f"价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")
    # 确保timestamp为datetime
    if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    # 不做聚合，直接返回1分钟K线
    return df


def build_renko(df: pd.DataFrame, renko_cfg: dict) -> pd.DataFrame:
    """
    构建砖型图，所有参数从 config.yaml 读取
    """
    # 1分钟K线+5分钟ATR动态砖块
    # 动态读取所有参数
    method = renko_cfg.get('method', 'fixed')
    brick_size = renko_cfg.get('brick_size', 350.0)
    atr_period = renko_cfg.get('atr_period', 14)
    atr_multiplier = renko_cfg.get('atr_multiplier', 2.0)
    percentage = renko_cfg.get('percentage', 0.0035)
    log_base = renko_cfg.get('log_base', 10.0)
    use_wicks = renko_cfg.get('use_wicks', False)

    renko_bricks = []
    last_brick_close = None
    buffer = []
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    for i in range(len(df)):
        buffer.append(df.iloc[i])
        if last_brick_close is None:
            last_brick_close = buffer[0]['open']
        while True:
            buffer_df = pd.DataFrame(buffer).copy().reset_index(drop=True)
            if len(buffer_df) == 0:
                break
            buffer_df.at[0, 'open'] = last_brick_close
            builder = RenkoBuilder(
                method=method,
                brick_size=brick_size,
                atr_period=atr_period,
                atr_multiplier=atr_multiplier,
                percentage=percentage,
                log_base=log_base,
                use_wicks=use_wicks
            )
            renko_df = builder.build(buffer_df)
            if renko_df.empty or len(renko_df) == 0:
                break
            brick = renko_df.iloc[0]
            renko_bricks.append(brick.to_dict())
            last_brick_close = brick['brick_close']
            used_idx = None
            for j in range(len(buffer_df)):
                if (brick['direction'] == 1 and buffer_df.loc[j, 'close'] >= brick['brick_close']) or \
                   (brick['direction'] == -1 and buffer_df.loc[j, 'close'] <= brick['brick_close']):
                    used_idx = j
                    break
            if used_idx is not None:
                buffer = buffer[used_idx+1:]
            else:
                buffer = []
    renko_df_final = pd.DataFrame(renko_bricks)
    logger.info(f"砖型图构建完成:")
    logger.info(f"  原始K线: {len(df):,} 条")
    logger.info(f"  砖块数量: {len(renko_df_final):,} 个")
    if not renko_df_final.empty:
        logger.info(f"  平均砖块大小: ${renko_df_final['brick_size'].mean():.2f}")
    return renko_df_final


def run_strategy_backtest(
    renko_df: pd.DataFrame,
    initial_capital: float = 10000.0
) -> dict:
    """
    运行策略回测
    """
    strategy = RenkoReversalStrategy(
        initial_capital=initial_capital,
        commission_rate=0.0004,
        slippage_rate=0.0001
    )
    stats = strategy.run_backtest(renko_df)
    strategy.print_statistics(stats)
    strategy.print_all_trades()
    return stats


def main():
    try:
        logger.info("="*70)
        logger.info("🚀 砖型图反转策略回测系统 (1分钟K线聚合5分钟+ATR砖块)")
        logger.info("="*70)
        # 加载配置文件
        with open('config/config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        renko_cfg = config.get('renko', {})
        data_cfg = config.get('data', {})
        symbol = data_cfg.get('symbol', 'BTCUSDT')
        # 加载并聚合数据
        df_5m = load_and_aggregate_data(symbol=symbol, start_date='20241212', end_date='20251212')
        # 构建砖型图
        renko_df = build_renko(df_5m, renko_cfg)
        # 运行回测
        stats = run_strategy_backtest(renko_df, initial_capital=10000.0)
        logger.info("\n✅ 回测完成！")
        # 打印交易总结
        print("\n回测统计总结：")
        print(f"最终余额: ${stats['final_balance']:,.2f}")
        print(f"总收益率: {stats['total_return_pct']*100:.2f}%")
        print(f"总交易次数: {stats['total_trades']}")
        print(f"胜率: {stats.get('win_rate', 0)*100:.2f}%")
        print(f"最大回撤: {stats.get('max_drawdown', 0)*100:.2f}%")
        print(f"盈利因子: {stats.get('profit_factor', 0):.2f}")
        if 'total_commission' in stats:
            print(f"总手续费: ${stats['total_commission']:,.2f}")
        else:
            print("总手续费: 未统计")
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
