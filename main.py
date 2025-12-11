"""
砖型图趋势过滤系统 - 主程序
"""

import sys
import argparse
from pathlib import Path
import yaml
from loguru import logger
from datetime import datetime, timedelta
import pandas as pd

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent))

from core.renko_builder import RenkoBuilder
from core.trend_filter import TrendFilter


class RenkoTrendSystem:
    """砖型图趋势过滤系统主类"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        初始化系统

        Args:
            config_path: 配置文件路径
        """
        self.config = self._load_config(config_path)
        self._setup_logging()
        self._initialize_components()

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        return config

    def _setup_logging(self):
        """设置日志"""
        log_config = self.config.get('logging', {})

        # 移除默认处理器
        logger.remove()

        # 控制台输出
        if log_config.get('console', True):
            logger.add(
                sys.stderr,
                level=log_config.get('level', 'INFO'),
                format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                       "<level>{level: <8}</level> | "
                       "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
                       "<level>{message}</level>"
            )

        # 文件输出
        if log_config.get('file', True):
            log_path = Path(log_config.get('path', 'logs/app.log'))
            log_path.parent.mkdir(parents=True, exist_ok=True)

            logger.add(
                log_path,
                level=log_config.get('level', 'INFO'),
                rotation=log_config.get('max_size', '10 MB'),
                retention=log_config.get('backup_count', 5),
                encoding='utf-8'
            )

    def _initialize_components(self):
        """初始化系统组件"""
        # 砖型图构建器
        renko_config = self.config.get('renko', {})
        self.renko_builder = RenkoBuilder(
            method=renko_config.get('method', 'atr'),
            brick_size=renko_config.get('brick_size'),
            atr_period=renko_config.get('atr_period', 14),
            atr_multiplier=renko_config.get('atr_multiplier', 2.0),
            percentage=renko_config.get('percentage', 0.001),
            use_wicks=renko_config.get('use_wicks', False)
        )

        # 趋势过滤器
        filter_config = self.config.get('trend_filter', {})
        self.trend_filter = TrendFilter(
            min_bricks=filter_config.get('min_bricks', 3),
            strength_threshold=filter_config.get('strength_threshold', 0.6),
            confidence_threshold=filter_config.get('confidence_threshold', 0.7),
            use_volume_filter=filter_config.get('use_volume_filter', True),
            volume_ma_period=filter_config.get('volume_ma_period', 20)
        )

        logger.info("系统组件初始化完成")

    def collect_data(self, symbol: str, days: int = 30):
        """
        采集历史数据

        Args:
            symbol: 交易对符号
            days: 回溯天数
        """
        logger.info(f"开始采集 {symbol} 的历史数据，回溯 {days} 天...")

        try:
            import ccxt

            # 初始化交易所
            exchange_name = self.config['data']['exchange']
            exchange_class = getattr(ccxt, exchange_name)
            exchange = exchange_class()

            # 计算时间范围
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)

            # 获取K线数据
            timeframe = self.config['data']['timeframe']
            since = int(start_time.timestamp() * 1000)

            logger.info(f"从 {exchange_name} 获取 {symbol} {timeframe} K线...")
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since)

            # 转换为DataFrame
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

            # 保存数据
            save_path = Path(self.config['data_collection']['historical']['save_path'])
            save_path.mkdir(parents=True, exist_ok=True)

            filename = f"{symbol.replace('/', '_')}_{timeframe}_{days}d.csv"
            filepath = save_path / filename
            df.to_csv(filepath)

            logger.info(f"数据已保存到: {filepath}")
            logger.info(f"数据行数: {len(df)}, 时间范围: {df.index[0]} 到 {df.index[-1]}")

            return df

        except Exception as e:
            logger.error(f"数据采集失败: {e}")
            raise

    def build_renko(self, ohlc_data: pd.DataFrame) -> pd.DataFrame:
        """
        构建砖型图

        Args:
            ohlc_data: OHLC数据

        Returns:
            砖型图数据
        """
        logger.info("开始构建砖型图...")

        renko_df = self.renko_builder.build(ohlc_data)

        logger.info(f"砖型图构建完成，砖块数: {len(renko_df)}")

        return renko_df

    def analyze_trend(self, renko_df: pd.DataFrame):
        """
        分析趋势

        Args:
            renko_df: 砖型图数据
        """
        logger.info("开始趋势分析...")

        # 趋势分析
        signal = self.trend_filter.analyze(renko_df)

        # 识别支撑阻力
        support, resistance = self.trend_filter.identify_support_resistance(renko_df)

        # 检查突破
        breakout = self.trend_filter.check_breakout(renko_df, support, resistance)

        # 输出结果
        direction_text = {1: '上涨', -1: '下跌', 0: '震荡'}[signal.direction]

        logger.info(f"\n{'='*60}")
        logger.info(f"趋势分析结果:")
        logger.info(f"  方向: {direction_text}")
        logger.info(f"  强度: {signal.strength:.2%}")
        logger.info(f"  可信度: {signal.confidence:.2%}")
        logger.info(f"  连续砖块数: {signal.brick_count}")
        logger.info(f"  距离反转: {signal.reversal_distance} 个砖块")

        if support:
            logger.info(f"\n  支撑位: {', '.join([f'{s:.2f}' for s in support[:3]])}")
        if resistance:
            logger.info(f"  阻力位: {', '.join([f'{r:.2f}' for r in resistance[:3]])}")

        if breakout['breakout']:
            logger.info(f"\n  ⚡ 检测到突破!")
            logger.info(f"  类型: {breakout['type']}")
            logger.info(f"  位置: {breakout['level']:.2f}")
            logger.info(f"  方向: {breakout['direction']}")

        logger.info(f"{'='*60}\n")

        return signal, support, resistance, breakout

    def run_analysis(self, symbol: str, days: int = 30):
        """
        运行完整分析流程

        Args:
            symbol: 交易对
            days: 数据天数
        """
        logger.info(f"开始分析 {symbol}...")

        # 1. 采集数据
        ohlc_data = self.collect_data(symbol, days)

        # 2. 构建砖型图
        renko_df = self.build_renko(ohlc_data)

        # 3. 分析趋势
        signal, support, resistance, breakout = self.analyze_trend(renko_df)

        # 4. 保存结果
        self._save_results(symbol, renko_df, signal, support, resistance, breakout)

        logger.info("分析完成!")

    def _save_results(self, symbol, renko_df, signal, support, resistance, breakout):
        """保存分析结果"""
        # 保存砖型图数据
        output_dir = Path("data/processed")
        output_dir.mkdir(parents=True, exist_ok=True)

        renko_file = output_dir / f"{symbol.replace('/', '_')}_renko.csv"
        renko_df.to_csv(renko_file, index=False)
        logger.info(f"砖型图数据已保存: {renko_file}")

        # 保存分析报告
        report_file = output_dir / f"{symbol.replace('/', '_')}_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"砖型图趋势分析报告\n")
            f.write(f"{'='*60}\n")
            f.write(f"交易对: {symbol}\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"砖块数量: {len(renko_df)}\n\n")

            direction_text = {1: '上涨', -1: '下跌', 0: '震荡'}[signal.direction]
            f.write(f"趋势方向: {direction_text}\n")
            f.write(f"趋势强度: {signal.strength:.2%}\n")
            f.write(f"信号可信度: {signal.confidence:.2%}\n")
            f.write(f"连续砖块数: {signal.brick_count}\n\n")

            if support:
                f.write(f"支撑位: {', '.join([f'{s:.2f}' for s in support[:5]])}\n")
            if resistance:
                f.write(f"阻力位: {', '.join([f'{r:.2f}' for r in resistance[:5]])}\n")

        logger.info(f"分析报告已保存: {report_file}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='砖型图趋势过滤系统')

    parser.add_argument('--symbol', type=str, default='BTC/USDT',
                       help='交易对符号 (default: BTC/USDT)')
    parser.add_argument('--days', type=int, default=30,
                       help='历史数据天数 (default: 30)')
    parser.add_argument('--config', type=str, default='config/config.yaml',
                       help='配置文件路径')

    args = parser.parse_args()

    try:
        # 初始化系统
        system = RenkoTrendSystem(config_path=args.config)

        # 运行分析
        system.run_analysis(symbol=args.symbol, days=args.days)

    except Exception as e:
        logger.error(f"系统运行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
