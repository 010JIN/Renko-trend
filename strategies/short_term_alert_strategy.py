"""
短期交易警报策略 (Short-term Trading Alert Strategy)

专为 MNQ (Micro E-mini Nasdaq-100) 和 MGC (Micro Gold Futures) 设计
支持 5分钟/15分钟 级别的反转和趋势交易信号

功能:
1. K线形态识别 (锤子线、吞没形态、十字星等)
2. 订单流分析 (成交量Delta、不平衡检测)
3. 反转信号生成 (RSI背离、关键位支撑/阻力)
4. 趋势突破信号 (成交量确认、假突破过滤)
5. 顺势交易信号 (回撤入场点)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger


class SignalType(Enum):
    """信号类型"""
    REVERSAL_BULLISH = "REVERSAL_BULLISH"       # 看涨反转
    REVERSAL_BEARISH = "REVERSAL_BEARISH"       # 看跌反转
    BREAKOUT_BULLISH = "BREAKOUT_BULLISH"       # 看涨突破
    BREAKOUT_BEARISH = "BREAKOUT_BEARISH"       # 看跌突破
    TREND_CONTINUATION_LONG = "TREND_LONG"      # 顺势做多
    TREND_CONTINUATION_SHORT = "TREND_SHORT"    # 顺势做空
    NO_SIGNAL = "NO_SIGNAL"                     # 无信号


class PatternType(Enum):
    """K线形态类型"""
    HAMMER = "锤子线"
    INVERTED_HAMMER = "倒锤子"
    BULLISH_ENGULFING = "看涨吞没"
    BEARISH_ENGULFING = "看跌吞没"
    PIERCING = "刺透形态"
    DARK_CLOUD = "乌云盖顶"
    DOJI = "十字星"
    MORNING_STAR = "早晨之星"
    EVENING_STAR = "黄昏之星"
    THREE_WHITE_SOLDIERS = "三白兵"
    THREE_BLACK_CROWS = "三乌鸦"
    BULLISH_FLAG = "看涨旗形"
    BEARISH_FLAG = "看跌旗形"


@dataclass
class TradingAlert:
    """交易警报数据类"""
    timestamp: datetime
    instrument: str              # 交易品种 (MNQ/MGC)
    signal_type: SignalType      # 信号类型
    direction: int               # 方向 1=多头, -1=空头
    price: float                 # 当前价格
    entry_price: float           # 建议入场价格
    stop_loss: float             # 建议止损价格
    take_profit: float           # 建议止盈价格
    confidence: float            # 信号置信度 (0-1)
    timeframe: str               # 时间框架
    patterns: List[str] = field(default_factory=list)          # 识别到的形态
    reasons: List[str] = field(default_factory=list)           # 信号原因
    order_flow_data: Dict = field(default_factory=dict)        # 订单流数据
    risk_reward_ratio: float = 0.0    # 风险回报比
    
    def __str__(self) -> str:
        direction_text = "🟢 做多" if self.direction == 1 else "🔴 做空"
        return (
            f"\n{'='*60}\n"
            f"⚠️  交易警报 - {self.instrument}\n"
            f"{'='*60}\n"
            f"时间: {self.timestamp}\n"
            f"信号: {self.signal_type.value} {direction_text}\n"
            f"当前价格: {self.price:.2f}\n"
            f"入场价格: {self.entry_price:.2f}\n"
            f"止损价格: {self.stop_loss:.2f}\n"
            f"止盈价格: {self.take_profit:.2f}\n"
            f"风险回报比: 1:{self.risk_reward_ratio:.2f}\n"
            f"置信度: {self.confidence*100:.1f}%\n"
            f"时间框架: {self.timeframe}\n"
            f"形态: {', '.join(self.patterns) if self.patterns else '无'}\n"
            f"原因: {'; '.join(self.reasons)}\n"
            f"{'='*60}"
        )


class CandlestickPatternRecognizer:
    """K线形态识别器"""
    
    @staticmethod
    def is_doji(candle: pd.Series, threshold: float = 0.1) -> bool:
        """检测十字星"""
        body = abs(candle['close'] - candle['open'])
        range_hl = candle['high'] - candle['low']
        return body <= range_hl * threshold if range_hl > 0 else False
    
    @staticmethod
    def is_hammer(candle: pd.Series, prev_candles: pd.DataFrame) -> bool:
        """检测锤子线 (下跌趋势中出现)"""
        body = abs(candle['close'] - candle['open'])
        range_hl = candle['high'] - candle['low']
        
        if range_hl == 0:
            return False
            
        # 实体小于整体范围的1/3
        if body > range_hl * 0.35:
            return False
            
        # 下影线至少是实体的2倍
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        if lower_shadow < body * 2:
            return False
            
        # 上影线很小
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        if upper_shadow > body * 0.5:
            return False
            
        # 前面是下跌趋势: 较早的收盘价平均值 > 较近的收盘价
        if len(prev_candles) >= 3:
            earlier_avg = prev_candles['close'].iloc[-3:-1].mean()  # 前2根K线的平均
            recent_close = prev_candles['close'].iloc[-1]  # 最后一根K线
            is_downtrend = earlier_avg > recent_close
            return is_downtrend
            
        return False
    
    @staticmethod
    def is_inverted_hammer(candle: pd.Series, prev_candles: pd.DataFrame) -> bool:
        """检测倒锤子 (下跌趋势中出现)"""
        body = abs(candle['close'] - candle['open'])
        range_hl = candle['high'] - candle['low']
        
        if range_hl == 0:
            return False
            
        # 实体小于整体范围的1/3
        if body > range_hl * 0.35:
            return False
            
        # 上影线至少是实体的2倍
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        if upper_shadow < body * 2:
            return False
            
        # 下影线很小
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        if lower_shadow > body * 0.5:
            return False
            
        # 前面是下跌趋势: 较早的收盘价平均值 > 较近的收盘价
        if len(prev_candles) >= 3:
            earlier_avg = prev_candles['close'].iloc[-3:-1].mean()  # 前2根K线的平均
            recent_close = prev_candles['close'].iloc[-1]  # 最后一根K线
            is_downtrend = earlier_avg > recent_close
            return is_downtrend
            
        return False
    
    @staticmethod
    def is_bullish_engulfing(candle: pd.Series, prev_candle: pd.Series) -> bool:
        """检测看涨吞没"""
        # 前一根是阴线
        if prev_candle['close'] >= prev_candle['open']:
            return False
            
        # 当前是阳线
        if candle['close'] <= candle['open']:
            return False
            
        # 当前实体完全包裹前一根实体
        curr_body_high = candle['close']
        curr_body_low = candle['open']
        prev_body_high = prev_candle['open']
        prev_body_low = prev_candle['close']
        
        return curr_body_high > prev_body_high and curr_body_low < prev_body_low
    
    @staticmethod
    def is_bearish_engulfing(candle: pd.Series, prev_candle: pd.Series) -> bool:
        """检测看跌吞没"""
        # 前一根是阳线
        if prev_candle['close'] <= prev_candle['open']:
            return False
            
        # 当前是阴线
        if candle['close'] >= candle['open']:
            return False
            
        # 当前实体完全包裹前一根实体
        curr_body_high = candle['open']
        curr_body_low = candle['close']
        prev_body_high = prev_candle['close']
        prev_body_low = prev_candle['open']
        
        return curr_body_high > prev_body_high and curr_body_low < prev_body_low
    
    @staticmethod
    def is_morning_star(candles: pd.DataFrame) -> bool:
        """检测早晨之星 (需要最近3根K线)"""
        if len(candles) < 3:
            return False
            
        first = candles.iloc[-3]
        second = candles.iloc[-2]
        third = candles.iloc[-1]
        
        # 第一根是长阴线
        first_body = first['open'] - first['close']
        if first_body <= 0:
            return False
            
        # 第二根是小实体 (十字星或小K线)
        second_body = abs(second['close'] - second['open'])
        first_range = first['high'] - first['low']
        if second_body > first_range * 0.3:
            return False
            
        # 第三根是长阳线，收盘价高于第一根实体中点
        third_body = third['close'] - third['open']
        if third_body <= 0:
            return False
            
        first_midpoint = (first['open'] + first['close']) / 2
        return third['close'] > first_midpoint
    
    @staticmethod
    def is_evening_star(candles: pd.DataFrame) -> bool:
        """检测黄昏之星 (需要最近3根K线)"""
        if len(candles) < 3:
            return False
            
        first = candles.iloc[-3]
        second = candles.iloc[-2]
        third = candles.iloc[-1]
        
        # 第一根是长阳线
        first_body = first['close'] - first['open']
        if first_body <= 0:
            return False
            
        # 第二根是小实体 (十字星或小K线)
        second_body = abs(second['close'] - second['open'])
        first_range = first['high'] - first['low']
        if second_body > first_range * 0.3:
            return False
            
        # 第三根是长阴线，收盘价低于第一根实体中点
        third_body = third['open'] - third['close']
        if third_body <= 0:
            return False
            
        first_midpoint = (first['open'] + first['close']) / 2
        return third['close'] < first_midpoint


class OrderFlowAnalyzer:
    """订单流分析器"""
    
    def __init__(self, delta_threshold: float = 0.2, imbalance_ratio: float = 2.0):
        self.delta_threshold = delta_threshold
        self.imbalance_ratio = imbalance_ratio
    
    def calculate_delta(self, df: pd.DataFrame) -> pd.Series:
        """
        计算成交量Delta
        Delta = 买入成交量 - 卖出成交量
        
        简化计算: 
        - 阳线的成交量视为买入
        - 阴线的成交量视为卖出
        """
        delta = pd.Series(index=df.index, dtype=float)
        
        for i, (idx, row) in enumerate(df.iterrows()):
            if row['close'] > row['open']:
                # 阳线: 买入为主
                buy_vol = row['volume'] * 0.7
                sell_vol = row['volume'] * 0.3
            elif row['close'] < row['open']:
                # 阴线: 卖出为主
                buy_vol = row['volume'] * 0.3
                sell_vol = row['volume'] * 0.7
            else:
                # 十字星: 平衡
                buy_vol = row['volume'] * 0.5
                sell_vol = row['volume'] * 0.5
            
            delta.iloc[i] = buy_vol - sell_vol
            
        return delta
    
    def calculate_cumulative_delta(self, df: pd.DataFrame) -> pd.Series:
        """计算累积Delta"""
        delta = self.calculate_delta(df)
        return delta.cumsum()
    
    def detect_delta_divergence(self, df: pd.DataFrame, lookback: int = 10) -> Dict:
        """
        检测Delta背离
        - 价格新高但Delta未新高 = 看跌背离
        - 价格新低但Delta未新低 = 看涨背离
        """
        if len(df) < lookback:
            return {"divergence": False}
            
        recent = df.tail(lookback).copy()
        cum_delta = self.calculate_cumulative_delta(recent)
        
        # 检测看跌背离
        price_high_idx = recent['high'].idxmax()
        delta_high_idx = cum_delta.idxmax()
        
        if price_high_idx != delta_high_idx:
            # 价格在最近创新高，但Delta没有
            if recent['high'].iloc[-1] == recent['high'].max():
                if cum_delta.iloc[-1] < cum_delta.max():
                    return {
                        "divergence": True,
                        "type": "bearish",
                        "description": "价格新高但Delta未新高 - 看跌背离"
                    }
        
        # 检测看涨背离
        price_low_idx = recent['low'].idxmin()
        delta_low_idx = cum_delta.idxmin()
        
        if price_low_idx != delta_low_idx:
            # 价格在最近创新低，但Delta没有
            if recent['low'].iloc[-1] == recent['low'].min():
                if cum_delta.iloc[-1] > cum_delta.min():
                    return {
                        "divergence": True,
                        "type": "bullish",
                        "description": "价格新低但Delta未新低 - 看涨背离"
                    }
        
        return {"divergence": False}
    
    def detect_volume_imbalance(self, df: pd.DataFrame, lookback: int = 5) -> Dict:
        """检测成交量不平衡"""
        if len(df) < lookback:
            return {"imbalance": False}
            
        recent = df.tail(lookback)
        
        # 计算买卖成交量
        buy_volume = 0
        sell_volume = 0
        
        for _, row in recent.iterrows():
            if row['close'] > row['open']:
                buy_volume += row['volume']
            elif row['close'] < row['open']:
                sell_volume += row['volume']
            else:
                buy_volume += row['volume'] * 0.5
                sell_volume += row['volume'] * 0.5
        
        # 处理零成交量情况
        if sell_volume == 0 and buy_volume == 0:
            return {"imbalance": False, "reason": "成交量数据不足"}
        
        if sell_volume == 0:
            # 只有买入量，极度看涨
            return {
                "imbalance": True,
                "type": "bullish",
                "ratio": float('inf'),
                "description": "仅有买入量，极度不平衡"
            }
        if buy_volume == 0:
            # 只有卖出量，极度看跌
            return {
                "imbalance": True,
                "type": "bearish",
                "ratio": float('inf'),
                "description": "仅有卖出量，极度不平衡"
            }
            
        buy_sell_ratio = buy_volume / sell_volume
        sell_buy_ratio = sell_volume / buy_volume
        
        result = {"imbalance": False}
        
        if buy_sell_ratio >= self.imbalance_ratio:
            result = {
                "imbalance": True,
                "type": "bullish",
                "ratio": buy_sell_ratio,
                "description": f"买入量是卖出量的 {buy_sell_ratio:.2f} 倍"
            }
        elif sell_buy_ratio >= self.imbalance_ratio:
            result = {
                "imbalance": True,
                "type": "bearish",
                "ratio": sell_buy_ratio,
                "description": f"卖出量是买入量的 {sell_buy_ratio:.2f} 倍"
            }
        
        return result
    
    def analyze(self, df: pd.DataFrame) -> Dict:
        """综合订单流分析"""
        delta = self.calculate_delta(df)
        cum_delta = self.calculate_cumulative_delta(df)
        divergence = self.detect_delta_divergence(df)
        imbalance = self.detect_volume_imbalance(df)
        
        # 确定Delta趋势
        if len(cum_delta) >= 5:
            recent_delta_mean = cum_delta.iloc[-5:].mean()
            if recent_delta_mean > 0:
                delta_trend = "bullish"
            else:
                delta_trend = "bearish"
        else:
            delta_trend = "neutral"
        
        return {
            "current_delta": delta.iloc[-1] if len(delta) > 0 else 0,
            "cumulative_delta": cum_delta.iloc[-1] if len(cum_delta) > 0 else 0,
            "divergence": divergence,
            "imbalance": imbalance,
            "delta_trend": delta_trend
        }


class TechnicalIndicators:
    """技术指标计算器"""
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """计算EMA"""
        return series.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算布林带"""
        middle = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return upper, middle, lower
    
    @staticmethod
    def detect_rsi_divergence(df: pd.DataFrame, rsi: pd.Series, lookback: int = 10) -> Dict:
        """检测RSI背离"""
        if len(df) < lookback or len(rsi) < lookback:
            return {"divergence": False}
            
        recent_price = df.tail(lookback)
        recent_rsi = rsi.tail(lookback)
        
        # 看跌背离: 价格新高但RSI未新高
        if recent_price['high'].iloc[-1] >= recent_price['high'].max() * 0.99:  # 接近最高
            if recent_rsi.iloc[-1] < recent_rsi.max() * 0.95:  # RSI明显低于最高
                return {
                    "divergence": True,
                    "type": "bearish",
                    "description": "价格新高但RSI未新高 - 看跌背离"
                }
        
        # 看涨背离: 价格新低但RSI未新低
        if recent_price['low'].iloc[-1] <= recent_price['low'].min() * 1.01:  # 接近最低
            if recent_rsi.iloc[-1] > recent_rsi.min() * 1.05:  # RSI明显高于最低
                return {
                    "divergence": True,
                    "type": "bullish",
                    "description": "价格新低但RSI未新低 - 看涨背离"
                }
        
        return {"divergence": False}


