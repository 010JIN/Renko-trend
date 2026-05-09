"""
砖型图反转策略 (Renko Reversal Strategy)
策略规则：
1. 两块同向砖块 = 趋势确立
2. 趋势反转时：立刻平仓当前持仓，并反向开仓
3. 固定本金：10000 USDT
4. 仓位管理：剩余保证金全仓交易
5. 无杠杆（1x）

新增支持：
- contract_multiplier：合约点值（如 MNQ Micro E-mini = 2 USD/点，NQ E-mini = 20 USD/点，加密货币 = 1）
- max_contracts：最大持仓合约数
- max_daily_loss：每日最大亏损（0=不限制）
- session_filter：交易时段过滤（仅在指定时段内开仓）
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, date
from loguru import logger


@dataclass
class Position:
    """持仓信息"""
    direction: int  # 1=多头, -1=空头, 0=无持仓
    entry_price: float  # 开仓价格
    quantity: float  # 持仓数量
    entry_time: datetime  # 开仓时间
    
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
    pnl: float  # 盈亏（USDT）
    pnl_pct: float  # 盈亏百分比
    balance_before: float  # 交易前余额
    balance_after: float  # 交易后余额
    
    def __str__(self):
        direction_text = "做多 🟢" if self.direction == 1 else "做空 🔴"
        return (f"Trade #{self.trade_id} | {direction_text} | "
                f"进场: {self.entry_price:.2f} @ {self.entry_time} | "
                f"出场: {self.exit_price:.2f} @ {self.exit_time} | "
                f"盈亏: {self.pnl:+.2f} USDT ({self.pnl_pct:+.2%}) | "
                f"余额: {self.balance_before:.2f} → {self.balance_after:.2f}")


class RenkoReversalStrategy:
    """
    砖型图反转策略

    核心逻辑：
    1. 检测趋势反转：连续2个同向砖块表示趋势确立
    2. 当趋势反转时：
       - 如果有持仓：平仓当前持仓
       - 立刻反向开仓（全仓）
    3. 资金管理：每次使用全部可用保证金（无杠杆）

    期货模式（contract_multiplier > 1）：
    - quantity = 合约手数（整数）
    - pnl = 价格差 × quantity × contract_multiplier
    - 例如 MNQ Micro E-mini：1点 = $2，买1张涨10点 = $20
    - 例如 NQ E-mini：1点 = $20，买1张涨10点 = $200
    - contract_multiplier ≤ 1 保留用于加密货币（连续计价，无合约倍数）
    """

    def on_brick(self, brick) -> str:
        """
        推送一根砖块，自动检测趋势、开平仓，返回信号字符串（买/卖/平/无操作）
        brick: 单根砖块（Series或dict）
        """
        # 兼容Series或dict
        direction = brick['direction']
        current_price = brick['brick_close']
        timestamp = brick['timestamp']
        # 维护最近两根方向
        if not hasattr(self, '_recent_directions'):
            self._recent_directions = []
        self._recent_directions.append(direction)
        if len(self._recent_directions) > 2:
            self._recent_directions.pop(0)
        # 检测趋势
        trend = None
        if len(self._recent_directions) == 2 and self._recent_directions[0] == self._recent_directions[1]:
            trend = self._recent_directions[1]
        signal = 'hold'
        if trend is not None:
            if not self.position.is_empty and self.position.direction != trend:
                self.close_position(current_price, timestamp)
                self.open_position(trend, current_price, timestamp)
                signal = 'reverse'
            elif self.position.is_empty:
                self.open_position(trend, current_price, timestamp)
                signal = 'open'
        self.update_equity(current_price)
        return signal
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission_rate: float = 0.0004,  # 手续费率 0.04%
        slippage_rate: float = 0.0001,    # 滑点 0.01%
        contract_multiplier: float = 1.0, # 合约点值倍数（NQ E-mini=20, 加密货币=1）
        max_contracts: int = 1,           # 最大持仓合约数
        max_daily_loss: float = 0.0,      # 每日最大亏损限额（0=不限制）
        session_start_hour: Optional[int] = None,  # 交易时段开始小时（UTC）
        session_end_hour: Optional[int] = None,    # 交易时段结束小时（UTC）
    ):
        """
        初始化策略

        Args:
            initial_capital: 初始资金
            commission_rate: 手续费率（默认0.04%，加密货币适用；期货按固定$/张设置）
            slippage_rate: 滑点率
            contract_multiplier: 合约点值（如 NQ E-mini = 20 USD/点，加密货币 = 1）
            max_contracts: 最大持仓合约数
            max_daily_loss: 每日最大亏损限额，超过后当天不再开仓（0=不限）
            session_start_hour: 只在此小时（UTC）之后开仓，None=不限
            session_end_hour: 只在此小时（UTC）之前开仓，None=不限
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.contract_multiplier = contract_multiplier
        self.max_contracts = max_contracts
        self.max_daily_loss = max_daily_loss
        self.session_start_hour = session_start_hour
        self.session_end_hour = session_end_hour

        # 账户状态
        self.balance = initial_capital  # 当前余额
        self.equity = initial_capital   # 总权益（余额+持仓市值）

        # 持仓
        self.position = Position(
            direction=0,
            entry_price=0.0,
            quantity=0.0,
            entry_time=None
        )
        # 累计手续费
        self.total_commission = 0.0

        # 交易记录
        self.trades: List[Trade] = []
        self.trade_counter = 0

        # 统计信息
        self.max_equity = initial_capital
        self.max_drawdown = 0.0

        # 每日跟踪
        self._daily_pnl: Dict[date, float] = {}   # 每日已实现 P&L
        self._daily_open_balance: Dict[date, float] = {}  # 每日开盘余额
        self._daily_trades: Dict[date, int] = {}  # 每日交易次数
        self._current_day: Optional[date] = None

        logger.info(f"初始化砖型图反转策略: 本金={initial_capital}, "
                   f"手续费={commission_rate:.4%}, 滑点={slippage_rate:.4%}, "
                   f"合约倍数={contract_multiplier}, 最大合约数={max_contracts}, "
                   f"每日限损={max_daily_loss}")
    
    def _update_daily_tracking(self, timestamp: datetime) -> None:
        """每日跟踪初始化"""
        if timestamp is None:
            return
        ts = timestamp if isinstance(timestamp, datetime) else pd.Timestamp(timestamp).to_pydatetime()
        today = ts.date()
        if today != self._current_day:
            self._current_day = today
            self._daily_open_balance[today] = self.balance
            if today not in self._daily_pnl:
                self._daily_pnl[today] = 0.0
            if today not in self._daily_trades:
                self._daily_trades[today] = 0

    def _is_daily_loss_limit_hit(self, timestamp: datetime) -> bool:
        """检查今日是否超过每日最大亏损限制"""
        if self.max_daily_loss <= 0 or timestamp is None:
            return False
        ts = timestamp if isinstance(timestamp, datetime) else pd.Timestamp(timestamp).to_pydatetime()
        today = ts.date()
        open_balance = self._daily_open_balance.get(today, self.balance)
        daily_loss = open_balance - self.balance
        return daily_loss >= self.max_daily_loss

    def _is_in_session(self, timestamp: datetime) -> bool:
        """检查时间戳是否在交易时段内"""
        if self.session_start_hour is None and self.session_end_hour is None:
            return True
        if timestamp is None:
            return True
        ts = timestamp if isinstance(timestamp, datetime) else pd.Timestamp(timestamp).to_pydatetime()
        hour = ts.hour
        if self.session_start_hour is not None and self.session_end_hour is not None:
            if self.session_start_hour < self.session_end_hour:
                return self.session_start_hour <= hour < self.session_end_hour
            else:  # 跨午夜
                return hour >= self.session_start_hour or hour < self.session_end_hour
        if self.session_start_hour is not None:
            return hour >= self.session_start_hour
        if self.session_end_hour is not None:
            return hour < self.session_end_hour
        return True

    def detect_trend_reversal(
        self, 
        renko_df: pd.DataFrame, 
        current_idx: int
    ) -> Optional[int]:
        """
        检测趋势反转
        
        规则：连续2个同向砖块 = 趋势确立
        
        Args:
            renko_df: 砖型图数据
            current_idx: 当前砖块索引
            
        Returns:
            趋势方向：1=上涨, -1=下跌, None=无趋势或数据不足
        """
        # 至少需要2个砖块
        if current_idx < 1:
            return None
        
        # 获取当前和前一个砖块的方向
        current_direction = renko_df.iloc[current_idx]['direction']
        prev_direction = renko_df.iloc[current_idx - 1]['direction']
        
        # 连续2个同向砖块 = 趋势确立
        if current_direction == prev_direction:
            return current_direction
        
        return None
    
    def calculate_position_size(self, price: float) -> float:
        """
        计算开仓数量

        加密货币模式（contract_multiplier=1）：
          quantity = balance / price（碎股）
        期货模式（contract_multiplier>1）：
          quantity = min(max_contracts, floor(balance / (price * contract_multiplier)))
          至少1张（资金不足时不开仓返回0）

        Args:
            price: 开仓价格

        Returns:
            开仓数量（期货=合约张数，加密货币=币数）
        """
        if self.contract_multiplier > 1:
            # 期货：按合约张数，向下取整
            contract_value = price * self.contract_multiplier
            qty = min(self.max_contracts, int(self.balance / contract_value))
            return float(qty)
        else:
            # 加密货币：全仓，预留手续费
            available = self.balance / (1 + self.commission_rate)
            return available / price
    
    def open_position(
        self,
        direction: int,
        price: float,
        timestamp: datetime
    ) -> None:
        """
        开仓

        Args:
            direction: 方向 (1=做多, -1=做空)
            price: 开仓价格
            timestamp: 开仓时间
        """
        self._update_daily_tracking(timestamp)

        # 交易时段过滤
        if not self._is_in_session(timestamp):
            logger.debug(f"非交易时段，跳过开仓 @ {timestamp}")
            return

        # 每日最大亏损过滤
        if self._is_daily_loss_limit_hit(timestamp):
            logger.debug(f"已达每日最大亏损限制，跳过开仓 @ {timestamp}")
            return

        # 计算开仓数量
        quantity = self.calculate_position_size(price)

        # 期货：至少1张才能开仓
        if self.contract_multiplier > 1 and quantity < 1:
            logger.warning(f"资金不足，无法开仓（需至少1张合约）")
            return

        # 考虑滑点
        if direction == 1:
            actual_price = price * (1 + self.slippage_rate)
        else:
            actual_price = price * (1 - self.slippage_rate)

        # 计算手续费
        if self.contract_multiplier > 1:
            # 期货：固定手续费（commission_rate 用作每张合约固定费用时=0）
            commission = quantity * actual_price * self.commission_rate * self.contract_multiplier
        else:
            commission = quantity * actual_price * self.commission_rate
        self.total_commission += commission

        # 更新持仓
        self.position = Position(
            direction=direction,
            entry_price=actual_price,
            quantity=quantity,
            entry_time=timestamp
        )

        self.balance -= commission

        direction_text = "做多 🟢" if direction == 1 else "做空 🔴"
        logger.debug(f"开仓 | {direction_text} | "
                    f"价格: {actual_price:.2f} | "
                    f"数量: {quantity:.4f} | "
                    f"手续费: {commission:.2f} | "
                    f"余额: {self.balance:.2f}")
    
    def close_position(self, price: float, timestamp: datetime) -> Optional[Trade]:
        """
        平仓

        Args:
            price: 平仓价格
            timestamp: 平仓时间

        Returns:
            交易记录
        """
        if self.position.is_empty:
            return None

        # 考虑滑点
        if self.position.is_long:
            actual_price = price * (1 - self.slippage_rate)
        else:
            actual_price = price * (1 + self.slippage_rate)

        # 计算价差盈亏（乘以合约倍数）
        if self.position.is_long:
            raw_pnl = (actual_price - self.position.entry_price) * self.position.quantity * self.contract_multiplier
        else:
            raw_pnl = (self.position.entry_price - actual_price) * self.position.quantity * self.contract_multiplier

        # 平仓手续费
        if self.contract_multiplier > 1:
            commission = self.position.quantity * actual_price * self.commission_rate * self.contract_multiplier
        else:
            commission = self.position.quantity * actual_price * self.commission_rate
        self.total_commission += commission

        net_pnl = raw_pnl - commission
        balance_before = self.balance
        self.balance += net_pnl

        # 每日 P&L 追踪
        self._update_daily_tracking(timestamp)
        if self._current_day is not None:
            self._daily_pnl[self._current_day] = self._daily_pnl.get(self._current_day, 0.0) + net_pnl
            self._daily_trades[self._current_day] = self._daily_trades.get(self._current_day, 0) + 1

        # 计算盈亏百分比（基于开仓时投入的资金）
        invested = self.position.quantity * self.position.entry_price * self.contract_multiplier
        pnl_pct = net_pnl / invested if invested > 0 else 0

        self.trade_counter += 1
        trade = Trade(
            trade_id=self.trade_counter,
            direction=self.position.direction,
            entry_time=self.position.entry_time,
            entry_price=self.position.entry_price,
            exit_time=timestamp,
            exit_price=actual_price,
            quantity=self.position.quantity,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            balance_before=balance_before,
            balance_after=self.balance
        )

        self.trades.append(trade)

        direction_text = "做多 🟢" if self.position.is_long else "做空 🔴"
        logger.info(f"平仓 | {direction_text} | "
                   f"进场: {self.position.entry_price:.2f} → 出场: {actual_price:.2f} | "
                   f"盈亏: {net_pnl:+.2f} ({pnl_pct:+.2%}) | "
                   f"余额: {self.balance:.2f}")

        # 清空持仓
        self.position = Position(
            direction=0,
            entry_price=0.0,
            quantity=0.0,
            entry_time=None
        )

        return trade
    
    def update_equity(self, current_price: float) -> None:
        """
        更新总权益（余额+持仓浮盈）

        Args:
            current_price: 当前价格
        """
        if self.position.is_empty:
            self.equity = self.balance
        else:
            if self.position.is_long:
                unrealized_pnl = (current_price - self.position.entry_price) * self.position.quantity * self.contract_multiplier
            else:
                unrealized_pnl = (self.position.entry_price - current_price) * self.position.quantity * self.contract_multiplier

            self.equity = self.balance + unrealized_pnl

        if self.equity > self.max_equity:
            self.max_equity = self.equity

        drawdown = (self.max_equity - self.equity) / self.max_equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
    
    def run_backtest(self, renko_df: pd.DataFrame) -> Dict:
        """
        运行回测
        
        Args:
            renko_df: 砖型图数据
            
        Returns:
            回测结果统计
        """
        logger.info("="*60)
        logger.info("开始回测砖型图反转策略")
        logger.info("="*60)
        
        # 遍历每个砖块
        for idx in range(len(renko_df)):
            brick = renko_df.iloc[idx]
            current_price = brick['brick_close']
            timestamp = brick['timestamp']
            
            # 检测趋势反转
            trend = self.detect_trend_reversal(renko_df, idx)
            
            if trend is not None:
                # 如果有持仓且方向相反，需要平仓并反向开仓
                if not self.position.is_empty and self.position.direction != trend:
                    # 平仓当前持仓
                    self.close_position(current_price, timestamp)
                    
                    # 反向开仓
                    self.open_position(trend, current_price, timestamp)
                
                # 如果没有持仓，直接开仓
                elif self.position.is_empty:
                    self.open_position(trend, current_price, timestamp)
            
            # 更新权益
            self.update_equity(current_price)
        
        # 如果最后还有持仓，平仓
        if not self.position.is_empty:
            last_brick = renko_df.iloc[-1]
            self.close_position(last_brick['brick_close'], last_brick['timestamp'])
        
        # 计算统计结果
        stats = self.calculate_statistics()
        
        logger.info("\n" + "="*60)
        logger.info("回测完成")
        logger.info("="*60)
        
        return stats
    
    def calculate_statistics(self) -> Dict:
        """计算回测统计数据"""
        if not self.trades:
            return {
                'total_trades': 0,
                'final_balance': self.balance,
                'total_return': 0.0,
                'total_return_pct': 0.0,
                'trades': [],
                'daily_pnl': self._daily_pnl,
                'daily_trades': self._daily_trades,
            }

        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_trades if total_trades > 0 else 0

        total_pnl = sum(t.pnl for t in self.trades)
        total_return_pct = (self.balance - self.initial_capital) / self.initial_capital

        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0

        profit_factor = (
            abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades))
            if losing_trades and sum(t.pnl for t in losing_trades) != 0
            else float('inf') if winning_trades else 0
        )

        # 日均交易次数
        if self._daily_trades:
            avg_daily_trades = np.mean(list(self._daily_trades.values()))
            days_with_trades = sum(1 for v in self._daily_trades.values() if v > 0)
        else:
            avg_daily_trades = 0
            days_with_trades = 0

        # 盈利日统计（对 Profimr 出金号有用）
        profitable_days = sum(1 for v in self._daily_pnl.values() if v > 0)
        profitable_days_200 = sum(1 for v in self._daily_pnl.values() if v >= 200)

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
            'total_commission': self.total_commission,
            'avg_daily_trades': avg_daily_trades,
            'days_with_trades': days_with_trades,
            'profitable_days': profitable_days,
            'profitable_days_200': profitable_days_200,
            'daily_pnl': self._daily_pnl,
            'daily_trades': self._daily_trades,
            'trades': self.trades,
        }

        return stats
    
    def print_statistics(self, stats: Dict) -> None:
        """打印统计结果"""
        logger.info("\n" + "="*60)
        logger.info("📊 回测统计结果")
        logger.info("="*60)
        
        logger.info(f"\n💰 资金情况:")
        logger.info(f"  初始资金: ${stats['initial_capital']:,.2f}")
        logger.info(f"  最终余额: ${stats['final_balance']:,.2f}")
        logger.info(f"  总盈亏: ${stats['total_return']:+,.2f}")
        logger.info(f"  总收益率: {stats['total_return_pct']:+.2%}")
        logger.info(f"  最大权益: ${stats['max_equity']:,.2f}")
        logger.info(f"  最大回撤: {stats['max_drawdown']:.2%}")
        
        logger.info(f"\n📈 交易统计:")
        logger.info(f"  总交易次数: {stats['total_trades']}")
        logger.info(f"  盈利次数: {stats['winning_trades']} ({stats['win_rate']:.2%})")
        logger.info(f"  亏损次数: {stats['losing_trades']}")
        logger.info(f"  平均盈利: ${stats['avg_win']:+.2f}")
        logger.info(f"  平均亏损: ${stats['avg_loss']:+.2f}")
        logger.info(f"  盈亏比: {stats['profit_factor']:.2f}")
        
        logger.info("\n" + "="*60)
    
    def print_all_trades(self) -> None:
        """打印所有交易记录"""
        if not self.trades:
            logger.info("无交易记录")
            return
        
        logger.info("\n" + "="*60)
        logger.info("📝 详细交易记录")
        logger.info("="*60)
        
        for trade in self.trades:
            logger.info(str(trade))
        
        logger.info("="*60)
