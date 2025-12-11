"""
砖型图构建器 (Renko Builder)
将传统OHLC数据转换为砖型图数据
"""

import pandas as pd
import numpy as np
from typing import Literal, Optional, Union
from loguru import logger


class RenkoBuilder:
    """
    砖型图构建器

    支持四种砖块大小计算方法：
    1. fixed - 固定点数
    2. atr - ATR动态调整
    3. percentage - 百分比
    4. log_percentage - 对数百分比（适合长期走势分析）
    """

    def __init__(
        self,
        method: Literal['fixed', 'atr', 'percentage', 'log_percentage'] = 'atr',
        brick_size: Optional[float] = 350.0,
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
        percentage: float = 0.005,
        log_base: float = 10.0,
        use_wicks: bool = False
    ):
        """
        初始化砖型图构建器

        Args:
            method: 砖块大小计算方法 ('fixed', 'atr', 'percentage', 'log_percentage')
            brick_size: 固定砖块大小（method='fixed'时使用）
            atr_period: ATR周期（method='atr'时使用）
            atr_multiplier: ATR倍数（method='atr'时使用）
            percentage: 百分比（method='percentage'或'log_percentage'时使用）
            log_base: 对数底数（method='log_percentage'时使用，默认10）
            use_wicks: 是否使用影线（使用最高/最低价而非收盘价）
        """
        self.method = method
        self.brick_size = brick_size
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.percentage = percentage
        self.log_base = log_base
        self.use_wicks = use_wicks

        if method == 'atr':
            logger.info(f"初始化砖型图构建器: method=atr, atr_period={atr_period}, atr_multiplier={atr_multiplier}")
        elif method == 'fixed':
            logger.info(f"初始化砖型图构建器: method=fixed, brick_size={brick_size}")
        elif method == 'percentage':
            logger.info(f"初始化砖型图构建器: method=percentage, percentage={percentage}")
        elif method == 'log_percentage':
            logger.info(f"初始化砖型图构建器: method=log_percentage, percentage={percentage}, log_base={log_base}")
        else:
            logger.info(f"初始化砖型图构建器: method={method}")

    def build(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        构建砖型图

        Args:
            df: OHLC数据，必须包含列：open, high, low, close

        Returns:
            砖型图数据DataFrame，包含列：
            - brick_open: 砖块开盘价
            - brick_close: 砖块收盘价
            - brick_high: 砖块最高价
            - brick_low: 砖块最低价
            - direction: 砖块方向 (1=上涨, -1=下跌)
            - brick_num: 砖块编号
            - timestamp: 时间戳
            - volume: 累计成交量
        """
        if df.empty:
            raise ValueError("输入数据为空")

        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"数据必须包含列: {required_cols}")

        # 计算砖块大小
        brick_size = self._calculate_brick_size(df)
        logger.info(f"计算得到砖块大小: {brick_size}")

        # 构建砖型图
        renko_bricks = self._build_bricks(df, brick_size)

        logger.info(f"成功构建 {len(renko_bricks)} 个砖块")
        return pd.DataFrame(renko_bricks)

    def _calculate_brick_size(self, df: pd.DataFrame) -> float:
        """计算砖块大小"""
        if self.method == 'fixed':
            if self.brick_size is None:
                raise ValueError("method='fixed'时必须指定brick_size")
            return self.brick_size

        elif self.method == 'atr':
            atr = self._calculate_atr(df, self.atr_period)
            return atr * self.atr_multiplier

        elif self.method == 'percentage':
            current_price = df['close'].iloc[-1]
            return current_price * self.percentage

        elif self.method == 'log_percentage':
            # 使用对数百分比：适合长期走势和宽幅价格变动
            # brick_size = percentage * log(price) / log(base)
            current_price = df['close'].iloc[-1]
            log_price = np.log(current_price) / np.log(self.log_base)
            return self.percentage * log_price

        else:
            raise ValueError(f"不支持的方法: {self.method}")

    def _calculate_atr(self, df: pd.DataFrame, period: int) -> float:
        """
        计算ATR (Average True Range)

        Args:
            df: OHLC数据
            period: ATR周期

        Returns:
            ATR值
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # 真实波动幅度
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # ATR = TR的移动平均
        atr = tr.rolling(window=period).mean()

        return atr.iloc[-1]

    def _build_bricks(self, df: pd.DataFrame, brick_size: float) -> list:
        """
        构建砖块

        Args:
            df: OHLC数据
            brick_size: 砖块大小

        Returns:
            砖块列表
        """
        bricks = []

        # 初始化第一个砖块
        current_brick_open = df['close'].iloc[0]
        current_brick_close = current_brick_open
        current_direction = 0  # 0=未确定
        brick_num = 0
        volume_accumulated = 0

        for idx, row in df.iterrows():
            timestamp = idx if isinstance(idx, pd.Timestamp) else row.get('timestamp')

            # 使用影线或收盘价
            if self.use_wicks:
                price_high = row['high']
                price_low = row['low']
            else:
                price_high = row['close']
                price_low = row['close']

            volume = row.get('volume', 0)
            volume_accumulated += volume

            # 检查是否形成新砖块
            while True:
                # 向上砖块
                if price_high >= current_brick_close + brick_size:
                    # 形成上涨砖块
                    brick_num += 1
                    bricks.append({
                        'brick_num': brick_num,
                        'brick_open': current_brick_close,
                        'brick_close': current_brick_close + brick_size,
                        'brick_high': current_brick_close + brick_size,
                        'brick_low': current_brick_close,
                        'direction': 1,
                        'timestamp': timestamp,
                        'volume': volume_accumulated,
                        'brick_size': brick_size
                    })

                    current_brick_close += brick_size
                    current_direction = 1
                    volume_accumulated = 0

                # 向下砖块
                elif price_low <= current_brick_close - brick_size:
                    # 形成下跌砖块
                    brick_num += 1
                    bricks.append({
                        'brick_num': brick_num,
                        'brick_open': current_brick_close,
                        'brick_close': current_brick_close - brick_size,
                        'brick_high': current_brick_close,
                        'brick_low': current_brick_close - brick_size,
                        'direction': -1,
                        'timestamp': timestamp,
                        'volume': volume_accumulated,
                        'brick_size': brick_size
                    })

                    current_brick_close -= brick_size
                    current_direction = -1
                    volume_accumulated = 0

                else:
                    # 未形成新砖块，退出循环
                    break

        return bricks

    def get_brick_reversals(self, renko_df: pd.DataFrame) -> pd.DataFrame:
        """
        获取砖块反转点

        Args:
            renko_df: 砖型图数据

        Returns:
            反转点DataFrame
        """
        reversals = []

        for i in range(1, len(renko_df)):
            current_dir = renko_df.iloc[i]['direction']
            prev_dir = renko_df.iloc[i-1]['direction']

            if current_dir != prev_dir:
                reversals.append({
                    'brick_num': renko_df.iloc[i]['brick_num'],
                    'timestamp': renko_df.iloc[i]['timestamp'],
                    'price': renko_df.iloc[i]['brick_open'],
                    'from_direction': prev_dir,
                    'to_direction': current_dir,
                    'reversal_type': 'bullish' if current_dir == 1 else 'bearish'
                })

        return pd.DataFrame(reversals)

    def calculate_trend_strength(self, renko_df: pd.DataFrame, window: int = 10) -> pd.Series:
        """
        计算趋势强度

        Args:
            renko_df: 砖型图数据
            window: 统计窗口

        Returns:
            趋势强度序列 (0-1)
        """
        # 统计窗口内同向砖块的比例
        direction_consistency = renko_df['direction'].rolling(window=window).apply(
            lambda x: abs(x.sum()) / len(x) if len(x) > 0 else 0
        )

        return direction_consistency


if __name__ == "__main__":
    # 测试代码
    import yfinance as yf

    # 下载测试数据
    print("下载测试数据...")
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(period="7d", interval="5m")
    df.columns = df.columns.str.lower()

    # 构建砖型图 - ATR方法
    print("\n使用ATR方法构建砖型图...")
    builder = RenkoBuilder(method='atr', atr_period=14, atr_multiplier=2.0)
    renko_df = builder.build(df)

    print(f"\n原始K线数量: {len(df)}")
    print(f"砖块数量: {len(renko_df)}")
    print(f"\n前5个砖块:")
    print(renko_df.head())

    # 获取反转点
    print("\n获取反转点...")
    reversals = builder.get_brick_reversals(renko_df)
    print(f"反转次数: {len(reversals)}")
    print(reversals.head())

    # 计算趋势强度
    print("\n计算趋势强度...")
    renko_df['trend_strength'] = builder.calculate_trend_strength(renko_df, window=10)
    print(renko_df[['brick_num', 'direction', 'trend_strength']].tail())