class ShortTermAlertStrategy:
    """
    短期交易警报策略
    
    整合:
    - K线形态识别
    - 订单流分析
    - 技术指标
    - 趋势过滤
    """
    
    def __init__(
        self,
        instrument: str = "MNQ",
        timeframe: str = "5m",
        rsi_oversold: int = 30,
        rsi_overbought: int = 70,
        min_confidence: float = 0.6,
        atr_sl_multiplier: float = 2.0,
        risk_reward_ratio: float = 2.0
    ):
        """
        初始化策略
        
        Args:
            instrument: 交易品种 (MNQ/MGC)
            timeframe: 时间框架 (5m/15m)
            rsi_oversold: RSI超卖阈值
            rsi_overbought: RSI超买阈值
            min_confidence: 最小信号置信度
            atr_sl_multiplier: ATR止损倍数
            risk_reward_ratio: 风险回报比
        """
        self.instrument = instrument
        self.timeframe = timeframe
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.min_confidence = min_confidence
        self.atr_sl_multiplier = atr_sl_multiplier
        self.risk_reward_ratio = risk_reward_ratio
        
        # 初始化分析器
        self.pattern_recognizer = CandlestickPatternRecognizer()
        self.order_flow = OrderFlowAnalyzer()
        self.indicators = TechnicalIndicators()
        
        # 警报历史
        self.alerts: List[TradingAlert] = []
        
        logger.info(f"初始化短期警报策略: {instrument} | {timeframe} | "
                   f"RSI: {rsi_oversold}/{rsi_overbought}")
    
    def _identify_patterns(self, df: pd.DataFrame) -> Tuple[List[str], int]:
        """
        识别K线形态
        
        Returns:
            (形态列表, 方向建议: 1=多头, -1=空头, 0=中性)
        """
        patterns = []
        direction = 0
        
        if len(df) < 3:
            return patterns, direction
            
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 检测各种形态
        if self.pattern_recognizer.is_doji(current):
            patterns.append(PatternType.DOJI.value)
            
        if self.pattern_recognizer.is_hammer(current, df.iloc[:-1]):
            patterns.append(PatternType.HAMMER.value)
            direction = 1
            
        if self.pattern_recognizer.is_inverted_hammer(current, df.iloc[:-1]):
            patterns.append(PatternType.INVERTED_HAMMER.value)
            direction = 1
            
        if self.pattern_recognizer.is_bullish_engulfing(current, prev):
            patterns.append(PatternType.BULLISH_ENGULFING.value)
            direction = 1
            
        if self.pattern_recognizer.is_bearish_engulfing(current, prev):
            patterns.append(PatternType.BEARISH_ENGULFING.value)
            direction = -1
            
        if self.pattern_recognizer.is_morning_star(df):
            patterns.append(PatternType.MORNING_STAR.value)
            direction = 1
            
        if self.pattern_recognizer.is_evening_star(df):
            patterns.append(PatternType.EVENING_STAR.value)
            direction = -1
        
        return patterns, direction
    
    def _identify_support_resistance(self, df: pd.DataFrame, lookback: int = 20) -> Tuple[List[float], List[float]]:
        """识别支撑和阻力位"""
        if len(df) < lookback:
            lookback = len(df)
            
        recent = df.tail(lookback)
        
        # 使用最高点和最低点
        highs = recent['high'].nlargest(3).tolist()
        lows = recent['low'].nsmallest(3).tolist()
        
        # 简化：使用价格聚类
        resistance_levels = []
        support_levels = []
        
        # 聚类阈值
        price_range = recent['high'].max() - recent['low'].min()
        cluster_threshold = price_range * 0.02  # 2%
        
        for high in highs:
            if not any(abs(r - high) < cluster_threshold for r in resistance_levels):
                resistance_levels.append(high)
                
        for low in lows:
            if not any(abs(s - low) < cluster_threshold for s in support_levels):
                support_levels.append(low)
        
        return sorted(support_levels), sorted(resistance_levels, reverse=True)
    
    def _check_breakout(
        self, 
        df: pd.DataFrame, 
        support_levels: List[float], 
        resistance_levels: List[float]
    ) -> Optional[Dict]:
        """检测突破"""
        if len(df) < 2:
            return None
            
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_close = current['close']
        prev_close = prev['close']
        current_volume = current['volume']
        
        # 计算平均成交量
        avg_volume = df['volume'].tail(20).mean() if len(df) >= 20 else df['volume'].mean()
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        # 检测阻力突破
        for resistance in resistance_levels:
            if prev_close < resistance <= current_close:
                if volume_ratio >= 1.5:  # 成交量放大
                    return {
                        "type": "bullish_breakout",
                        "level": resistance,
                        "volume_ratio": volume_ratio,
                        "confirmed": True
                    }
                else:
                    return {
                        "type": "bullish_breakout",
                        "level": resistance,
                        "volume_ratio": volume_ratio,
                        "confirmed": False,
                        "warning": "成交量未放大，可能是假突破"
                    }
        
        # 检测支撑突破
        for support in support_levels:
            if prev_close > support >= current_close:
                if volume_ratio >= 1.5:
                    return {
                        "type": "bearish_breakout",
                        "level": support,
                        "volume_ratio": volume_ratio,
                        "confirmed": True
                    }
                else:
                    return {
                        "type": "bearish_breakout",
                        "level": support,
                        "volume_ratio": volume_ratio,
                        "confirmed": False,
                        "warning": "成交量未放大，可能是假突破"
                    }
        
        return None
    
    def _calculate_entry_sl_tp(
        self, 
        df: pd.DataFrame, 
        direction: int, 
        signal_type: SignalType
    ) -> Tuple[float, float, float, float]:
        """
        计算入场价、止损价、止盈价
        
        Returns:
            (entry_price, stop_loss, take_profit, risk_reward_ratio)
        """
        current_price = df.iloc[-1]['close']
        atr = self.indicators.calculate_atr(df).iloc[-1]
        
        if pd.isna(atr) or atr == 0:
            atr = (df['high'] - df['low']).mean()  # 使用平均波动作为替代
        
        if direction == 1:  # 做多
            entry_price = current_price
            stop_loss = current_price - (atr * self.atr_sl_multiplier)
            risk = entry_price - stop_loss
            take_profit = entry_price + (risk * self.risk_reward_ratio)
        else:  # 做空
            entry_price = current_price
            stop_loss = current_price + (atr * self.atr_sl_multiplier)
            risk = stop_loss - entry_price
            take_profit = entry_price - (risk * self.risk_reward_ratio)
        
        return entry_price, stop_loss, take_profit, self.risk_reward_ratio
    
    def generate_alert(self, df: pd.DataFrame) -> Optional[TradingAlert]:
        """
        生成交易警报
        
        Args:
            df: OHLCV数据
            
        Returns:
            TradingAlert 或 None
        """
        if len(df) < 20:
            logger.debug("数据不足，无法生成警报")
            return None
        
        current_price = df.iloc[-1]['close']
        timestamp = df.index[-1] if isinstance(df.index[-1], datetime) else datetime.now()
        
        # 初始化
        reasons = []
        patterns = []
        confidence = 0.0
        signal_type = SignalType.NO_SIGNAL
        direction = 0
        
        # 1. 计算技术指标
        rsi = self.indicators.calculate_rsi(df)
        current_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50
        atr = self.indicators.calculate_atr(df)
        bb_upper, bb_middle, bb_lower = self.indicators.calculate_bollinger_bands(df)
        
        # 2. K线形态识别
        detected_patterns, pattern_direction = self._identify_patterns(df)
        patterns.extend(detected_patterns)
        
        # 3. 订单流分析
        order_flow_data = self.order_flow.analyze(df)
        
        # 4. RSI背离检测
        rsi_divergence = self.indicators.detect_rsi_divergence(df, rsi)
        
        # 5. 支撑阻力位
        support_levels, resistance_levels = self._identify_support_resistance(df)
        
        # 6. 突破检测
        breakout = self._check_breakout(df, support_levels, resistance_levels)
        
        # ==========================================
        # 信号生成逻辑
        # ==========================================
        
        # A. 反转信号检测
        # 看涨反转条件
        bullish_reversal_score = 0
        bearish_reversal_score = 0
        
        # RSI超卖 + 看涨形态
        if current_rsi < self.rsi_oversold:
            bullish_reversal_score += 0.3
            reasons.append(f"RSI超卖: {current_rsi:.1f}")
            
        if pattern_direction == 1:
            bullish_reversal_score += 0.3
            reasons.append(f"看涨形态: {', '.join(detected_patterns)}")
            
        # 价格触及布林带下轨
        if current_price <= bb_lower.iloc[-1]:
            bullish_reversal_score += 0.2
            reasons.append("价格触及布林带下轨")
            
        # RSI看涨背离
        if rsi_divergence.get("divergence") and rsi_divergence.get("type") == "bullish":
            bullish_reversal_score += 0.3
            reasons.append(rsi_divergence.get("description", "RSI看涨背离"))
            
        # 订单流看涨背离
        if order_flow_data["divergence"].get("divergence") and order_flow_data["divergence"].get("type") == "bullish":
            bullish_reversal_score += 0.2
            reasons.append(order_flow_data["divergence"].get("description", "订单流看涨背离"))
            
        # 订单流不平衡 (买入为主)
        if order_flow_data["imbalance"].get("imbalance") and order_flow_data["imbalance"].get("type") == "bullish":
            bullish_reversal_score += 0.2
            reasons.append(order_flow_data["imbalance"].get("description", "买入量占优"))
        
        # RSI超买 + 看跌形态
        if current_rsi > self.rsi_overbought:
            bearish_reversal_score += 0.3
            reasons.append(f"RSI超买: {current_rsi:.1f}")
            
        if pattern_direction == -1:
            bearish_reversal_score += 0.3
            reasons.append(f"看跌形态: {', '.join(detected_patterns)}")
            
        # 价格触及布林带上轨
        if current_price >= bb_upper.iloc[-1]:
            bearish_reversal_score += 0.2
            reasons.append("价格触及布林带上轨")
            
        # RSI看跌背离
        if rsi_divergence.get("divergence") and rsi_divergence.get("type") == "bearish":
            bearish_reversal_score += 0.3
            reasons.append(rsi_divergence.get("description", "RSI看跌背离"))
            
        # 订单流看跌背离
        if order_flow_data["divergence"].get("divergence") and order_flow_data["divergence"].get("type") == "bearish":
            bearish_reversal_score += 0.2
            reasons.append(order_flow_data["divergence"].get("description", "订单流看跌背离"))
            
        # 订单流不平衡 (卖出为主)
        if order_flow_data["imbalance"].get("imbalance") and order_flow_data["imbalance"].get("type") == "bearish":
            bearish_reversal_score += 0.2
            reasons.append(order_flow_data["imbalance"].get("description", "卖出量占优"))
        
        # B. 突破信号检测
        if breakout:
            if breakout["type"] == "bullish_breakout":
                if breakout.get("confirmed"):
                    signal_type = SignalType.BREAKOUT_BULLISH
                    direction = 1
                    confidence = 0.75
                    reasons.append(f"突破阻力位 {breakout['level']:.2f}，成交量放大 {breakout['volume_ratio']:.2f}x")
                else:
                    # 未确认的突破，降低置信度
                    signal_type = SignalType.BREAKOUT_BULLISH
                    direction = 1
                    confidence = 0.55
                    reasons.append(f"突破阻力位 {breakout['level']:.2f}，但{breakout.get('warning', '未确认')}")
                    
            elif breakout["type"] == "bearish_breakout":
                if breakout.get("confirmed"):
                    signal_type = SignalType.BREAKOUT_BEARISH
                    direction = -1
                    confidence = 0.75
                    reasons.append(f"跌破支撑位 {breakout['level']:.2f}，成交量放大 {breakout['volume_ratio']:.2f}x")
                else:
                    signal_type = SignalType.BREAKOUT_BEARISH
                    direction = -1
                    confidence = 0.55
                    reasons.append(f"跌破支撑位 {breakout['level']:.2f}，但{breakout.get('warning', '未确认')}")
        
        # C. 如果没有突破信号，检查反转信号
        if signal_type == SignalType.NO_SIGNAL:
            if bullish_reversal_score >= 0.5:
                signal_type = SignalType.REVERSAL_BULLISH
                direction = 1
                confidence = min(bullish_reversal_score, 0.9)
                
            elif bearish_reversal_score >= 0.5:
                signal_type = SignalType.REVERSAL_BEARISH
                direction = -1
                confidence = min(bearish_reversal_score, 0.9)
        
        # D. 检查是否达到最小置信度
        if confidence < self.min_confidence or signal_type == SignalType.NO_SIGNAL:
            return None
        
        # 5. 计算入场价、止损、止盈
        entry_price, stop_loss, take_profit, rr_ratio = self._calculate_entry_sl_tp(df, direction, signal_type)
        
        # 6. 创建警报
        alert = TradingAlert(
            timestamp=timestamp,
            instrument=self.instrument,
            signal_type=signal_type,
            direction=direction,
            price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            timeframe=self.timeframe,
            patterns=patterns,
            reasons=reasons,
            order_flow_data=order_flow_data,
            risk_reward_ratio=rr_ratio
        )
        
        # 记录警报
        self.alerts.append(alert)
        
        return alert
    
    def analyze_and_alert(self, df: pd.DataFrame) -> Optional[TradingAlert]:
        """
        分析数据并生成警报 (主入口函数)
        
        Args:
            df: OHLCV数据
            
        Returns:
            TradingAlert 或 None
        """
        try:
            alert = self.generate_alert(df)
            
            if alert:
                logger.info(f"生成交易警报: {alert.signal_type.value} | "
                           f"{self.instrument} | 置信度: {alert.confidence*100:.1f}%")
                print(alert)
                
            return alert
            
        except Exception as e:
            logger.error(f"生成警报时出错: {e}")
            return None
    
    def get_alert_history(self) -> List[TradingAlert]:
        """获取警报历史"""
        return self.alerts
    
    def clear_alerts(self):
        """清空警报历史"""
        self.alerts = []


