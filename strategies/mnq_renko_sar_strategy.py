"""
MNQ 短线交易策略 (MNQ Short-term Trading Strategy)

策略组合：
1. Renko砖型图过滤 - 过滤市场噪音，识别趋势
2. K线形态识别 - 识别反转和延续形态
3. Parabolic SAR止损 - 动态跟踪止损

适用于：MNQ (Micro E-mini Nasdaq-100) 5分钟/15分钟级别交易
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger


class SignalType(Enum):
    """信号类型"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"


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
    BULLISH_HARAMI = "看涨孕线"
    BEARISH_HARAMI = "看跌孕线"
    TWEEZER_TOP = "镊子顶"
    TWEEZER_BOTTOM = "镊子底"


@dataclass
class Position:
    """持仓信息"""
    direction: int  # 1=多头, -1=空头, 0=无持仓
    entry_price: float  # 开仓价格
    quantity: float  # 持仓数量(合约张数)
    entry_time: datetime  # 开仓时间
    stop_loss: float = 0.0  # 止损价格
    sar_value: float = 0.0  # 当前SAR值
    
    @property
    def is_long(self) -> bool:
        return self.direction == 1
    
    @property
    def is_short(self) -> bool:
        return self.direction == -1
    
    @property
    def is_empty(self) -> bool:
        return self.direction == 0


@dataclass
class Trade:
    """交易记录"""
    trade_id: int
    direction: int  # 1=做多, -1=做空
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    quantity: float
    pnl: float  # 盈亏（$）
    pnl_pct: float  # 盈亏百分比
    exit_reason: str  # 出场原因
    patterns_detected: List[str] = field(default_factory=list)
    
    def __str__(self):
        direction_text = "做多 🟢" if self.direction == 1 else "做空 🔴"
        return (f"Trade #{self.trade_id} | {direction_text} | "
                f"进场: {self.entry_price:.2f} @ {self.entry_time} | "
                f"出场: {self.exit_price:.2f} @ {self.exit_time} | "
                f"盈亏: {self.pnl:+.2f} ({self.pnl_pct:+.2%}) | "
                f"出场原因: {self.exit_reason}")


