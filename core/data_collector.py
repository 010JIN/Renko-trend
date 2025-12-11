"""
数据采集器 (Data Collector)
支持多交易所数据采集，自动故障切换
"""

import ccxt
import pandas as pd
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
import time


class DataCollector:
    """
    数据采集器

    支持：
    1. 币安合约（优先）
    2. OKX合约（备用）
    3. 自动故障切换
    4. 数据验证和保存
    """

    def __init__(
        self,
        primary_exchange: str = 'binance',
        backup_exchange: str = 'okx',
        testnet: bool = False,
        api_keys: Optional[Dict] = None
    ):
        """
        初始化数据采集器

        Args:
            primary_exchange: 主交易所
            backup_exchange: 备用交易所
            testnet: 是否使用测试网
            api_keys: API密钥字典
        """
        self.primary_exchange = primary_exchange
        self.backup_exchange = backup_exchange
        self.testnet = testnet
        self.api_keys = api_keys or {}

        self.primary_client = None
        self.backup_client = None
        self.current_exchange = None

        self._initialize_exchanges()

    def _initialize_exchanges(self):
        """初始化交易所客户端"""
        # 初始化主交易所
        try:
            self.primary_client = self._create_exchange_client(self.primary_exchange)
            self.current_exchange = self.primary_exchange
            logger.info(f"✓ 主交易所初始化成功: {self.primary_exchange}")
        except Exception as e:
            logger.error(f"✗ 主交易所初始化失败: {e}")

        # 初始化备用交易所
        try:
            self.backup_client = self._create_exchange_client(self.backup_exchange)
            logger.info(f"✓ 备用交易所初始化成功: {self.backup_exchange}")
        except Exception as e:
            logger.error(f"✗ 备用交易所初始化失败: {e}")

        if not self.primary_client and not self.backup_client:
            raise RuntimeError("所有交易所初始化失败")

    def _create_exchange_client(self, exchange_name: str):
        """
        创建交易所客户端

        Args:
            exchange_name: 交易所名称

        Returns:
            交易所客户端实例
        """
        exchange_class = getattr(ccxt, exchange_name)

        config = {
            'enableRateLimit': True,
            'timeout': 30000,
        }

        # 添加API密钥（如果有）
        if exchange_name in self.api_keys:
            keys = self.api_keys[exchange_name]
            config['apiKey'] = keys.get('api_key', '')
            config['secret'] = keys.get('secret', '')
            if 'password' in keys:
                config['password'] = keys['password']

        # 测试网配置
        if self.testnet:
            if exchange_name == 'binance':
                config['options'] = {'defaultType': 'future'}
                config['urls'] = {
                    'api': {
                        'public': 'https://testnet.binancefuture.com',
                        'private': 'https://testnet.binancefuture.com',
                    }
                }
            elif exchange_name == 'okx':
                config['password'] = self.api_keys.get('okx', {}).get('password', '')

        exchange = exchange_class(config)

        # 设置为合约交易
        if exchange_name == 'binance':
            exchange.options['defaultType'] = 'future'
        elif exchange_name == 'okx':
            exchange.options['defaultType'] = 'swap'

        return exchange

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '5m',
        since: Optional[int] = None,
        limit: int = 1000,
        max_retries: int = 3
    ) -> pd.DataFrame:
        """
        获取OHLCV数据，支持自动切换交易所

        Args:
            symbol: 交易对符号（如 'BTC/USDT'）
            timeframe: 时间周期
            since: 开始时间戳（毫秒）
            limit: 数据条数
            max_retries: 最大重试次数

        Returns:
            OHLCV DataFrame
        """
        # 标准化交易对符号
        symbol = self._normalize_symbol(symbol)

        # 尝试主交易所
        if self.primary_client:
            try:
                logger.info(f"从主交易所 {self.primary_exchange} 获取 {symbol} 数据...")
                df = self._fetch_from_exchange(
                    self.primary_client,
                    symbol,
                    timeframe,
                    since,
                    limit
                )
                self.current_exchange = self.primary_exchange
                logger.success(f"✓ 成功从 {self.primary_exchange} 获取 {len(df)} 条数据")
                return df
            except Exception as e:
                logger.warning(f"主交易所获取失败: {e}")

        # 切换到备用交易所
        if self.backup_client:
            try:
                logger.info(f"切换到备用交易所 {self.backup_exchange}...")
                df = self._fetch_from_exchange(
                    self.backup_client,
                    symbol,
                    timeframe,
                    since,
                    limit
                )
                self.current_exchange = self.backup_exchange
                logger.success(f"✓ 成功从 {self.backup_exchange} 获取 {len(df)} 条数据")
                return df
            except Exception as e:
                logger.error(f"备用交易所也失败了: {e}")

        raise RuntimeError(f"所有交易所都无法获取 {symbol} 数据")

    def _fetch_from_exchange(
        self,
        exchange,
        symbol: str,
        timeframe: str,
        since: Optional[int],
        limit: int
    ) -> pd.DataFrame:
        """
        从指定交易所获取数据

        Args:
            exchange: 交易所客户端
            symbol: 交易对
            timeframe: 时间周期
            since: 开始时间
            limit: 数据条数

        Returns:
            DataFrame
        """
        # 调整交易对格式
        if exchange.id == 'binance':
            # 币安合约使用 BTCUSDT 格式
            symbol_format = symbol.replace('/', '')
        elif exchange.id == 'okx':
            # OKX使用 BTC-USDT-SWAP 格式
            base, quote = symbol.split('/')
            symbol_format = f"{base}-{quote}-SWAP"
        else:
            symbol_format = symbol

        # 获取数据
        ohlcv = exchange.fetch_ohlcv(
            symbol_format,
            timeframe=timeframe,
            since=since,
            limit=limit
        )

        if not ohlcv:
            raise ValueError("未获取到数据")

        # 转换为DataFrame
        df = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )

        # 转换时间戳
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['datetime'] = df['timestamp']

        # 添加元数据
        df['symbol'] = symbol
        df['exchange'] = exchange.id
        df['timeframe'] = timeframe

        return df

    def _normalize_symbol(self, symbol: str) -> str:
        """
        标准化交易对符号

        Args:
            symbol: 原始符号

        Returns:
            标准化符号 (BTC/USDT 格式)
        """
        symbol = symbol.upper().replace(' ', '')

        if '/' not in symbol:
            # 假设是 BTCUSDT 格式，转换为 BTC/USDT
            if 'USDT' in symbol:
                base = symbol.replace('USDT', '')
                return f"{base}/USDT"
            elif 'BUSD' in symbol:
                base = symbol.replace('BUSD', '')
                return f"{base}/BUSD"

        return symbol

    def collect_historical_data(
        self,
        symbols: List[str],
        timeframe: str = '5m',
        days: int = 30,
        save_path: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        批量采集历史数据

        Args:
            symbols: 交易对列表
            timeframe: 时间周期
            days: 回溯天数
            save_path: 保存路径

        Returns:
            数据字典 {symbol: DataFrame}
        """
        logger.info(f"开始批量采集 {len(symbols)} 个交易对的历史数据...")
        logger.info(f"时间周期: {timeframe}, 回溯天数: {days}")

        # 计算时间范围
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        since = int(start_time.timestamp() * 1000)

        results = {}

        for symbol in symbols:
            try:
                logger.info(f"\n{'='*60}")
                logger.info(f"采集 {symbol}...")

                # 获取数据
                df = self.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=5000  # 获取足够多的数据
                )

                # 数据验证
                df = self._validate_data(df)

                results[symbol] = df

                # 保存数据
                if save_path:
                    self._save_data(df, symbol, timeframe, save_path)

                logger.info(f"✓ {symbol} 采集完成")
                logger.info(f"  数据量: {len(df)} 条")
                logger.info(f"  时间范围: {df['datetime'].min()} 到 {df['datetime'].max()}")
                logger.info(f"  来源: {self.current_exchange}")

                # 避免API限流
                time.sleep(0.2)

            except Exception as e:
                logger.error(f"✗ {symbol} 采集失败: {e}")
                continue

        logger.info(f"\n{'='*60}")
        logger.info(f"批量采集完成！成功: {len(results)}/{len(symbols)}")

        return results

    def _validate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        验证和清洗数据

        Args:
            df: 原始数据

        Returns:
            清洗后的数据
        """
        # 删除重复行
        df = df.drop_duplicates(subset=['timestamp'], keep='last')

        # 排序
        df = df.sort_values('timestamp').reset_index(drop=True)

        # 检查缺失值
        if df.isnull().any().any():
            logger.warning("发现缺失值，使用前向填充")
            df = df.fillna(method='ffill')

        # 检查异常值
        for col in ['open', 'high', 'low', 'close']:
            if (df[col] <= 0).any():
                logger.warning(f"发现非正价格，列: {col}")
                df = df[df[col] > 0]

        # 验证OHLC逻辑
        invalid_ohlc = (df['high'] < df['low']) | \
                      (df['high'] < df['open']) | \
                      (df['high'] < df['close']) | \
                      (df['low'] > df['open']) | \
                      (df['low'] > df['close'])

        if invalid_ohlc.any():
            logger.warning(f"发现 {invalid_ohlc.sum()} 条OHLC逻辑错误的数据，已删除")
            df = df[~invalid_ohlc]

        return df

    def _save_data(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        save_path: str
    ):
        """
        保存数据到本地

        Args:
            df: 数据
            symbol: 交易对
            timeframe: 时间周期
            save_path: 保存路径
        """
        # 创建目录
        save_dir = Path(save_path)
        save_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        symbol_clean = symbol.replace('/', '_')
        date_str = datetime.now().strftime('%Y%m%d')
        filename = f"{symbol_clean}_{timeframe}_{date_str}.csv"
        filepath = save_dir / filename

        # 保存为CSV
        df.to_csv(filepath, index=False)
        logger.info(f"  已保存到: {filepath}")

        # 同时保存为Parquet（更高效）
        parquet_file = filepath.with_suffix('.parquet')
        df.to_parquet(parquet_file, index=False)
        logger.info(f"  已保存到: {parquet_file}")

    def get_latest_price(self, symbol: str) -> float:
        """
        获取最新价格

        Args:
            symbol: 交易对

        Returns:
            最新价格
        """
        symbol = self._normalize_symbol(symbol)

        try:
            if self.primary_client:
                ticker = self.primary_client.fetch_ticker(symbol)
                return ticker['last']
        except:
            pass

        if self.backup_client:
            ticker = self.backup_client.fetch_ticker(symbol)
            return ticker['last']

        raise RuntimeError(f"无法获取 {symbol} 最新价格")

    def get_exchange_info(self) -> Dict:
        """获取当前使用的交易所信息"""
        return {
            'current_exchange': self.current_exchange,
            'primary_exchange': self.primary_exchange,
            'backup_exchange': self.backup_exchange,
            'primary_status': 'ok' if self.primary_client else 'failed',
            'backup_status': 'ok' if self.backup_client else 'failed'
        }


if __name__ == "__main__":
    # 测试代码
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))

    logger.info("开始测试数据采集器...")

    # 创建采集器（不需要API密钥，使用公开数据）
    collector = DataCollector(
        primary_exchange='binance',
        backup_exchange='okx',
        testnet=False
    )

    # 测试交易对
    symbols = ['BTC/USDT', 'ETH/USDT']

    # 采集数据
    data = collector.collect_historical_data(
        symbols=symbols,
        timeframe='5m',
        days=7,
        save_path='data/raw'
    )

    # 显示结果
    logger.info("\n" + "="*60)
    logger.info("采集结果汇总:")
    for symbol, df in data.items():
        logger.info(f"\n{symbol}:")
        logger.info(f"  数据量: {len(df)}")
        logger.info(f"  时间范围: {df['datetime'].min()} 到 {df['datetime'].max()}")
        logger.info(f"  价格范围: {df['close'].min():.2f} - {df['close'].max():.2f}")
        logger.info(f"\n最新5条数据:")
        print(df.tail())

    # 获取交易所信息
    info = collector.get_exchange_info()
    logger.info(f"\n交易所信息: {info}")
