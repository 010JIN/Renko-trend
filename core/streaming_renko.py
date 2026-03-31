"""
流式砖型图构建器 (Streaming Renko Builder)

实现逐根K线推送，动态构建砖块的真实回测逻辑。
解决传统回测的"未来窥视"问题。

关键特性：
1. 逐根K线推送，动态形成砖块
2. 砖块完成后才产生信号
3. 实际入场价格使用砖块完成后的下一根K线开盘价
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class RenkoBrick:
    """单个砖块数据"""
    brick_num: int
    brick_open: float
    brick_close: float
    brick_high: float
    brick_low: float
    direction: int  # 1=上涨, -1=下跌
    completed_at: datetime  # 砖块完成时间
    completed_price: float  # 触发砖块完成的价格
    volume: float = 0.0


class StreamingRenkoBuilder:
    """
    流式砖型图构建器
    
    与传统RenkoBuilder不同，此构建器支持：
    1. 逐根K线推送 (push_candle)
    2. 实时判断是否形成新砖块
    3. 记录砖块完成时的精确价格和时间
    """
    
    def __init__(
        self,
        brick_size: float = 10.0,
        use_wicks: bool = False
    ):
        """
        初始化流式砖型图构建器
        
        Args:
            brick_size: 砖块大小（点数）
            use_wicks: 是否使用影线（使用最高/最低价而非收盘价）
        """
        self.brick_size = brick_size
        self.use_wicks = use_wicks
        
        # 当前砖块基准价格
        self.current_brick_close: Optional[float] = None
        self.current_direction: int = 0  # 0=未确定
        
        # 已完成的砖块列表
        self.bricks: List[RenkoBrick] = []
        self.brick_counter = 0
        
        # 累计成交量
        self.volume_accumulated = 0.0
        
        # 新砖块标志（供外部检查）
        self._new_bricks_this_push: List[RenkoBrick] = []
        
        logger.info(f"初始化流式砖型图: brick_size={brick_size}, use_wicks={use_wicks}")
    
    def reset(self) -> None:
        """重置构建器状态"""
        self.current_brick_close = None
        self.current_direction = 0
        self.bricks = []
        self.brick_counter = 0
        self.volume_accumulated = 0.0
        self._new_bricks_this_push = []
    
    def push_candle(
        self,
        timestamp: datetime,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        volume: float = 0.0
    ) -> List[RenkoBrick]:
        """
        推送一根新K线，检查是否形成新砖块
        
        这是核心方法：
        - 使用当前K线的价格检查是否触发新砖块
        - 如果触发，记录砖块完成时的精确价格
        - 返回本次推送形成的新砖块列表
        
        Args:
            timestamp: K线时间戳
            open_price: 开盘价
            high_price: 最高价
            low_price: 最低价
            close_price: 收盘价
            volume: 成交量
            
        Returns:
            本次推送形成的新砖块列表（可能为空，或多个）
        """
        # 初始化基准价格
        if self.current_brick_close is None:
            self.current_brick_close = close_price
            self.volume_accumulated = volume
            return []
        
        # 根据设置选择使用的价格
        if self.use_wicks:
            price_high = high_price
            price_low = low_price
        else:
            price_high = close_price
            price_low = close_price
        
        self.volume_accumulated += volume
        self._new_bricks_this_push = []
        
        # 检查是否形成新砖块（可能一次形成多个）
        while True:
            # 向上砖块检查
            if price_high >= self.current_brick_close + self.brick_size:
                self.brick_counter += 1
                new_brick = RenkoBrick(
                    brick_num=self.brick_counter,
                    brick_open=self.current_brick_close,
                    brick_close=self.current_brick_close + self.brick_size,
                    brick_high=self.current_brick_close + self.brick_size,
                    brick_low=self.current_brick_close,
                    direction=1,
                    completed_at=timestamp,
                    completed_price=self.current_brick_close + self.brick_size,  # 触发价格
                    volume=self.volume_accumulated
                )
                self.bricks.append(new_brick)
                self._new_bricks_this_push.append(new_brick)
                
                self.current_brick_close += self.brick_size
                self.current_direction = 1
                self.volume_accumulated = 0.0
                
            # 向下砖块检查
            elif price_low <= self.current_brick_close - self.brick_size:
                self.brick_counter += 1
                new_brick = RenkoBrick(
                    brick_num=self.brick_counter,
                    brick_open=self.current_brick_close,
                    brick_close=self.current_brick_close - self.brick_size,
                    brick_high=self.current_brick_close,
                    brick_low=self.current_brick_close - self.brick_size,
                    direction=-1,
                    completed_at=timestamp,
                    completed_price=self.current_brick_close - self.brick_size,  # 触发价格
                    volume=self.volume_accumulated
                )
                self.bricks.append(new_brick)
                self._new_bricks_this_push.append(new_brick)
                
                self.current_brick_close -= self.brick_size
                self.current_direction = -1
                self.volume_accumulated = 0.0
                
            else:
                # 未形成新砖块，退出
                break
        
        return self._new_bricks_this_push
    
    def get_last_n_bricks(self, n: int) -> List[RenkoBrick]:
        """获取最近n个砖块"""
        return self.bricks[-n:] if len(self.bricks) >= n else self.bricks[:]
    
    def get_current_trend(self, lookback: int = 2) -> int:
        """
        获取当前趋势方向
        
        Args:
            lookback: 回溯砖块数量
            
        Returns:
            1=上涨趋势, -1=下跌趋势, 0=无趋势/数据不足
        """
        if len(self.bricks) < lookback:
            return 0
        
        recent_bricks = self.get_last_n_bricks(lookback)
        directions = [b.direction for b in recent_bricks]
        
        # 所有砖块同向才算确认趋势
        if all(d == 1 for d in directions):
            return 1
        elif all(d == -1 for d in directions):
            return -1
        else:
            return 0
    
    def is_trend_reversal(self) -> Tuple[bool, int]:
        """
        检查是否发生趋势反转
        
        Returns:
            (是否反转, 新趋势方向)
        """
        if len(self.bricks) < 2:
            return False, 0
        
        current = self.bricks[-1].direction
        previous = self.bricks[-2].direction
        
        if current != previous:
            return True, current
        
        return False, 0
    
    def to_dataframe(self) -> pd.DataFrame:
        """将砖块转换为DataFrame"""
        if not self.bricks:
            return pd.DataFrame()
        
        data = []
        for brick in self.bricks:
            data.append({
                'brick_num': brick.brick_num,
                'brick_open': brick.brick_open,
                'brick_close': brick.brick_close,
                'brick_high': brick.brick_high,
                'brick_low': brick.brick_low,
                'direction': brick.direction,
                'timestamp': brick.completed_at,
                'completed_price': brick.completed_price,
                'volume': brick.volume
            })
        
        return pd.DataFrame(data)


class StreamingParabolicSAR:
    """
    流式Parabolic SAR计算器
    
    逐根K线更新SAR值，无需预先计算所有数据
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
        
        # SAR状态
        self.sar: Optional[float] = None
        self.sar_direction: int = 1  # 1=上升趋势, -1=下降趋势
        self.af: float = af_start
        self.ep: Optional[float] = None  # 极值点
        
        # 历史数据（用于调整SAR）
        self.prev_high: Optional[float] = None
        self.prev_low: Optional[float] = None
        self.prev_prev_high: Optional[float] = None
        self.prev_prev_low: Optional[float] = None
    
    def reset(self) -> None:
        """重置SAR状态"""
        self.sar = None
        self.sar_direction = 1
        self.af = self.af_start
        self.ep = None
        self.prev_high = None
        self.prev_low = None
        self.prev_prev_high = None
        self.prev_prev_low = None
    
    def update(
        self,
        high: float,
        low: float,
        close: float
    ) -> Tuple[float, int]:
        """
        推送新K线，更新SAR
        
        Args:
            high: 最高价
            low: 最低价
            close: 收盘价
            
        Returns:
            (SAR值, SAR方向)
        """
        # 初始化
        if self.sar is None:
            self.sar = low
            self.ep = high
            self.sar_direction = 1
            self.prev_high = high
            self.prev_low = low
            return self.sar, self.sar_direction
        
        # 保存前一个SAR
        prev_sar = self.sar
        
        # 计算新SAR
        new_sar = prev_sar + self.af * (self.ep - prev_sar)
        
        # 根据趋势方向调整
        if self.sar_direction == 1:  # 上升趋势
            # SAR不能高于前两个低点
            if self.prev_low is not None:
                new_sar = min(new_sar, self.prev_low)
            if self.prev_prev_low is not None:
                new_sar = min(new_sar, self.prev_prev_low)
            
            # 检查反转
            if low < new_sar:
                # 反转为下降趋势
                self.sar_direction = -1
                new_sar = self.ep
                self.af = self.af_start
                self.ep = low
            else:
                # 更新EP和AF
                if high > self.ep:
                    self.ep = high
                    self.af = min(self.af + self.af_step, self.af_max)
        
        else:  # 下降趋势
            # SAR不能低于前两个高点
            if self.prev_high is not None:
                new_sar = max(new_sar, self.prev_high)
            if self.prev_prev_high is not None:
                new_sar = max(new_sar, self.prev_prev_high)
            
            # 检查反转
            if high > new_sar:
                # 反转为上升趋势
                self.sar_direction = 1
                new_sar = self.ep
                self.af = self.af_start
                self.ep = high
            else:
                # 更新EP和AF
                if low < self.ep:
                    self.ep = low
                    self.af = min(self.af + self.af_step, self.af_max)
        
        self.sar = new_sar
        
        # 更新历史数据
        self.prev_prev_high = self.prev_high
        self.prev_prev_low = self.prev_low
        self.prev_high = high
        self.prev_low = low
        
        return self.sar, self.sar_direction