# ==========================================
# 使用示例和测试
# ==========================================

if __name__ == "__main__":
    import yfinance as yf
    
    logger.info("="*60)
    logger.info("短期交易警报系统测试")
    logger.info("="*60)
    
    # 下载测试数据 (使用NQ期货作为MNQ的近似)
    print("\n下载测试数据...")
    
    # 使用 QQQ ETF 作为 MNQ 的替代测试数据
    ticker = yf.Ticker("QQQ")
    df = ticker.history(period="5d", interval="5m")
    df.columns = df.columns.str.lower()
    
    print(f"数据条数: {len(df)}")
    print(f"最新价格: {df['close'].iloc[-1]:.2f}")
    
    # 初始化策略
    strategy = ShortTermAlertStrategy(
        instrument="MNQ",
        timeframe="5m",
        rsi_oversold=30,
        rsi_overbought=70,
        min_confidence=0.5,  # 测试时降低阈值
        atr_sl_multiplier=2.0,
        risk_reward_ratio=2.0
    )
    
    # 分析并生成警报
    print("\n分析数据中...")
    alert = strategy.analyze_and_alert(df)
    
    if alert:
        print("\n✅ 生成了交易警报!")
    else:
        print("\n❌ 当前没有符合条件的交易信号")
    
    # 显示技术分析摘要
    print("\n" + "="*60)
    print("技术分析摘要")
    print("="*60)
    
    rsi = TechnicalIndicators.calculate_rsi(df)
    atr = TechnicalIndicators.calculate_atr(df)
    bb_upper, bb_middle, bb_lower = TechnicalIndicators.calculate_bollinger_bands(df)
    
    print(f"RSI(14): {rsi.iloc[-1]:.2f}")
    print(f"ATR(14): {atr.iloc[-1]:.2f}")
    print(f"布林带上轨: {bb_upper.iloc[-1]:.2f}")
    print(f"布林带中轨: {bb_middle.iloc[-1]:.2f}")
    print(f"布林带下轨: {bb_lower.iloc[-1]:.2f}")
    
    # 订单流分析
    order_flow = OrderFlowAnalyzer()
    of_data = order_flow.analyze(df)
    
    print(f"\n订单流分析:")
    print(f"  当前Delta: {of_data['current_delta']:.2f}")
    print(f"  累积Delta: {of_data['cumulative_delta']:.2f}")
    print(f"  Delta趋势: {of_data['delta_trend']}")
    print(f"  背离检测: {of_data['divergence']}")
    print(f"  不平衡检测: {of_data['imbalance']}")
