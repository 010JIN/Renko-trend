"""
趋势过滤器 (Trend Filter)
基于砖型图分析市场趋势，过滤噪音信号
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from loguru import logger
from dataclasses import dataclass


@dataclass
class TrendSignal:
    """趋势信号数据类"""
    direction: int  # 1=上涨, -1=下跌, 0=震荡
    strength: float  # 0-1, 趋势强度
    confidence: float  # 0-1, 信号可信度
    brick_count: int  # 连续同向砖块数
    reversal_distance: int  # 距离上次反转的砖块数
    timestamp: pd.Timestamp
    details: Dict


class TrendFilter:
    """
    趋势过滤器

    多维度分析砖型图趋势：
    1. 连续砖块数量
    2. 趋势持续时间
    3. 趋势强度
    4. 多周期确认
    """

    def __init__(
        self,
        min_bricks: int = 3,
        strength_threshold: float = 0.6,
        confidence_threshold: float = 0.7,
        use_volume_filter: bool = True,
        volume_ma_period: int = 20
    ):
        """
        初始化趋势过滤器

        Args:
            min_bricks: 最小连续砖块数
            strength_threshold: 趋势强度阈值
            confidence_threshold: 信号可信度阈值
            use_volume_filter: 是否使用成交量过滤
            volume_ma_period: 成交量移动平均周期
        """
        self.min_bricks = min_bricks
        self.strength_threshold = strength_threshold
        self.confidence_threshold = confidence_threshold
        self.use_volume_filter = use_volume_filter
        self.volume_ma_period = volume_ma_period

        logger.info(f"初始化趋势过滤器: min_bricks={min_bricks}, "
                   f"strength_threshold={strength_threshold}")

    def analyze(self, renko_df: pd.DataFrame) -> TrendSignal:
        """
        分析当前趋势

        Args:
            renko_df: 砖型图数据

        Returns:
            TrendSignal对象
        """
        if len(renko_df) < self.min_bricks:
            return TrendSignal(
                direction=0,
                strength=0.0,
                confidence=0.0,
                brick_count=0,
                reversal_distance=0,
                timestamp=renko_df.iloc[-1]['timestamp'],
                details={"reason": "数据不足"}
            )

        # 1. 计算连续同向砖块
        brick_count = self._count_consecutive_bricks(renko_df)

        # 2. 计算趋势强度
        strength = self._calculate_strength(renko_df)

        # 3. 计算可信度
        confidence = self._calculate_confidence(renko_df, brick_count, strength)

        # 4. 确定方向
        direction = renko_df.iloc[-1]['direction']

        # 5. 计算距离反转的距离
        reversal_distance = self._calculate_reversal_distance(renko_df)

        # 6. 应用过滤器
        if brick_count < self.min_bricks:
            direction = 0
            confidence *= 0.5

        if strength < self.strength_threshold:
            confidence *= 0.7

        # 7. 成交量过滤
        volume_confirmed = True
        if self.use_volume_filter:
            volume_confirmed = self._check_volume_confirmation(renko_df)
            if not volume_confirmed:
                confidence *= 0.8

        details = {
            "brick_count": brick_count,
            "strength": strength,
            "volume_confirmed": volume_confirmed,
            "reversal_distance": reversal_distance
        }

        return TrendSignal(
            direction=direction if confidence >= self.confidence_threshold else 0,
            strength=strength,
            confidence=confidence,
            brick_count=brick_count,
            reversal_distance=reversal_distance,
            timestamp=renko_df.iloc[-1]['timestamp'],
            details=details
        )

    def _count_consecutive_bricks(self, renko_df: pd.DataFrame) -> int:
        """计算连续同向砖块数"""
        if len(renko_df) == 0:
            return 0

        current_direction = renko_df.iloc[-1]['direction']
        count = 0

        for i in range(len(renko_df) - 1, -1, -1):
            if renko_df.iloc[i]['direction'] == current_direction:
                count += 1
            else:
                break

        return count

    def _calculate_strength(self, renko_df: pd.DataFrame, window: int = 20) -> float:
        """
        计算趋势强度

        基于：
        1. 窗口内同向砖块比例
        2. 砖块形成速度（可选）
        """
        if len(renko_df) < window:
            window = len(renko_df)

        recent_bricks = renko_df.tail(window)

        # 方法1: 同向砖块比例
        direction_sum = abs(recent_bricks['direction'].sum())
        consistency = direction_sum / len(recent_bricks)

        # 方法2: 方向一致性标准差（越小越强）
        direction_std = recent_bricks['direction'].std()
        consistency_score = 1 - (direction_std / 2)  # 归一化到0-1

        # 综合评分
        strength = (consistency * 0.7 + consistency_score * 0.3)

        return min(max(strength, 0.0), 1.0)

    def _calculate_confidence(
        self,
        renko_df: pd.DataFrame,
        brick_count: int,
        strength: float
    ) -> float:
        """
        计算信号可信度

        综合考虑：
        1. 连续砖块数
        2. 趋势强度
        3. 砖块形成的时间间隔（可选）
        """
        # 砖块数量评分（sigmoid函数）
        brick_score = 1 / (1 + np.exp(-0.5 * (brick_count - self.min_bricks)))

        # 强度评分
        strength_score = strength

        # 综合评分
        confidence = (brick_score * 0.4 + strength_score * 0.6)

        return min(max(confidence, 0.0), 1.0)

    def _calculate_reversal_distance(self, renko_df: pd.DataFrame) -> int:
        """计算距离上次反转的砖块数"""
        if len(renko_df) < 2:
            return 0

        current_direction = renko_df.iloc[-1]['direction']
        distance = 0

        for i in range(len(renko_df) - 1, -1, -1):
            if renko_df.iloc[i]['direction'] == current_direction:
                distance += 1
            else:
                break

        return distance

    def _check_volume_confirmation(self, renko_df: pd.DataFrame) -> bool:
        """
        成交量确认

        最近砖块的成交量应该高于移动平均
        """
        if 'volume' not in renko_df.columns:
            return True  # 无成交量数据时默认通过

        if len(renko_df) < self.volume_ma_period:
            return True

        # 计算成交量移动平均
        volume_ma = renko_df['volume'].rolling(window=self.volume_ma_period).mean()

        # 最近3个砖块的平均成交量
        recent_volume = renko_df.tail(3)['volume'].mean()
        avg_volume = volume_ma.iloc[-1]

        # 最近成交量应该大于平均值
        return recent_volume > avg_volume * 0.8

    def identify_support_resistance(
        self,
        renko_df: pd.DataFrame,
        lookback: int = 50
    ) -> Tuple[List[float], List[float]]:
        """
        识别支撑和阻力位

        基于砖块反转点的价格聚类

        Args:
            renko_df: 砖型图数据
            lookback: 回溯砖块数

        Returns:
            (support_levels, resistance_levels)
        """
        if len(renko_df) < lookback:
            lookback = len(renko_df)

        recent_data = renko_df.tail(lookback)

        # 找到反转点
        reversals = []
        for i in range(1, len(recent_data)):
            if recent_data.iloc[i]['direction'] != recent_data.iloc[i-1]['direction']:
                price = recent_data.iloc[i]['brick_open']
                direction = recent_data.iloc[i]['direction']
                reversals.append({'price': price, 'direction': direction})

        if len(reversals) < 2:
            return [], []

        # 价格聚类（简单方法：使用价格范围）
        reversal_prices = [r['price'] for r in reversals]
        price_range = max(reversal_prices) - min(reversal_prices)
        cluster_threshold = price_range * 0.02  # 2%范围内视为同一水平

        # 识别支撑和阻力
        support_levels = []
        resistance_levels = []

        for reversal in reversals:
            price = reversal['price']
            direction = reversal['direction']

            # 检查是否已有相近的水平
            if direction == 1:  # 从下跌转为上涨 -> 支撑
                if not any(abs(s - price) < cluster_threshold for s in support_levels):
                    support_levels.append(price)
            else:  # 从上涨转为下跌 -> 阻力
                if not any(abs(r - price) < cluster_threshold for r in resistance_levels):
                    resistance_levels.append(price)

        return sorted(support_levels), sorted(resistance_levels, reverse=True)

    def check_breakout(
        self,
        renko_df: pd.DataFrame,
        support_levels: List[float],
        resistance_levels: List[float]
    ) -> Dict:
        """
        检查突破

        Args:
            renko_df: 砖型图数据
            support_levels: 支撑位列表
            resistance_levels: 阻力位列表

        Returns:
            突破信息字典
        """
        if len(renko_df) < 2:
            return {"breakout": False}

        current_price = renko_df.iloc[-1]['brick_close']
        prev_price = renko_df.iloc[-2]['brick_close']
        direction = renko_df.iloc[-1]['direction']

        # 检查阻力突破
        if direction == 1:
            for resistance in resistance_levels:
                if prev_price < resistance <= current_price:
                    return {
                        "breakout": True,
                        "type": "resistance",
                        "level": resistance,
                        "direction": "bullish"
                    }

        # 检查支撑突破
        elif direction == -1:
            for support in support_levels:
                if prev_price > support >= current_price:
                    return {
                        "breakout": True,
                        "type": "support",
                        "level": support,
                        "direction": "bearish"
                    }

        return {"breakout": False}


if __name__ == "__main__":
    # 测试代码
    from core.renko_builder import RenkoBuilder
    import yfinance as yf

    print("下载测试数据...")
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(period="30d", interval="1h")
    df.columns = df.columns.str.lower()

    print("构建砖型图...")
    builder = RenkoBuilder(method='atr', atr_period=14, atr_multiplier=2.0)
    renko_df = builder.build(df)

    print("分析趋势...")
    filter = TrendFilter(min_bricks=3, strength_threshold=0.6)
    signal = filter.analyze(renko_df)

    print(f"\n当前趋势分析:")
    print(f"  方向: {'上涨' if signal.direction == 1 else '下跌' if signal.direction == -1 else '震荡'}")
    print(f"  强度: {signal.strength:.2f}")
    print(f"  可信度: {signal.confidence:.2f}")
    print(f"  连续砖块数: {signal.brick_count}")
    print(f"  详情: {signal.details}")

    print("\n识别支撑阻力位...")
    support, resistance = filter.identify_support_resistance(renko_df)
    print(f"  支撑位: {[f'{s:.2f}' for s in support[:3]]}")
    print(f"  阻力位: {[f'{r:.2f}' for r in resistance[:3]]}")

    print("\n检查突破...")
    breakout = filter.check_breakout(renko_df, support, resistance)
    print(f"  突破信息: {breakout}")