if __name__ == "__main__":
    # 测试代码
    print("测试流式砖型图构建器...")
    
    # 创建构建器
    builder = StreamingRenkoBuilder(brick_size=10.0)
    
    # 模拟推送K线数据
    test_data = [
        (datetime(2024, 1, 1, 9, 0), 100, 105, 98, 103),
        (datetime(2024, 1, 1, 9, 5), 103, 110, 102, 108),
        (datetime(2024, 1, 1, 9, 10), 108, 115, 107, 112),  # 应该形成上涨砖块
        (datetime(2024, 1, 1, 9, 15), 112, 118, 110, 115),
        (datetime(2024, 1, 1, 9, 20), 115, 125, 114, 122),  # 应该形成上涨砖块
        (datetime(2024, 1, 1, 9, 25), 122, 123, 108, 110),  # 可能反转
        (datetime(2024, 1, 1, 9, 30), 110, 111, 95, 98),   # 应该形成下跌砖块
    ]
    
    for ts, o, h, l, c in test_data:
        new_bricks = builder.push_candle(ts, o, h, l, c)
        if new_bricks:
            for brick in new_bricks:
                print(f"新砖块 #{brick.brick_num}: "
                      f"方向={'↑' if brick.direction == 1 else '↓'}, "
                      f"价格={brick.brick_open:.1f}→{brick.brick_close:.1f}, "
                      f"完成于={brick.completed_at}")
    
    print(f"\n总共形成 {len(builder.bricks)} 个砖块")
    print(f"当前趋势: {builder.get_current_trend()}")
    
    # 测试SAR
    print("\n测试流式SAR...")
    sar_calc = StreamingParabolicSAR(af_start=0.02, af_step=0.02, af_max=0.2)
    
    for ts, o, h, l, c in test_data:
        sar, direction = sar_calc.update(h, l, c)
        print(f"价格={c:.1f}, SAR={sar:.2f}, 方向={'↑' if direction == 1 else '↓'}")
