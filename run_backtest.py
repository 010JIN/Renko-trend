"""
运行砖型图反转策略回测
使用真实历史数据进行策略测试
"""

import pandas as pd
import sys
from pathlib import Path
from loguru import logger
import yaml

sys.path.append(str(Path(__file__).parent))

from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy


def load_data(symbol: str = 'BTC_USDT', date: str = '20251211') -> pd.DataFrame:
    """加载历史数据"""
    data_dir = Path('data/raw')
    parquet_file = data_dir / f"{symbol}_5m_{date}.parquet"
    
    if not parquet_file.exists():
        logger.error(f"数据文件不存在: {parquet_file}")
        logger.info("请先运行: python fetch_real_data.py")
        sys.exit(1)
    
    df = pd.read_parquet(parquet_file)
    logger.info(f"加载数据: {len(df):,} 条K线")
    logger.info(f"时间范围: {df['timestamp'].min()} 至 {df['timestamp'].max()}")
    logger.info(f"价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")
    
    return df


def build_renko(df: pd.DataFrame, renko_cfg: dict) -> pd.DataFrame:
    """构建砖型图，所有参数从 config.yaml 读取"""
    method = renko_cfg.get('method', 'fixed')
    logger.info(f"\n构建砖型图 (方法: {method})... 配置: {renko_cfg}")
    builder = RenkoBuilder(
        method=method,
        brick_size=renko_cfg.get('brick_size', 350.0),
        atr_period=renko_cfg.get('atr_period', 14),
        atr_multiplier=renko_cfg.get('atr_multiplier', 2.0),
        percentage=renko_cfg.get('percentage', 0.005),
        log_base=renko_cfg.get('log_base', 10.0),
        use_wicks=renko_cfg.get('use_wicks', False)
    )
    renko_df = builder.build(df)
    logger.info(f"砖型图构建完成:")
    logger.info(f"  原始K线: {len(df):,} 条")
    logger.info(f"  砖块数量: {len(renko_df):,} 个")
    logger.info(f"  压缩比: {len(df)/len(renko_df):.2f}:1")
    logger.info(f"  平均砖块大小: ${renko_df['brick_size'].mean():.2f}")
    return renko_df


def run_strategy_backtest(
    renko_df: pd.DataFrame,
    initial_capital: float = 10000.0
) -> dict:
    """运行策略回测"""
    
    # 创建策略实例
    strategy = RenkoReversalStrategy(
        initial_capital=initial_capital,
        commission_rate=0.0004,  # 0.04% 手续费
        slippage_rate=0.0001     # 0.01% 滑点
    )
    
    # 运行回测
    stats = strategy.run_backtest(renko_df)
    
    # 打印统计结果
    strategy.print_statistics(stats)
    
    # 打印交易记录
    strategy.print_all_trades()
    
    return stats


def compare_different_brick_methods(df: pd.DataFrame):
    """对比不同砖块大小方法的策略表现"""
    logger.info("\n" + "="*70)
    logger.info("🔬 对比不同砖块方法的策略表现")
    logger.info("="*70)
    
    methods = ['fixed', 'atr', 'percentage', 'log_percentage']
    results = {}
    
    for method in methods:
        logger.info(f"\n{'='*70}")
        logger.info(f"测试方法: {method.upper()}")
        logger.info("="*70)
        
        # 构建砖型图
        renko_df = build_renko(df, method=method)
        
        # 运行策略
        stats = run_strategy_backtest(renko_df, initial_capital=10000.0)
        
        results[method] = {
            'brick_count': len(renko_df),
            'final_balance': stats['final_balance'],
            'return_pct': stats['total_return_pct'],
            'total_trades': stats['total_trades'],
            'win_rate': stats['win_rate'],
            'max_drawdown': stats['max_drawdown'],
            'profit_factor': stats['profit_factor']
        }
    
    # 打印对比结果
    logger.info("\n" + "="*70)
    logger.info("📊 方法对比总结")
    logger.info("="*70)
    
    df_compare = pd.DataFrame(results).T
    df_compare['return_pct'] = df_compare['return_pct'].apply(lambda x: f"{x:.2%}")
    df_compare['win_rate'] = df_compare['win_rate'].apply(lambda x: f"{x:.2%}")
    df_compare['max_drawdown'] = df_compare['max_drawdown'].apply(lambda x: f"{x:.2%}")
    df_compare['final_balance'] = df_compare['final_balance'].apply(lambda x: f"${x:,.2f}")
    df_compare['profit_factor'] = df_compare['profit_factor'].apply(lambda x: f"{x:.2f}")
    
    print("\n" + df_compare.to_string())
    logger.info("="*70)
    
    return results