class ParabolicSAR:
    """
    Parabolic SAR 计算器
    
    SAR = 前一个SAR + AF × (EP - 前一个SAR)
    AF: 加速因子，初始为0.02，每次EP更新时增加0.02，最大为0.2
    EP: 极值点，做多时为最高价，做空时为最低价
    """
    
    def __init__(
        self,
        af_start: float = 0.02,
        af_step: float = 0.02,
        af_max: float = 0.2
    ):
        self.af_start = af_start
        self.af_step = af_step
        self.af_max = af_max
    
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算Parabolic SAR
        
        Args:
            df: 必须包含 high, low, close 列
            
        Returns:
            添加了 sar, sar_direction 列的DataFrame
        """
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        n = len(df)
        
        # 初始化
        sar = np.zeros(n)
        sar_direction = np.zeros(n)  # 1=上升趋势, -1=下降趋势
        af = np.zeros(n)
        ep = np.zeros(n)
        
        # 第一根K线初始化
        sar[0] = low[0]
        sar_direction[0] = 1  # 假设初始为上升趋势
        af[0] = self.af_start
        ep[0] = high[0]
        
        for i in range(1, n):
            # 前一个SAR和方向
            prev_sar = sar[i-1]
            prev_direction = sar_direction[i-1]
            prev_af = af[i-1]
            prev_ep = ep[i-1]
            
            # 计算新SAR
            new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
            
            # 上升趋势
            if prev_direction == 1:
                # SAR不能高于前两个低点
                if i >= 2:
                    new_sar = min(new_sar, low[i-1], low[i-2])
                else:
                    new_sar = min(new_sar, low[i-1])
                
                # 检查是否触发反转
                if low[i] < new_sar:
                    # 反转为下降趋势
                    sar_direction[i] = -1
                    sar[i] = prev_ep  # 使用前一个EP作为新SAR
                    af[i] = self.af_start
                    ep[i] = low[i]
                else:
                    sar_direction[i] = 1
                    sar[i] = new_sar
                    
                    # 更新EP和AF
                    if high[i] > prev_ep:
                        ep[i] = high[i]
                        af[i] = min(prev_af + self.af_step, self.af_max)
                    else:
                        ep[i] = prev_ep
                        af[i] = prev_af
            
            # 下降趋势
            else:
                # SAR不能低于前两个高点
                if i >= 2:
                    new_sar = max(new_sar, high[i-1], high[i-2])
                else:
                    new_sar = max(new_sar, high[i-1])
                
                # 检查是否触发反转
                if high[i] > new_sar:
                    # 反转为上升趋势
                    sar_direction[i] = 1
                    sar[i] = prev_ep  # 使用前一个EP作为新SAR
                    af[i] = self.af_start
                    ep[i] = high[i]
                else:
                    sar_direction[i] = -1
                    sar[i] = new_sar
                    
                    # 更新EP和AF
                    if low[i] < prev_ep:
                        ep[i] = low[i]
                        af[i] = min(prev_af + self.af_step, self.af_max)
                    else:
                        ep[i] = prev_ep
                        af[i] = prev_af
        
        result = df.copy()
        result['sar'] = sar
        result['sar_direction'] = sar_direction
        result['sar_af'] = af
        result['sar_ep'] = ep
        
        return result


class CandlestickPatterns:
    """K线形态识别器"""
    
    @staticmethod
    def body_size(candle: pd.Series) -> float:
        """计算实体大小"""
        return abs(candle['close'] - candle['open'])
    
    @staticmethod
    def is_bullish(candle: pd.Series) -> bool:
        """是否为阳线"""
        return candle['close'] > candle['open']
    
    @staticmethod
    def is_bearish(candle: pd.Series) -> bool:
        """是否为阴线"""
        return candle['close'] < candle['open']
    
    @staticmethod
    def upper_shadow(candle: pd.Series) -> float:
        """计算上影线长度"""
        return candle['high'] - max(candle['open'], candle['close'])
    
    @staticmethod
    def lower_shadow(candle: pd.Series) -> float:
        """计算下影线长度"""
        return min(candle['open'], candle['close']) - candle['low']
    
    @staticmethod
    def range_size(candle: pd.Series) -> float:
        """计算K线范围"""
        return candle['high'] - candle['low']
    
    @classmethod
    def is_doji(cls, candle: pd.Series, threshold: float = 0.1) -> bool:
        """检测十字星"""
        body = cls.body_size(candle)
        range_hl = cls.range_size(candle)
        return body <= range_hl * threshold if range_hl > 0 else False
    
    @classmethod
    def is_hammer(cls, candle: pd.Series, df: pd.DataFrame, idx: int) -> bool:
        """
        检测锤子线
        条件：
        1. 实体小于整体范围的1/3
        2. 下影线至少是实体的2倍
        3. 上影线很小
        4. 处于下跌趋势中
        """
        body = cls.body_size(candle)
        range_hl = cls.range_size(candle)
        
        if range_hl == 0:
            return False
        
        # 实体小于整体范围的1/3
        if body > range_hl * 0.35:
            return False
        
        # 下影线至少是实体的2倍
        lower = cls.lower_shadow(candle)
        if body > 0 and lower < body * 2:
            return False
        
        # 上影线很小
        upper = cls.upper_shadow(candle)
        if upper > body * 0.5:
            return False
        
        # 检查前面是下跌趋势: 前3根K线的平均 > 前1根K线
        if idx >= 3:
            earlier_avg = df['close'].iloc[idx-3:idx-1].mean()  # 前3、前2根的平均
            recent_close = df['close'].iloc[idx-1]  # 前1根
            if recent_close >= earlier_avg:
                return False
        
        return True
    
    @classmethod
    def is_inverted_hammer(cls, candle: pd.Series, df: pd.DataFrame, idx: int) -> bool:
        """
        检测倒锤子
        条件：
        1. 实体小于整体范围的1/3
        2. 上影线至少是实体的2倍
        3. 下影线很小
        4. 处于下跌趋势中
        """
        body = cls.body_size(candle)
        range_hl = cls.range_size(candle)
        
        if range_hl == 0:
            return False
        
        # 实体小于整体范围的1/3
        if body > range_hl * 0.35:
            return False
        
        # 上影线至少是实体的2倍
        upper = cls.upper_shadow(candle)
        if body > 0 and upper < body * 2:
            return False
        
        # 下影线很小
        lower = cls.lower_shadow(candle)
        if lower > body * 0.5:
            return False
        
        # 检查前面是下跌趋势: 前3根K线的平均 > 前1根K线
        if idx >= 3:
            earlier_avg = df['close'].iloc[idx-3:idx-1].mean()  # 前3、前2根的平均
            recent_close = df['close'].iloc[idx-1]  # 前1根
            if recent_close >= earlier_avg:
                return False
        
        return True
    
    @classmethod
    def is_bullish_engulfing(cls, current: pd.Series, prev: pd.Series) -> bool:
        """
        检测看涨吞没
        条件：
        1. 前一根是阴线
        2. 当前是阳线
        3. 当前实体完全包裹前一根实体
        """
        # 前一根是阴线
        if not cls.is_bearish(prev):
            return False
        
        # 当前是阳线
        if not cls.is_bullish(current):
            return False
        
        # 当前实体完全包裹前一根实体
        curr_body_high = current['close']
        curr_body_low = current['open']
        prev_body_high = prev['open']
        prev_body_low = prev['close']
        
        return curr_body_high > prev_body_high and curr_body_low < prev_body_low
    
    @classmethod
    def is_bearish_engulfing(cls, current: pd.Series, prev: pd.Series) -> bool:
        """
        检测看跌吞没
        条件：
        1. 前一根是阳线
        2. 当前是阴线
        3. 当前实体完全包裹前一根实体
        """
        # 前一根是阳线
        if not cls.is_bullish(prev):
            return False
        
        # 当前是阴线
        if not cls.is_bearish(current):
            return False
        
        # 当前实体完全包裹前一根实体
        curr_body_high = current['open']
        curr_body_low = current['close']
        prev_body_high = prev['close']
        prev_body_low = prev['open']
        
        return curr_body_high > prev_body_high and curr_body_low < prev_body_low
    
    @classmethod
    def is_morning_star(cls, candles: pd.DataFrame) -> bool:
        """
        检测早晨之星 (需要最近3根K线)
        """
        if len(candles) < 3:
            return False
        
        first = candles.iloc[-3]
        second = candles.iloc[-2]
        third = candles.iloc[-1]
        
        # 第一根是长阴线
        if not cls.is_bearish(first):
            return False
        first_body = cls.body_size(first)
        first_range = cls.range_size(first)
        if first_range > 0 and first_body < first_range * 0.5:
            return False
        
        # 第二根是小实体 (十字星或小K线)
        second_body = cls.body_size(second)
        if second_body > first_body * 0.3:
            return False
        
        # 第三根是长阳线，收盘价高于第一根实体中点
        if not cls.is_bullish(third):
            return False
        
        first_midpoint = (first['open'] + first['close']) / 2
        return third['close'] > first_midpoint
    
    @classmethod
    def is_evening_star(cls, candles: pd.DataFrame) -> bool:
        """
        检测黄昏之星 (需要最近3根K线)
        """
        if len(candles) < 3:
            return False
        
        first = candles.iloc[-3]
        second = candles.iloc[-2]
        third = candles.iloc[-1]
        
        # 第一根是长阳线
        if not cls.is_bullish(first):
            return False
        first_body = cls.body_size(first)
        first_range = cls.range_size(first)
        if first_range > 0 and first_body < first_range * 0.5:
            return False
        
        # 第二根是小实体 (十字星或小K线)
        second_body = cls.body_size(second)
        if second_body > first_body * 0.3:
            return False
        
        # 第三根是长阴线，收盘价低于第一根实体中点
        if not cls.is_bearish(third):
            return False
        
        first_midpoint = (first['open'] + first['close']) / 2
        return third['close'] < first_midpoint
    
    @classmethod
    def is_three_white_soldiers(cls, candles: pd.DataFrame) -> bool:
        """检测三白兵"""
        if len(candles) < 3:
            return False
        
        for i in range(-3, 0):
            candle = candles.iloc[i]
            if not cls.is_bullish(candle):
                return False
            # 每根收盘价高于前一根
            if i > -3 and candle['close'] <= candles.iloc[i-1]['close']:
                return False
            # 开盘价在前一根实体内
            if i > -3:
                prev_body_low = candles.iloc[i-1]['open']
                prev_body_high = candles.iloc[i-1]['close']
                if not (prev_body_low <= candle['open'] <= prev_body_high):
                    return False
        
        return True
    
    @classmethod
    def is_three_black_crows(cls, candles: pd.DataFrame) -> bool:
        """检测三乌鸦"""
        if len(candles) < 3:
            return False
        
        for i in range(-3, 0):
            candle = candles.iloc[i]
            if not cls.is_bearish(candle):
                return False
            # 每根收盘价低于前一根
            if i > -3 and candle['close'] >= candles.iloc[i-1]['close']:
                return False
            # 开盘价在前一根实体内
            if i > -3:
                prev_body_low = candles.iloc[i-1]['close']
                prev_body_high = candles.iloc[i-1]['open']
                if not (prev_body_low <= candle['open'] <= prev_body_high):
                    return False
        
        return True
    
    @classmethod
    def detect_patterns(cls, df: pd.DataFrame, idx: int) -> List[Tuple[PatternType, int]]:
        """
        检测当前位置的K线形态
        
        Returns:
            List of (PatternType, direction) where direction is 1=bullish, -1=bearish
        """
        patterns = []
        
        if idx < 2:
            return patterns
        
        current = df.iloc[idx]
        prev = df.iloc[idx-1]
        candles_3 = df.iloc[max(0, idx-2):idx+1]
        
        # 单K线形态
        if cls.is_doji(current):
            patterns.append((PatternType.DOJI, 0))  # 中性信号
        
        if cls.is_hammer(current, df, idx):
            patterns.append((PatternType.HAMMER, 1))
        
        if cls.is_inverted_hammer(current, df, idx):
            patterns.append((PatternType.INVERTED_HAMMER, 1))
        
        # 双K线形态
        if cls.is_bullish_engulfing(current, prev):
            patterns.append((PatternType.BULLISH_ENGULFING, 1))
        
        if cls.is_bearish_engulfing(current, prev):
            patterns.append((PatternType.BEARISH_ENGULFING, -1))
        
        # 三K线形态
        if len(candles_3) >= 3:
            if cls.is_morning_star(candles_3):
                patterns.append((PatternType.MORNING_STAR, 1))
            
            if cls.is_evening_star(candles_3):
                patterns.append((PatternType.EVENING_STAR, -1))
            
            if cls.is_three_white_soldiers(candles_3):
                patterns.append((PatternType.THREE_WHITE_SOLDIERS, 1))
            
            if cls.is_three_black_crows(candles_3):
                patterns.append((PatternType.THREE_BLACK_CROWS, -1))
        
        return patterns


class MNQRenkoSARStrategy:
    """
    MNQ 砖型图 + K线形态 + SAR止损 综合策略
    
    入场逻辑：
    1. Renko砖型图确认趋势方向（连续2个同向砖块）
    2. K线形态确认入场信号
    3. SAR方向与趋势一致
    
    出场逻辑：
    1. SAR反转触发止损
    2. Renko趋势反转
    3. 固定止盈目标
    """
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission_per_contract: float = 2.0,  # MNQ每合约手续费
        tick_value: float = 0.50,  # MNQ每跳价值
        tick_size: float = 0.25,  # MNQ最小变动
        contracts_per_trade: int = 1,  # 每笔交易合约数
        sar_af_start: float = 0.02,
        sar_af_step: float = 0.02,
        sar_af_max: float = 0.2,
        renko_brick_size: float = 10.0,  # MNQ砖块大小(点)
        risk_reward_ratio: float = 2.0,  # 风险回报比
        max_daily_loss: float = 300.0,  # 每日最大亏损
        use_pattern_filter: bool = True,  # 使用K线形态过滤
        min_renko_bricks: int = 2,  # 最小确认砖块数
    ):
        """初始化策略"""
        self.initial_capital = initial_capital
        self.commission_per_contract = commission_per_contract
        self.tick_value = tick_value
        self.tick_size = tick_size
        self.contracts_per_trade = contracts_per_trade
        
        # SAR参数
        self.sar_af_start = sar_af_start
        self.sar_af_step = sar_af_step
        self.sar_af_max = sar_af_max
        
        # Renko参数
        self.renko_brick_size = renko_brick_size
        
        # 风险管理
        self.risk_reward_ratio = risk_reward_ratio
        self.max_daily_loss = max_daily_loss
        
        # 策略参数
        self.use_pattern_filter = use_pattern_filter
        self.min_renko_bricks = min_renko_bricks
        
        # SAR计算器
        self.sar_calculator = ParabolicSAR(
            af_start=sar_af_start,
            af_step=sar_af_step,
            af_max=sar_af_max
        )
        
        # 形态识别器
        self.pattern_detector = CandlestickPatterns()
        
        # 账户状态
        self.balance = initial_capital
        self.equity = initial_capital
        
        # 持仓
        self.position = Position(
            direction=0,
            entry_price=0.0,
            quantity=0.0,
            entry_time=None
        )
        
        # 交易记录
        self.trades: List[Trade] = []
        self.trade_counter = 0
        
        # 统计
        self.max_equity = initial_capital
        self.max_drawdown = 0.0
        self.daily_pnl = 0.0
        self.total_commission = 0.0
        
        # Renko状态
        self.renko_trend = 0  # 1=上涨, -1=下跌, 0=未确定
        self.renko_brick_count = 0
        self.last_brick_direction = 0
        
        logger.info(f"初始化MNQ策略: 本金=${initial_capital}, "
                   f"砖块={renko_brick_size}点, SAR={sar_af_start}/{sar_af_step}/{sar_af_max}")
    
    def _calculate_renko_trend(self, df: pd.DataFrame, brick_size: float) -> Tuple[int, int]:
        """
        基于收盘价计算Renko趋势
        
        Returns:
            (trend_direction, consecutive_bricks)
        """
        if len(df) < 2:
            return 0, 0
        
        # 简化的Renko计算
        prices = df['close'].values
        current_brick = prices[0]
        brick_directions = []
        
        for price in prices[1:]:
            while True:
                if price >= current_brick + brick_size:
                    brick_directions.append(1)
                    current_brick += brick_size
                elif price <= current_brick - brick_size:
                    brick_directions.append(-1)
                    current_brick -= brick_size
                else:
                    break
        
        if not brick_directions:
            return 0, 0
        
        # 计算连续同向砖块
        last_direction = brick_directions[-1]
        count = 0
        for d in reversed(brick_directions):
            if d == last_direction:
                count += 1
            else:
                break
        
        return last_direction, count
    
    def _should_enter(
        self, 
        df: pd.DataFrame, 
        idx: int, 
        sar_direction: int,
        patterns: List[Tuple[PatternType, int]]
    ) -> Tuple[bool, int, str]:
        """
        判断是否应该入场
        
        Returns:
            (should_enter, direction, reason)
        """
        if self.position.direction != 0:
            return False, 0, "已有持仓"
        
        # 计算Renko趋势
        lookback = min(100, idx + 1)
        renko_trend, brick_count = self._calculate_renko_trend(
            df.iloc[idx-lookback+1:idx+1], 
            self.renko_brick_size
        )
        
        # 检查Renko趋势确认
        if brick_count < self.min_renko_bricks:
            return False, 0, f"Renko趋势未确认({brick_count}块)"
        
        # 检查SAR方向
        if renko_trend != sar_direction:
            return False, 0, "SAR与Renko方向不一致"
        
        # K线形态过滤
        if self.use_pattern_filter:
            # 寻找同向的形态确认
            pattern_confirmed = False
            for pattern, p_direction in patterns:
                if p_direction == renko_trend:
                    pattern_confirmed = True
                    break
            
            if not pattern_confirmed:
                return False, 0, "无K线形态确认"
        
        reason = f"Renko={renko_trend}, SAR={sar_direction}, 砖块数={brick_count}"
        if patterns:
            reason += f", 形态={[p[0].value for p in patterns]}"
        
        return True, renko_trend, reason
    
    def _should_exit(
        self, 
        current_price: float, 
        sar_value: float, 
        sar_direction: int
    ) -> Tuple[bool, str]:
        """
        判断是否应该出场
        
        Returns:
            (should_exit, reason)
        """
        if self.position.direction == 0:
            return False, ""
        
        # SAR止损检查
        if self.position.is_long:
            # 多头：价格跌破SAR
            if current_price < sar_value:
                return True, "SAR止损触发"
            # SAR反转
            if sar_direction == -1:
                return True, "SAR反转"
        else:
            # 空头：价格突破SAR
            if current_price > sar_value:
                return True, "SAR止损触发"
            # SAR反转
            if sar_direction == 1:
                return True, "SAR反转"
        
        return False, ""
    
    def _open_position(
        self, 
        direction: int, 
        price: float, 
        timestamp: datetime,
        sar_value: float,
        patterns: List[str]
    ) -> None:
        """开仓"""
        # 计算手续费
        commission = self.commission_per_contract * self.contracts_per_trade
        self.total_commission += commission
        
        # 计算初始止损
        if direction == 1:
            stop_loss = sar_value
        else:
            stop_loss = sar_value
        
        # 更新持仓
        self.position = Position(
            direction=direction,
            entry_price=price,
            quantity=self.contracts_per_trade,
            entry_time=timestamp,
            stop_loss=stop_loss,
            sar_value=sar_value
        )
        
        # 扣除手续费
        self.balance -= commission
        
        direction_text = "做多 🟢" if direction == 1 else "做空 🔴"
        logger.debug(f"开仓 | {direction_text} | "
                    f"价格: {price:.2f} | "
                    f"合约: {self.contracts_per_trade} | "
                    f"SAR止损: {stop_loss:.2f} | "
                    f"形态: {patterns}")
    
    def _close_position(
        self, 
        price: float, 
        timestamp: datetime,
        exit_reason: str,
        patterns: List[str] = None
    ) -> Trade:
        """平仓"""
        if self.position.direction == 0:
            return None
        
        # 计算手续费
        commission = self.commission_per_contract * self.contracts_per_trade
        self.total_commission += commission
        
        # 计算盈亏（点数 × 每点价值 × 合约数）
        if self.position.is_long:
            points_pnl = (price - self.position.entry_price) / self.tick_size
        else:
            points_pnl = (self.position.entry_price - price) / self.tick_size
        
        dollar_pnl = points_pnl * self.tick_value * self.position.quantity
        net_pnl = dollar_pnl - commission
        
        # 计算盈亏百分比
        entry_value = self.position.entry_price * self.position.quantity
        pnl_pct = net_pnl / self.initial_capital if self.initial_capital > 0 else 0
        
        # 更新余额
        self.balance += net_pnl
        self.daily_pnl += net_pnl
        
        # 创建交易记录
        self.trade_counter += 1
        trade = Trade(
            trade_id=self.trade_counter,
            direction=self.position.direction,
            entry_time=self.position.entry_time,
            entry_price=self.position.entry_price,
            exit_time=timestamp,
            exit_price=price,
            quantity=self.position.quantity,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            patterns_detected=patterns or []
        )
        
        self.trades.append(trade)
        
        direction_text = "做多 🟢" if self.position.is_long else "做空 🔴"
        logger.info(f"平仓 | {direction_text} | "
                   f"进场: {self.position.entry_price:.2f} → 出场: {price:.2f} | "
                   f"盈亏: {net_pnl:+.2f} ({pnl_pct:+.2%}) | "
                   f"原因: {exit_reason}")
        
        # 清空持仓
        self.position = Position(
            direction=0,
            entry_price=0.0,
            quantity=0.0,
            entry_time=None
        )
        
        return trade
    
    def _update_equity(self, current_price: float) -> None:
        """更新权益"""
        if self.position.direction == 0:
            self.equity = self.balance
        else:
            # 计算浮动盈亏
            if self.position.is_long:
                points_pnl = (current_price - self.position.entry_price) / self.tick_size
            else:
                points_pnl = (self.position.entry_price - current_price) / self.tick_size
            
            unrealized_pnl = points_pnl * self.tick_value * self.position.quantity
            self.equity = self.balance + unrealized_pnl
        
        # 更新最大权益和回撤
        if self.equity > self.max_equity:
            self.max_equity = self.equity
        
        drawdown = (self.max_equity - self.equity) / self.max_equity if self.max_equity > 0 else 0
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """
        运行回测
        
        Args:
            df: OHLCV数据，必须包含 open, high, low, close, volume 列
            
        Returns:
            回测统计结果
        """
        logger.info("="*60)
        logger.info("开始MNQ Renko+SAR策略回测")
        logger.info("="*60)
        
        # 计算SAR
        df_with_sar = self.sar_calculator.calculate(df)
        
        # 遍历每根K线
        for idx in range(20, len(df_with_sar)):  # 跳过前20根用于指标计算
            candle = df_with_sar.iloc[idx]
            timestamp = candle.name if isinstance(candle.name, datetime) else df_with_sar.index[idx]
            current_price = candle['close']
            sar_value = candle['sar']
            sar_direction = int(candle['sar_direction'])
            
            # 检测K线形态
            patterns = self.pattern_detector.detect_patterns(df_with_sar, idx)
            pattern_names = [p[0].value for p in patterns]
            
            # 检查是否应该出场
            if self.position.direction != 0:
                should_exit, exit_reason = self._should_exit(current_price, sar_value, sar_direction)
                if should_exit:
                    self._close_position(current_price, timestamp, exit_reason, pattern_names)
            
            # 检查是否应该入场
            if self.position.direction == 0:
                should_enter, direction, reason = self._should_enter(
                    df_with_sar, idx, sar_direction, patterns
                )
                if should_enter:
                    self._open_position(direction, current_price, timestamp, sar_value, pattern_names)
            
            # 更新SAR止损
            if self.position.direction != 0:
                self.position.sar_value = sar_value
            
            # 更新权益
            self._update_equity(current_price)
        
        # 如果最后还有持仓，平仓
        if self.position.direction != 0:
            last_candle = df_with_sar.iloc[-1]
            timestamp = last_candle.name if isinstance(last_candle.name, datetime) else df_with_sar.index[-1]
            self._close_position(last_candle['close'], timestamp, "回测结束平仓")
        
        # 计算统计结果
        stats = self._calculate_statistics()
        
        logger.info("="*60)
        logger.info("回测完成")
        logger.info("="*60)
        
        return stats
    
    def _calculate_statistics(self) -> Dict:
        """计算回测统计数据"""
        if not self.trades:
            return {
                'total_trades': 0,
                'final_balance': self.balance,
                'total_return': 0.0,
                'total_return_pct': 0.0,
                'win_rate': 0.0,
                'max_drawdown': 0.0
            }
        
        # 基础统计
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_trades if total_trades > 0 else 0
        
        # 盈亏统计
        total_pnl = sum(t.pnl for t in self.trades)
        total_return_pct = (self.balance - self.initial_capital) / self.initial_capital
        
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        # 盈亏比
        if losing_trades and sum(t.pnl for t in losing_trades) != 0:
            profit_factor = abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades))
        else:
            profit_factor = float('inf') if winning_trades else 0
        
        # 期望值
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss) if total_trades > 0 else 0
        
        # 最大连续盈利/亏损
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0
        
        for trade in self.trades:
            if trade.pnl > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
        
        stats = {
            'initial_capital': self.initial_capital,
            'final_balance': self.balance,
            'total_return': total_pnl,
            'total_return_pct': total_return_pct,
            'max_equity': self.max_equity,
            'max_drawdown': self.max_drawdown,
            'total_trades': total_trades,
            'winning_trades': win_count,
            'losing_trades': loss_count,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses,
            'total_commission': self.total_commission,
            'trades': self.trades
        }
        
        return stats
    
    def print_statistics(self, stats: Dict) -> None:
        """打印统计结果"""
        print("\n" + "="*60)
        print("📊 MNQ Renko+SAR策略回测统计")
        print("="*60)
        
        print(f"\n💰 资金情况:")
        print(f"  初始资金: ${stats['initial_capital']:,.2f}")
        print(f"  最终余额: ${stats['final_balance']:,.2f}")
        print(f"  总盈亏: ${stats['total_return']:+,.2f}")
        print(f"  总收益率: {stats['total_return_pct']:+.2%}")
        print(f"  最大权益: ${stats['max_equity']:,.2f}")
        print(f"  最大回撤: {stats['max_drawdown']:.2%}")
        print(f"  总手续费: ${stats['total_commission']:,.2f}")
        
        print(f"\n📈 交易统计:")
        print(f"  总交易次数: {stats['total_trades']}")
        print(f"  盈利次数: {stats['winning_trades']} ({stats['win_rate']:.2%})")
        print(f"  亏损次数: {stats['losing_trades']}")
        print(f"  平均盈利: ${stats['avg_win']:+.2f}")
        print(f"  平均亏损: ${stats['avg_loss']:+.2f}")
        print(f"  盈亏比: {stats['profit_factor']:.2f}")
        print(f"  期望值: ${stats['expectancy']:+.2f}")
        print(f"  最大连续盈利: {stats['max_consecutive_wins']}")
        print(f"  最大连续亏损: {stats['max_consecutive_losses']}")
        
        print("="*60)
    
    def print_trades(self, max_trades: int = None) -> None:
        """打印交易记录"""
        if not self.trades:
            print("无交易记录")
            return
        
        print("\n" + "="*60)
        print("📝 详细交易记录")
        print("="*60)
        
        trades_to_print = self.trades if max_trades is None else self.trades[:max_trades]
        for trade in trades_to_print:
            print(str(trade))
        
        if max_trades and len(self.trades) > max_trades:
            print(f"... 还有 {len(self.trades) - max_trades} 笔交易未显示")
        
        print("="*60)


def get_strategy_params() -> Dict:
    """获取策略默认参数"""
    return {
        'initial_capital': 10000.0,
        'commission_per_contract': 2.0,
        'tick_value': 0.50,
        'tick_size': 0.25,
        'contracts_per_trade': 1,
        'sar_af_start': 0.02,
        'sar_af_step': 0.02,
        'sar_af_max': 0.2,
        'renko_brick_size': 10.0,
        'risk_reward_ratio': 2.0,
        'max_daily_loss': 300.0,
        'use_pattern_filter': True,
        'min_renko_bricks': 2
    }


if __name__ == "__main__":
    # 测试代码
    import yfinance as yf
    
    print("下载NQ期货数据 (使用QQQ ETF作为代理)...")
    ticker = yf.Ticker("QQQ")
    df = ticker.history(period="30d", interval="5m")
    df.columns = df.columns.str.lower()
    
    # 模拟MNQ价格 (放大100倍)
    df['open'] = df['open'] * 100
    df['high'] = df['high'] * 100
    df['low'] = df['low'] * 100
    df['close'] = df['close'] * 100
    
    print(f"数据条数: {len(df)}")
    print(f"价格范围: {df['low'].min():.2f} - {df['high'].max():.2f}")
    
    # 初始化策略
    strategy = MNQRenkoSARStrategy(
        initial_capital=10000.0,
        renko_brick_size=10.0,
        sar_af_start=0.02,
        sar_af_step=0.02,
        sar_af_max=0.2,
        use_pattern_filter=True,
        min_renko_bricks=2
    )
    
    # 运行回测
    stats = strategy.run_backtest(df)
    
    # 打印结果
    strategy.print_statistics(stats)
    strategy.print_trades(max_trades=10)