def main():
    """主函数"""
    try:
        logger.info("="*70)
        logger.info("🚀 砖型图反转策略回测系统")
        logger.info("="*70)

        # 0. 加载配置文件
        with open('config/config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        renko_cfg = config.get('renko', {})
        data_cfg = config.get('data', {})

        # 1. 加载历史数据（symbol、date可从配置读取或默认）
        logger.info("\n【步骤1】加载历史数据")
        symbol = data_cfg.get('symbol', 'BTCUSDT')
        # date可按需处理，这里仍用默认
        df = load_data(symbol=symbol, date='20251211')

        # 2. 构建砖型图（所有参数从配置文件）
        logger.info("\n【步骤2】构建砖型图")
        renko_df = build_renko(df, renko_cfg)

        # 3. 运行策略回测
        logger.info("\n【步骤3】运行策略回测")
        stats = run_strategy_backtest(renko_df, initial_capital=10000.0)

        logger.info("\n" + "="*70)
        logger.info("✅ 回测完成！")
        logger.info("="*70)
        # 输出指定统计结果
        print("\n回测统计结果:")
        print(f"最终余额: ${stats['final_balance']:,.2f}")
        print(f"总收益率: {stats['total_return_pct']*100:.2f}%")
        print(f"总交易次数: {stats['total_trades']}")
        print(f"胜率: {stats['win_rate']*100:.2f}%")
        print(f"最大回撤: {stats['max_drawdown']*100:.2f}%")
        print(f"盈利因子: {stats['profit_factor']:.2f}")
        if 'total_commission' in stats:
            print(f"总手续费: ${stats['total_commission']:,.2f}")
        else:
            print("总手续费: 未统计")
        
        # 保存结果
        output_dir = Path('data/processed')
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if stats['trades']:
            trades_df = pd.DataFrame([
                {
                    'trade_id': t.trade_id,
                    'direction': '做多' if t.direction == 1 else '做空',
                    'entry_time': t.entry_time,
                    'entry_price': t.entry_price,
                    'exit_time': t.exit_time,
                    'exit_price': t.exit_price,
                    'quantity': t.quantity,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                    'balance_after': t.balance_after
                }
                for t in stats['trades']
            ])
            output_file = output_dir / 'backtest_trades.csv'
            trades_df.to_csv(output_file, index=False)
            logger.info(f"\n交易记录已保存: {output_file}")

        # ======== Professional Equity Curve & BTC Price Visualization ========
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        # Equity curve (balance_after)
        equity_curve = trades_df[['exit_time', 'balance_after']].copy()
        equity_curve['exit_time'] = pd.to_datetime(equity_curve['exit_time'])
        equity_curve.set_index('exit_time', inplace=True)

        # Key statistics
        key_stats = {
            'Final Balance': stats['final_balance'],
            'Max Drawdown': stats['max_drawdown'],
            'Total Return': stats['total_return_pct'],
            'Total Commission': stats.get('total_commission', 0.0),
            'Win Rate': stats['win_rate'],
            'Total Trades': stats['total_trades']
        }

        # BTC price curve (raw Kline)
        btc_curve = df[['timestamp', 'close']].copy()
        btc_curve['timestamp'] = pd.to_datetime(btc_curve['timestamp'])
        btc_curve.set_index('timestamp', inplace=True)

        fig, ax1 = plt.subplots(figsize=(16, 8))
        ax1.plot(equity_curve.index, equity_curve['balance_after'], label='Strategy Equity', color='blue', linewidth=2)
        ax1.set_ylabel('Strategy Equity (USDT)', fontsize=14)
        ax1.set_xlabel('Time', fontsize=14)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax1.tick_params(axis='x', rotation=30)

        # Mark final balance
        ax1.scatter(equity_curve.index[-1], equity_curve['balance_after'].iloc[-1], color='red', s=80, label=f"Final Balance: ${equity_curve['balance_after'].iloc[-1]:,.2f}")

        # BTC price curve on right axis
        ax2 = ax1.twinx()
        ax2.plot(btc_curve.index, btc_curve['close'], label='BTC Price', color='gray', alpha=0.5)
        ax2.set_ylabel('BTC Price (USDT)', fontsize=14)

        # Legends and title
        ax1.legend(loc='upper left', fontsize=12)
        ax2.legend(loc='upper right', fontsize=12)
        plt.title('Strategy Equity Curve vs BTC Price', fontsize=16)

        # Key statistics textbox
        stats_text = '\n'.join([
            f"Final Balance: ${key_stats['Final Balance']:,.2f}",
            f"Max Drawdown: {key_stats['Max Drawdown']*100:.2f}%",
            f"Total Return: {key_stats['Total Return']*100:.2f}%",
            f"Total Commission: ${key_stats['Total Commission']:,.2f}",
            f"Win Rate: {key_stats['Win Rate']*100:.2f}%",
            f"Total Trades: {key_stats['Total Trades']}"
        ])
        plt.gcf().text(0.02, 0.25, stats_text, fontsize=12, bbox=dict(facecolor='white', alpha=0.8))

        plt.tight_layout(rect=[0, 0, 1, 0.97])
        plt.savefig(output_dir / 'equity_vs_btc_curve.png', dpi=150)
        plt.show()
        
        logger.info("\n💡 策略说明:")
        logger.info("  - 规则: 连续2个同向砖块 = 趋势确立")
        logger.info("  - 动作: 趋势反转时立刻平仓并反向开仓")
        logger.info("  - 仓位: 全仓交易，无杠杆")
        logger.info("  - 本金: 10,000 USDT")
        
        logger.info("\n💡 优化建议:")
        logger.info("  1. 调整砖块大小参数（在 build_renko 函数中）")
        logger.info("  2. 添加止损止盈逻辑")
        logger.info("  3. 优化仓位管理（不使用全仓）")
        logger.info("  4. 增加趋势过滤器（避免震荡市场）")
        
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
